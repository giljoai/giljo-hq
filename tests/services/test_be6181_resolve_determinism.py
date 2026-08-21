# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6181 — SequenceChainContextResolver.resolve determinism on write failure.

Regression at the FAILING layer. The alpha observed: the FIRST get_job_mission of
a fresh impl session returned the generic SOLO protocol (no CH_CHAIN_DRIVE); a
second read moments later (same job) carried the chain chapters. Root cause: the
conductor self-registration WRITE inside resolve() can transiently fail/conflict
on the first concurrent touch; conductor_chain_injector wraps the WHOLE resolve in
try/except and falls back to SOLO on ANY error -> read #1 misses.

Fix: the self-registration write is non-fatal to CLASSIFICATION. The conductor
role is decided deterministically from resolved_order[0] BEFORE the write, so a
write failure must NOT propagate — resolve() STILL returns role="conductor", and
the injector injects CH_CHAIN_DRIVE on read #1.

DB-touching: db_session fixture (TransactionalTestContext). Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.conductor_chain_injector import inject_conductor_chain_drive
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed_head_run(session: AsyncSession, tenant: str) -> tuple[str, str]:
    """Seed a head project + an active run with conductor_agent_id NULL (first touch)."""
    head_pid = str(uuid.uuid4())
    p2 = str(uuid.uuid4())
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=head_pid,
        name=f"BE-6181 det {uuid.uuid4().hex[:6]}",
        description="Determinism test.",
        mission="Drive run.",
        status="active",
        tenant_key=tenant,
        product_id=_owning_product_project.id,
        series_number=1,
        execution_mode="claude_code_cli",
        implementation_launched_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    session.add(project)
    run = SequenceRun(
        id=str(uuid.uuid4()),
        tenant_key=tenant,
        project_ids=[head_pid, p2],
        resolved_order=[head_pid, p2],
        current_index=0,
        execution_mode="claude_code_cli",
        status="running",
        review_policy="per_card",
        project_statuses={},
        conductor_agent_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)
    session.info["tenant_key"] = tenant
    await session.flush()
    return head_pid, run.id


async def test_resolve_returns_conductor_when_self_registration_write_fails(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """A transient self-registration write failure does NOT demote resolve() to solo."""
    tenant = TenantManager.generate_tenant_key()
    head_pid, _run_id = await _seed_head_run(db_session, tenant)

    resolver = SequenceChainContextResolver(
        db_manager=None,
        tenant_manager=TenantManager(),
        test_session=db_session,
    )

    # Force the self-registration WRITE to blow up (the transient conflict the
    # alpha hit). Only the write is patched; classification is upstream.
    from giljo_mcp.services.sequence_run_service import SequenceRunService

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated transient self-registration write conflict")

    monkeypatch.setattr(SequenceRunService, "update", _boom)

    chain_ctx = await resolver.resolve(
        db_session,
        project_id=head_pid,
        tenant_key=tenant,
        orchestrator_agent_id="cond-fresh-session",
        is_staging=False,
    )

    assert chain_ctx is not None, "resolve must NOT return None (solo) on a write failure"
    assert chain_ctx.role == "conductor", "role is decided from resolved_order[0], independent of the write"


async def test_injector_yields_chain_drive_on_first_read_despite_write_failure(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """End-to-end: the injector still appends CH_CHAIN_DRIVE on read #1 when the
    self-registration write fails (the determinism the alpha needed)."""
    tenant = TenantManager.generate_tenant_key()
    head_pid, _run_id = await _seed_head_run(db_session, tenant)

    from giljo_mcp.services.sequence_run_service import SequenceRunService

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated transient self-registration write conflict")

    monkeypatch.setattr(SequenceRunService, "update", _boom)

    mission_svc = MissionService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)

    class _Job:
        job_type = "orchestrator"
        project_id = head_pid
        job_id = "job-head"

    class _Exec:
        agent_id = "cond-fresh-session"

    project = await db_session.get(Project, head_pid)
    base = "SOLO ORCHESTRATOR PROTOCOL"

    out = await inject_conductor_chain_drive(mission_svc, base, _Job(), _Exec(), project, tenant)

    assert "CH_CHAIN_DRIVE" in out, "CH_CHAIN_DRIVE must inject on read #1 even when the registration write fails"
    assert base in out
