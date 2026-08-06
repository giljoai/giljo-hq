# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6165e — chain lifecycle: list_active service + continuation-prompt chain brief.

Regression at the failing layer:
- ``SequenceRunService.list_active`` is the missing durable-election read-back —
  test tenant isolation + status filter at the service write/read boundary.
- ``build_continuation_prompt`` gains an optional chain brief — test it appears
  when run_id is supplied and is ABSENT (byte-identical solo) when it is not.

Endpoint-level release/list tests live in
tests/integration/test_be6165e_lifecycle_endpoints.py.

Parallel-safety: DB-touching tests use the db_session fixture
(TransactionalTestContext); the autouse teardown wipes sequence_runs because the
service COMMITs through the injected session (same pattern as RoadmapService),
which escapes the rollback (per-worker DB, serial tests -> a table delete is safe).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.thin_prompt_generator import build_continuation_prompt


pytestmark = pytest.mark.asyncio

_MODE = "claude_code_cli"


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        # Raw SQL scoped to THIS test's seeded rows: they are committed (escape
        # rollback), a cross-tenant ORM delete trips the tenant guard, and a
        # blanket wipe would hit other tests' projects (shared per-worker DB).
        # A textual DELETE is not an ORM construct, so the guard's
        # do_orm_execute hook skips it.
        await session.execute(text("DELETE FROM projects WHERE name LIKE 'chain-member-%'"))
        await session.commit()


def _svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=None, session=session)


async def _seed_live_project(session: AsyncSession, tenant: str) -> str:
    """Insert a live (non-terminal) project row so list_active's BE-6200 live-member
    filter keeps the run that references it. A real chain always has real member
    projects; the default INACTIVE status is non-terminal -> 'live'."""
    pid = str(uuid.uuid4())
    session.add(
        Project(
            id=pid,
            tenant_key=tenant,
            name=f"chain-member-{pid[:8]}",
            description="live chain member",
            mission="member mission",
        )
    )
    await session.flush()
    return pid


async def _create(svc: SequenceRunService, tenant: str, *, status: str = "pending") -> dict:
    pa = await _seed_live_project(svc._session, tenant)
    pb = await _seed_live_project(svc._session, tenant)
    return await svc.create(
        project_ids=[pa, pb],
        resolved_order=[pa, pb],
        execution_mode=_MODE,
        status=status,
        project_statuses={pa: "pending", pb: "pending"},
        tenant_key=tenant,
    )


# ---------------------------------------------------------------------------
# list_active — tenant isolation + status filter
# ---------------------------------------------------------------------------


async def test_list_active_tenant_isolation(db_session: AsyncSession) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    svc = _svc(db_session)

    a1 = await _create(svc, tenant_a)
    a2 = await _create(svc, tenant_a, status="running")
    await _create(svc, tenant_b)

    runs_a = await svc.list_active(tenant_key=tenant_a)
    ids_a = {r["id"] for r in runs_a}
    assert ids_a == {a1["id"], a2["id"]}, "tenant A must see only its own active runs"

    runs_b = await svc.list_active(tenant_key=tenant_b)
    assert all(r["tenant_key"] == tenant_b for r in runs_b)
    assert a1["id"] not in {r["id"] for r in runs_b}, "TENANT LEAK: B saw A's run"


async def test_list_active_status_filter(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session)

    pending = await _create(svc, tenant, status="pending")
    done = await _create(svc, tenant, status="pending")
    await svc.update(run_id=done["id"], tenant_key=tenant, status="completed")

    # Default active filter excludes completed.
    active = await svc.list_active(tenant_key=tenant)
    active_ids = {r["id"] for r in active}
    assert pending["id"] in active_ids
    assert done["id"] not in active_ids, "completed run must be excluded from the active default"

    # Explicit completed filter returns it.
    completed = await svc.list_active(tenant_key=tenant, statuses=("completed",))
    assert {r["id"] for r in completed} == {done["id"]}


async def test_list_active_rejects_invalid_status(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session)
    with pytest.raises(ValidationError):
        await svc.list_active(tenant_key=tenant, statuses=("not_a_status",))


# ---------------------------------------------------------------------------
# build_continuation_prompt — chain brief present / absent
# ---------------------------------------------------------------------------


def test_continuation_prompt_carries_chain_brief() -> None:
    run_id = str(uuid.uuid4())
    order = ["proj-head", "proj-2", "proj-3"]
    prompt = build_continuation_prompt(
        project_id="proj-head",
        agent_id="agent-1",
        job_id="job-1",
        run_id=run_id,
        current_index=1,
        resolved_order=order,
        overarching_mission="Ship the whole widget pipeline end to end.",
    )
    assert "CHAIN CONTINUATION" in prompt
    assert run_id in prompt
    assert "proj-head -> proj-2 -> proj-3" in prompt
    assert "Ship the whole widget pipeline end to end." in prompt
    assert "Resume at index: 1" in prompt
    # The sacred per-project gate must be spelled out (never batch-unlock).
    assert "launch_implementation per project" in prompt


def test_continuation_prompt_solo_unchanged_without_run() -> None:
    """No run_id => byte-identical solo continuation (no chain brief)."""
    solo = build_continuation_prompt(
        project_id="proj-1",
        agent_id="agent-1",
        job_id="job-1",
    )
    assert "CHAIN CONTINUATION" not in solo
    # Sanity: it is still a real continuation prompt.
    assert "CONTINUATION SESSION" in solo
