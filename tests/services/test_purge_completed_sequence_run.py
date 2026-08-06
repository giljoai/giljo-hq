# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Auto-purge sequence_run on chain completion (Option A) — service-layer regression.

Regression at the FAILING LAYER (SequenceRunService — the owning service and the
ONLY deleter of ``sequence_runs``). Covers ``purge_run``:

  - THE DELETION TEST: after purge the run row is GONE and the conductor's
    project-less AgentJob + AgentExecution are GONE, while the durable record —
    project rows, a 360 memory entry, and a comms message — SURVIVES. Only the
    chain GROUPING is lost.
  - Idempotent: re-calling purge_run on an already-purged run is a clean no-op
    (the hook is best-effort and can fire more than once).
  - Tenant-scoped: purging tenant A's run does NOT touch tenant B's identical run.

Parallel-safety: DB-touching; uses the db_session fixture (TransactionalTestContext).
SequenceRunService COMMITs through the injected session (RoadmapService pattern), so
a function-scoped collector fixture wipes only the tenant_keys each test created — no
module-level mutable state, each test owns its setup + teardown.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.models.tasks import Message
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_MODE = "claude_code_cli"


@pytest_asyncio.fixture
async def cleanup_tenants(db_manager):
    """Collect tenant_keys created by a test; delete their rows at teardown.

    SequenceRunService.create/purge_run COMMIT through the injected session, so
    rows persist on the per-worker DB past the transactional session. Scoping the
    wipe to the tenant_keys this test created keeps it parallel-safe (no global
    truncate, no cross-test interference)."""
    tenants: list[str] = []
    yield tenants
    for tk in tenants:
        # Per-tenant session so the tenant-scope guard is satisfied; child-before-parent FK order.
        async with db_manager.get_session_async(tenant_key=tk) as session:
            await session.execute(delete(Message).where(Message.tenant_key == tk))
            await session.execute(delete(ProductMemoryEntry).where(ProductMemoryEntry.tenant_key == tk))
            await session.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tk))
            await session.execute(delete(AgentJob).where(AgentJob.tenant_key == tk))
            await session.execute(delete(SequenceRun).where(SequenceRun.tenant_key == tk))
            await session.execute(delete(Project).where(Project.tenant_key == tk))
            await session.execute(delete(Product).where(Product.tenant_key == tk))
            await session.commit()


def _seq_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=None, session=session)


async def _create_product(session: AsyncSession, tenant_key: str) -> str:
    product_id = str(uuid.uuid4())
    session.add(Product(id=product_id, tenant_key=tenant_key, name="Purge Test Product"))
    await session.commit()
    return product_id


async def _create_project(session: AsyncSession, tenant_key: str, product_id: str) -> str:
    project_id = str(uuid.uuid4())
    session.add(
        Project(
            id=project_id,
            product_id=product_id,
            name="Purge Test Project",
            description="Purge regression",
            mission="Purge regression mission",
            status="completed",
            tenant_key=tenant_key,
            execution_mode="multi_terminal",
            series_number=random.randint(1, 9000),
        )
    )
    await session.commit()
    return project_id


async def _create_memory(session: AsyncSession, tenant_key: str, product_id: str, project_id: str) -> str:
    entry_id = uuid.uuid4()
    session.add(
        ProductMemoryEntry(
            id=entry_id,
            tenant_key=tenant_key,
            product_id=product_id,
            project_id=project_id,
            sequence=1,
            entry_type="project_completion",
            source="closeout_v1",
            timestamp=datetime.now(UTC),
            summary="Durable 360 memory that must survive the purge.",
        )
    )
    await session.commit()
    return str(entry_id)


async def _create_message(session: AsyncSession, tenant_key: str, project_id: str) -> str:
    message_id = str(uuid.uuid4())
    session.add(
        Message(
            id=message_id,
            tenant_key=tenant_key,
            project_id=project_id,
            content="Durable comms message that must survive the purge.",
        )
    )
    await session.commit()
    return message_id


async def _create_run(session: AsyncSession, tenant_key: str, project_ids: list[str]) -> dict:
    return await _seq_svc(session).create(
        project_ids=project_ids,
        resolved_order=project_ids,
        execution_mode=_MODE,
        status="running",
        project_statuses=dict.fromkeys(project_ids, "completed"),
        tenant_key=tenant_key,
    )


async def _conductor_job_ids(session: AsyncSession, tenant_key: str, run_id: str) -> list[str]:
    """Read back a tenant's conductor job ids under an explicit tenant context.

    SEC-9276: this shared session sees back-to-back setup for MULTIPLE tenants
    (test_purge_is_tenant_scoped seeds tenant A then tenant B), so the session's
    flush-derived tenant context can be stale relative to this call's explicit
    tenant_key predicate by the time it runs. tenant_session_context re-anchors the
    read to the tenant this call is actually asking about -- the guard stays live,
    it is just told the truth about which tenant this query is for.
    """
    with tenant_session_context(session, tenant_key):
        rows = await session.execute(
            select(AgentJob.job_id).where(
                AgentJob.tenant_key == tenant_key,
                AgentJob.project_id.is_(None),
                AgentJob.job_metadata["run_id"].astext == run_id,
            )
        )
    return [r[0] for r in rows.all()]


async def _run_exists(session: AsyncSession, tenant_key: str, run_id: str) -> bool:
    """Read back whether a run row exists, under an explicit tenant context (see
    _conductor_job_ids above for why: the shared session sees multiple tenants)."""
    with tenant_session_context(session, tenant_key):
        row = await session.execute(
            select(SequenceRun.id).where(SequenceRun.id == run_id, SequenceRun.tenant_key == tenant_key)
        )
    return row.scalar_one_or_none() is not None


async def test_purge_deletes_run_and_conductor_but_survivors_live(
    db_session: AsyncSession, cleanup_tenants: list[str]
) -> None:
    """The Deletion Test: run + conductor rows die; project / 360 memory / comms live."""
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    product_id = await _create_product(db_session, tenant)
    p1 = await _create_project(db_session, tenant, product_id)
    p2 = await _create_project(db_session, tenant, product_id)
    memory_id = await _create_memory(db_session, tenant, product_id, p1)
    message_id = await _create_message(db_session, tenant, p1)

    run = await _create_run(db_session, tenant, [p1, p2])
    job_ids = await _conductor_job_ids(db_session, tenant, run["id"])
    assert job_ids, "create() must mint a project-less conductor job linked by run_id"

    result = await _seq_svc(db_session).purge_run(run_id=run["id"], tenant_key=tenant)
    assert result["run_deleted"] is True
    assert result["conductor_jobs_deleted"] == len(job_ids)

    # Run row + conductor AgentJob + AgentExecution are GONE.
    assert not await _run_exists(db_session, tenant, run["id"])
    remaining_jobs = await db_session.execute(select(AgentJob.job_id).where(AgentJob.job_id.in_(job_ids)))
    assert remaining_jobs.scalar_one_or_none() is None
    remaining_execs = await db_session.execute(select(AgentExecution.id).where(AgentExecution.job_id.in_(job_ids)))
    assert remaining_execs.scalar_one_or_none() is None

    # The durable record SURVIVES.
    for pid in (p1, p2):
        row = await db_session.execute(select(Project.id).where(Project.id == pid))
        assert row.scalar_one_or_none() == pid, "project row must survive the purge"
    mem = await db_session.execute(select(ProductMemoryEntry.id).where(ProductMemoryEntry.id == uuid.UUID(memory_id)))
    assert mem.scalar_one_or_none() is not None, "360 memory entry must survive the purge"
    msg = await db_session.execute(select(Message.id).where(Message.id == message_id))
    assert msg.scalar_one_or_none() == message_id, "comms message must survive the purge"


async def test_purge_is_idempotent(db_session: AsyncSession, cleanup_tenants: list[str]) -> None:
    """A second purge_run on the same (already-gone) run is a clean no-op."""
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    product_id = await _create_product(db_session, tenant)
    p1 = await _create_project(db_session, tenant, product_id)
    p2 = await _create_project(db_session, tenant, product_id)
    run = await _create_run(db_session, tenant, [p1, p2])

    first = await _seq_svc(db_session).purge_run(run_id=run["id"], tenant_key=tenant)
    assert first["run_deleted"] is True

    second = await _seq_svc(db_session).purge_run(run_id=run["id"], tenant_key=tenant)
    assert second["run_deleted"] is False
    assert second["conductor_jobs_deleted"] == 0


async def test_purge_is_tenant_scoped(db_session: AsyncSession, cleanup_tenants: list[str]) -> None:
    """Purging tenant A's run leaves tenant B's identical-shaped run untouched."""
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    cleanup_tenants.extend([tenant_a, tenant_b])

    prod_a = await _create_product(db_session, tenant_a)
    a1 = await _create_project(db_session, tenant_a, prod_a)
    a2 = await _create_project(db_session, tenant_a, prod_a)
    run_a = await _create_run(db_session, tenant_a, [a1, a2])

    prod_b = await _create_product(db_session, tenant_b)
    b1 = await _create_project(db_session, tenant_b, prod_b)
    b2 = await _create_project(db_session, tenant_b, prod_b)
    run_b = await _create_run(db_session, tenant_b, [b1, b2])
    b_job_ids = await _conductor_job_ids(db_session, tenant_b, run_b["id"])
    assert b_job_ids

    await _seq_svc(db_session).purge_run(run_id=run_a["id"], tenant_key=tenant_a)

    # Tenant A: gone. Tenant B: fully intact.
    assert not await _run_exists(db_session, tenant_a, run_a["id"])
    assert await _run_exists(db_session, tenant_b, run_b["id"]), "tenant B's run must be untouched"
    b_jobs = await _conductor_job_ids(db_session, tenant_b, run_b["id"])
    assert set(b_jobs) == set(b_job_ids), "tenant B's conductor jobs must be untouched"
    b_exec = await db_session.execute(select(AgentExecution.id).where(AgentExecution.job_id.in_(b_job_ids)))
    assert b_exec.scalar_one_or_none() is not None, "tenant B's conductor execution must be untouched"
