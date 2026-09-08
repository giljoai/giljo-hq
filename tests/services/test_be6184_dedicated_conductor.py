# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6184: dedicated, project-less chain conductor (foundation).

Moves the chain "conductor" off the head project's orchestrator (the dual-hat
collapse that caused the alpha dead-end) to a DEDICATED, PROJECT-LESS orchestrator
minted at run-create. Regression at the failing layer (service + resolver):

1. test_create_mints_projectless_conductor_job
   SequenceRunService.create inserts a conductor AgentJob with project_id IS NULL
   and stamps run.conductor_agent_id to that job's execution agent_id.

2. test_conductor_insert_failure_rolls_back_run
   A forced conductor-mint failure rolls back the WHOLE run create: no orphan run,
   no orphan job.

3. test_resolve_classifies_by_agent_id
   resolve() returns role="conductor" for the conductor agent_id and
   role="sub_orchestrator" for the head project's orchestrator on the same run.

4. test_solo_resolve_returns_none_deletion
   DELETION TEST: a solo project (no active run) → resolve() returns None and the
   injector renders the runtime protocol byte-identical to the no-chain render.

5. test_projectless_conductor_injector_gets_chain_drive
   A project-less conductor's runtime injection (implementation phase) does NOT
   crash on NULL project_id and CONTAINS CH_CHAIN_DRIVE (injector repoint proven).

6. test_tolerance_legacy_conductor_project_id_still_resolves
   A run row with conductor_project_id=<head_pid> set (an in-flight alpha run) still
   resolves the conductor by conductor_agent_id (no crash, no rewrite).

Parallel-safe: DB-touching tests use the db_session fixture
(TransactionalTestContext, rollback at teardown). No module-level mutable state.
Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.conductor_chain_injector import inject_conductor_chain_drive
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_project(session: AsyncSession, tenant_key: str, *, launched: bool = True) -> str:
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6184 {uuid.uuid4().hex[:6]}",
        description="Dedicated conductor test project.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        # BE-9429: uq_project_taxonomy_active is NULLS NOT DISTINCT, so these
        # NULL-product/NULL-type rows collide unless the serial differs.
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC) if launched else None,
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _spawn_orchestrator(session: AsyncSession, tenant_key: str, project_id: str) -> str:
    """Spawn a project-bound orchestrator; return its agent_id."""
    lifecycle = JobLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=session,
    )
    result = await lifecycle.spawn_job(
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        project_id=project_id,
        tenant_key=tenant_key,
        mission="Sub-orchestrator for a chain member.",
    )
    row = await session.execute(
        select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.job_id == result.job_id,
        )
    )
    return str(row.scalar_one().agent_id)


def _run_svc(session: AsyncSession, *, websocket_manager=None) -> SequenceRunService:
    return SequenceRunService(
        db_manager=None,
        tenant_manager=TenantManager(),
        session=session,
        websocket_manager=websocket_manager,
    )


# ---------------------------------------------------------------------------
# 1. create mints a project-less conductor job + stamps conductor_agent_id
# ---------------------------------------------------------------------------


async def test_create_mints_projectless_conductor_job(db_session: AsyncSession) -> None:
    """create() inserts a conductor AgentJob (project_id IS NULL) + stamps conductor_agent_id."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    svc = _run_svc(db_session)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )

    conductor_agent_id = run["conductor_agent_id"]
    assert conductor_agent_id is not None, "create() must stamp conductor_agent_id"
    assert run["conductor_project_id"] is None, "the dedicated conductor owns NO project"

    # The conductor execution exists with that agent_id, and its job is project-less.
    row = await db_session.execute(
        select(AgentExecution, AgentJob)
        .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
        .where(
            AgentExecution.tenant_key == tenant,
            AgentExecution.agent_id == conductor_agent_id,
        )
    )
    execution, job = row.one()
    assert job.project_id is None, "conductor AgentJob.project_id must be NULL"
    assert job.job_type == "orchestrator"
    assert execution.project_phase == "implementation"


# ---------------------------------------------------------------------------
# 2. a forced conductor-mint failure rolls back the whole run
# ---------------------------------------------------------------------------


async def test_conductor_insert_failure_rolls_back_run(db_session: AsyncSession, monkeypatch) -> None:
    """A conductor-mint failure rolls back the run create: no orphan run, no orphan job."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    from giljo_mcp.services import sequence_run_service as srs_module

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated conductor mint failure")

    monkeypatch.setattr(srs_module, "mint_conductor_job", _boom)

    svc = _run_svc(db_session)
    with pytest.raises(Exception):  # noqa: B017 (create wraps as BaseGiljoError; the point is it raises)
        await svc.create(
            project_ids=[p1, p2],
            resolved_order=[p1, p2],
            execution_mode="claude_code_cli",
            tenant_key=tenant,
        )

    # No run persisted for this tenant.
    runs = await db_session.execute(select(SequenceRun).where(SequenceRun.tenant_key == tenant))
    assert runs.scalars().first() is None, "a failed conductor mint must leave NO orphan run"

    # No orphan project-less orchestrator job persisted for this tenant.
    jobs = await db_session.execute(
        select(AgentJob).where(
            AgentJob.tenant_key == tenant,
            AgentJob.job_type == "orchestrator",
            AgentJob.project_id.is_(None),
        )
    )
    assert jobs.scalars().first() is None, "a failed conductor mint must leave NO orphan conductor job"


# ---------------------------------------------------------------------------
# BE-9440 Phase 1: create() broadcasts agent:created for the freshly minted conductor
# ---------------------------------------------------------------------------


class _RecordingWebsocketManager:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def broadcast_to_tenant(self, *, tenant_key, event_type, data):
        self.calls.append({"tenant_key": tenant_key, "event_type": event_type, "data": data})


async def test_create_broadcasts_agent_created_for_conductor(db_session: AsyncSession) -> None:
    """create() emits agent:created for the conductor AFTER its commit lands.

    BE-9440 Phase 1: previously the mint broadcast nothing, so a freshly minted
    chain conductor appeared on no dashboard until a manual refresh.
    """
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    ws = _RecordingWebsocketManager()
    svc = _run_svc(db_session, websocket_manager=ws)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )

    agent_created_calls = [c for c in ws.calls if c["event_type"] == "agent:created"]
    assert len(agent_created_calls) == 1, "exactly one agent:created for the minted conductor"
    data = agent_created_calls[0]["data"]
    assert data["agent_id"] == run["conductor_agent_id"]
    assert data["project_id"] is None, "the dedicated conductor owns NO project"
    assert data["chain_conductor"] is True


# ---------------------------------------------------------------------------
# 3. resolve() classifies by agent_id (conductor vs sub_orchestrator)
# ---------------------------------------------------------------------------


async def test_resolve_classifies_by_agent_id(db_session: AsyncSession) -> None:
    """resolve(): conductor agent_id → conductor; head project's orchestrator → sub_orchestrator."""
    tenant = TenantManager.generate_tenant_key()
    head_pid = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    svc = _run_svc(db_session)
    run = await svc.create(
        project_ids=[head_pid, p2],
        resolved_order=[head_pid, p2],
        execution_mode="claude_code_cli",
        status="running",
        tenant_key=tenant,
    )
    conductor_agent_id = run["conductor_agent_id"]

    head_orch_agent_id = await _spawn_orchestrator(db_session, tenant, head_pid)
    assert head_orch_agent_id != conductor_agent_id

    resolver = SequenceChainContextResolver(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)

    # The dedicated conductor (resolving via the head project_id it is driving) is the conductor.
    conductor_ctx = await resolver.resolve(
        db_session,
        project_id=head_pid,
        tenant_key=tenant,
        orchestrator_agent_id=conductor_agent_id,
        is_staging=False,
    )
    assert conductor_ctx is not None
    assert conductor_ctx.role == "conductor", "the run's conductor_agent_id must classify as conductor"

    # The head project's OWN orchestrator is now a symmetric sub_orchestrator.
    head_ctx = await resolver.resolve(
        db_session,
        project_id=head_pid,
        tenant_key=tenant,
        orchestrator_agent_id=head_orch_agent_id,
        is_staging=False,
    )
    assert head_ctx is not None
    assert head_ctx.role == "sub_orchestrator", "the head project's orchestrator is no longer the conductor"

    # The sub-orchestrator must NOT have overwritten the conductor identity.
    refreshed = await svc.get(run_id=run["id"], tenant_key=tenant)
    assert refreshed["conductor_agent_id"] == conductor_agent_id
    assert refreshed["conductor_project_id"] is None, "resolve() must not stamp conductor_project_id"


# ---------------------------------------------------------------------------
# 4. DELETION TEST: solo project → resolve() None → injector byte-identical
# ---------------------------------------------------------------------------


async def test_solo_resolve_returns_none_deletion(db_session: AsyncSession) -> None:
    """Solo project (no active run): resolve() None and the injected protocol is byte-identical."""
    tenant = TenantManager.generate_tenant_key()
    solo_pid = await _seed_project(db_session, tenant)

    resolver = SequenceChainContextResolver(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)
    chain_ctx = await resolver.resolve(
        db_session,
        project_id=solo_pid,
        tenant_key=tenant,
        orchestrator_agent_id=str(uuid.uuid4()),
        is_staging=False,
    )
    assert chain_ctx is None, "a solo project (no active run) must resolve to None"

    # The injector no-ops → runtime protocol returned byte-identical (Deletion Test).
    mission_svc = MissionService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)

    class _Job:
        job_type = "orchestrator"
        project_id = solo_pid
        job_id = "job-solo"

    class _Exec:
        agent_id = str(uuid.uuid4())

    project = await db_session.get(Project, solo_pid)
    base = "SOLO ORCHESTRATOR PROTOCOL - startup / coordination / closeout"
    out = await inject_conductor_chain_drive(mission_svc, base, _Job(), _Exec(), project, tenant)
    assert out == base, "solo injection must return the protocol byte-identical (no chain chapters)"


# ---------------------------------------------------------------------------
# 5. project-less conductor injector gets CH_CHAIN_DRIVE (no NULL-project crash)
# ---------------------------------------------------------------------------


async def test_projectless_conductor_injector_gets_chain_drive(db_session: AsyncSession) -> None:
    """A project-less conductor (job.project_id=None) in impl phase gains CH_CHAIN_DRIVE."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    svc = _run_svc(db_session)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        status="running",
        tenant_key=tenant,
    )
    conductor_agent_id = run["conductor_agent_id"]

    mission_svc = MissionService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)

    class _Job:
        job_type = "orchestrator"
        project_id = None  # the dedicated conductor owns NO project
        job_id = "job-conductor"

    class _Exec:
        agent_id = conductor_agent_id

    base = "SOLO ORCHESTRATOR PROTOCOL"
    # project=None must NOT crash; the gate is the RUN phase, not a project row.
    out = await inject_conductor_chain_drive(mission_svc, base, _Job(), _Exec(), None, tenant)
    assert "CH_CHAIN_DRIVE" in out, "the project-less conductor must receive CH_CHAIN_DRIVE"
    assert base in out


# ---------------------------------------------------------------------------
# 6. tolerance: a legacy conductor_project_id row still resolves by agent_id
# ---------------------------------------------------------------------------


async def test_tolerance_legacy_conductor_project_id_still_resolves(db_session: AsyncSession) -> None:
    """An in-flight alpha run with conductor_project_id set still resolves the conductor by agent_id."""
    tenant = TenantManager.generate_tenant_key()
    head_pid = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    legacy_conductor_agent_id = str(uuid.uuid4())
    # Hand-seed an alpha-shaped run: conductor_project_id set to the head pid.
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
        conductor_agent_id=legacy_conductor_agent_id,
        conductor_project_id=head_pid,  # the alpha dual-hat shape
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(run)
    await db_session.flush()

    resolver = SequenceChainContextResolver(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)
    ctx = await resolver.resolve(
        db_session,
        project_id=head_pid,
        tenant_key=tenant,
        orchestrator_agent_id=legacy_conductor_agent_id,
        is_staging=False,
    )
    assert ctx is not None
    assert ctx.role == "conductor", "tolerance: the stored conductor_agent_id still classifies as conductor"

    # The legacy conductor_project_id is read-tolerated, NOT rewritten.
    run_svc = _run_svc(db_session)
    refreshed = await run_svc.get(run_id=run.id, tenant_key=tenant)
    assert refreshed["conductor_project_id"] == head_pid, "tolerance: the legacy value must not be rewritten"
    assert refreshed["conductor_agent_id"] == legacy_conductor_agent_id
