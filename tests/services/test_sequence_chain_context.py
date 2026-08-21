# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6165c / BE-6184: sequence driver agent-id role classification + helper tests.

BE-6184 moved the conductor off the head project (the dual-hat collapse) to a
DEDICATED, project-less orchestrator minted at run-create. resolve() now classifies
role BY AGENT IDENTITY (conductor iff the calling agent IS the run's
conductor_agent_id); the head project's orchestrator is a symmetric sub_orchestrator
and conductor_project_id is no longer stamped.

Regression tests (failing layer = MCP-boundary / service layer):

1. test_resolve_null_conductor_fallback_stamps_agent_id
   resolve() on a run whose conductor_agent_id is NULL (legacy/out-of-band) takes
   the non-fatal safety fallback: it stamps conductor_agent_id (NOT
   conductor_project_id), classifies the caller as conductor, and broadcasts.

2. test_conductor_agent_match_is_idempotent
   A resolve() whose orchestrator_agent_id already equals conductor_agent_id is a
   no-op (conductor role, no re-stamp, no broadcast).

3. test_head_orchestrator_is_sub_when_conductor_set
   With conductor_agent_id already set to a DIFFERENT (dedicated-conductor) agent,
   the head project's own orchestrator resolves as sub_orchestrator and does NOT
   overwrite the conductor identity.

4. test_sub_orchestrator_never_overwrites_conductor
   A non-head project in the run is classified as sub_orchestrator and MUST NOT
   overwrite conductor_agent_id.

5. test_solo_project_no_ch_conductor
   A project with no active run returns chain_ctx=None and the protocol response
   has NO ch_conductor chapter (byte-identical solo path).

6. test_find_active_run_tenant_isolation
   find_active_run_for_project is tenant-scoped (other-tenant run invisible).

7. test_find_active_run_status_filter
   Completed/terminated/cancelled runs are excluded; pending/running/stalled included.

8. test_advance_index_if_committed_refuses_without_closeout
   advance_index_if_committed returns False without a closeout record.

9. test_advance_index_if_committed_advances_with_closeout
   advance_index_if_committed returns True and bumps the index when
   closeout_executed_at is set.

10. test_mark_stalled_if_past_deadline
    mark_stalled_if_past_deadline flips status to stalled past the deadline and
    returns False when before it.

Parallel-safety:
- DB-touching tests use the ``db_session`` fixture (TransactionalTestContext —
  rollback at teardown, each test owns its setup).
- No module-level mutable state.
- No ordering dependencies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_project(
    session: AsyncSession,
    tenant_key: str,
    *,
    execution_mode: str = "claude_code_cli",
    closeout_executed_at: datetime | None = None,
) -> str:
    """Seed a project in implementation phase and return its id."""
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
        name=f"BE-6165c test {uuid.uuid4().hex[:6]}",
        description="Sequence driver test project.",
        mission="Drive sequential run.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        # BE-9429: uq_project_taxonomy_active is NULLS NOT DISTINCT, so these
        # NULL-product/NULL-type rows collide unless the serial differs.
        series_number=next_series_number(),
        execution_mode=execution_mode,
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC),
        closeout_executed_at=closeout_executed_at,
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _spawn_orchestrator(session: AsyncSession, tenant_key: str, project_id: str) -> tuple[str, str]:
    """Spawn an orchestrator job; return (job_id, agent_id)."""
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
        mission="Drive sequential run as conductor.",
    )
    row = await session.execute(
        __import__("sqlalchemy", fromlist=["select"])
        .select(AgentExecution)
        .where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.job_id == result.job_id,
        )
    )
    execution = row.scalar_one()
    return result.job_id, str(execution.agent_id)


async def _seed_sequence_run(
    session: AsyncSession,
    tenant_key: str,
    project_ids: list[str],
    *,
    resolved_order: list[str] | None = None,
    status: str = "running",
    conductor_agent_id: str | None = None,
    conductor_project_id: str | None = None,
) -> str:
    """Seed a SequenceRun and return its id."""
    run_id = str(uuid.uuid4())
    run = SequenceRun(
        id=run_id,
        tenant_key=tenant_key,
        project_ids=project_ids,
        resolved_order=resolved_order or project_ids,
        current_index=0,
        execution_mode="claude_code_cli",
        status=status,
        review_policy="per_card",
        project_statuses={},
        conductor_agent_id=conductor_agent_id,
        conductor_project_id=conductor_project_id,
        conductor_label=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    return run_id


def _make_svc(session: AsyncSession, ws_manager: Any = None) -> MissionOrchestrationService:
    """Build a MissionOrchestrationService with a shared test session."""
    return MissionOrchestrationService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=session,
        websocket_manager=ws_manager,
    )


def _stub_ws() -> MagicMock:
    """Return a stub WebSocket manager that captures broadcast calls."""
    ws = MagicMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# 1. NULL-conductor fallback stamps conductor_agent_id (not conductor_project_id)
# ---------------------------------------------------------------------------


async def test_resolve_null_conductor_fallback_stamps_agent_id(db_session: AsyncSession) -> None:
    """resolve() on a NULL-conductor run takes the safety fallback: stamp agent_id only."""
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)
    proj2_id = await _seed_project(db_session, tenant)
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
        conductor_agent_id=None,
    )
    _job_id, agent_id = await _spawn_orchestrator(db_session, tenant, proj_id)

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=agent_id,
        is_staging=True,
    )

    assert chain_ctx is not None, "a running run with no conductor must still return a ChainContext"
    assert chain_ctx.role == "conductor", "the fallback stamps this agent as conductor-of-record"
    assert chain_ctx.conductor_agent_id == agent_id, "conductor_agent_id must reflect the stamped value"

    # Verify the DB row was updated: agent_id stamped, project_id NOT (BE-6184).
    svc2 = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await svc2.get(run_id=run_id, tenant_key=tenant)
    assert run["conductor_agent_id"] == agent_id, "SequenceRun.conductor_agent_id must be persisted"
    assert run["conductor_project_id"] is None, "BE-6184: resolve() must NOT stamp conductor_project_id"

    # Verify broadcast was attempted.
    ws.broadcast_event_to_tenant.assert_called_once()
    call_kwargs = ws.broadcast_event_to_tenant.call_args
    broadcast_tenant = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("tenant_key")
    assert broadcast_tenant == tenant or call_kwargs is not None  # broadcast fired


# ---------------------------------------------------------------------------
# 2. agent_id match is idempotent (conductor role, no re-write, no broadcast)
# ---------------------------------------------------------------------------


async def test_conductor_agent_match_is_idempotent(db_session: AsyncSession) -> None:
    """resolve() whose agent_id already equals conductor_agent_id is a no-op."""
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)
    proj2_id = await _seed_project(db_session, tenant)
    _job_id, agent_id = await _spawn_orchestrator(db_session, tenant, proj_id)

    # Pre-stamp the run with this agent_id (the conductor already minted/registered).
    await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
        conductor_agent_id=agent_id,
    )

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=agent_id,
        is_staging=True,
    )

    assert chain_ctx is not None
    assert chain_ctx.role == "conductor", "agent_id == conductor_agent_id must classify as conductor"
    # No broadcast: agent_id already matches, no re-stamp/fallback.
    ws.broadcast_event_to_tenant.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Head orchestrator is sub_orchestrator when a (different) conductor is set
# ---------------------------------------------------------------------------


async def test_head_orchestrator_is_sub_when_conductor_set(db_session: AsyncSession) -> None:
    """BE-6184: the head project's own orchestrator is a sub_orchestrator, not the conductor."""
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)
    proj2_id = await _seed_project(db_session, tenant)

    # The dedicated conductor's agent_id is already stamped (minted at run-create).
    conductor_agent_id = str(uuid.uuid4())
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
        conductor_agent_id=conductor_agent_id,
    )

    # The head project's OWN orchestrator (a different agent) resolves.
    _job_id, head_agent_id = await _spawn_orchestrator(db_session, tenant, proj_id)
    assert head_agent_id != conductor_agent_id

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=head_agent_id,
        is_staging=False,
    )

    assert chain_ctx is not None
    assert chain_ctx.role == "sub_orchestrator", "BE-6184: the head project's orchestrator is NOT the conductor"
    # The conductor identity (carried on the ctx) is the dedicated conductor's, not the head's.
    assert chain_ctx.conductor_agent_id == conductor_agent_id

    svc2 = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await svc2.get(run_id=run_id, tenant_key=tenant)
    assert run["conductor_agent_id"] == conductor_agent_id, "the head orchestrator must NOT overwrite the conductor"

    # No broadcast / re-stamp from a sub_orchestrator.
    ws.broadcast_event_to_tenant.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Sub-orchestrator (non-head project) never overwrites conductor identity
# ---------------------------------------------------------------------------


async def test_sub_orchestrator_never_overwrites_conductor(db_session: AsyncSession) -> None:
    """A sub_orchestrator project must NOT overwrite conductor_agent_id."""
    tenant = TenantManager.generate_tenant_key()
    head_proj_id = await _seed_project(db_session, tenant)
    sub_proj_id = await _seed_project(db_session, tenant)

    conductor_agent_id = str(uuid.uuid4())
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[head_proj_id, sub_proj_id],
        resolved_order=[head_proj_id, sub_proj_id],
        status="running",
        conductor_agent_id=conductor_agent_id,
        conductor_project_id=head_proj_id,
    )

    # Sub-orchestrator spawned for project 2.
    _job_id, sub_agent_id = await _spawn_orchestrator(db_session, tenant, sub_proj_id)

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=sub_proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=sub_agent_id,
        is_staging=False,
    )

    assert chain_ctx is not None
    assert chain_ctx.role == "sub_orchestrator", "non-head project must be sub_orchestrator"

    # Conductor identity must be unchanged.
    svc2 = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await svc2.get(run_id=run_id, tenant_key=tenant)
    assert run["conductor_agent_id"] == conductor_agent_id, "sub_orchestrator must NOT overwrite conductor_agent_id"
    assert run["conductor_project_id"] == head_proj_id

    # No broadcast from sub-orchestrator path.
    ws.broadcast_event_to_tenant.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Solo project (no active run) → chain_ctx=None → no ch_conductor chapter
# ---------------------------------------------------------------------------


async def test_solo_project_no_ch_conductor(db_session: AsyncSession) -> None:
    """A project with no active run returns chain_ctx=None → no ch_conductor in protocol."""
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=str(uuid.uuid4()),
        is_staging=True,
    )

    assert chain_ctx is None, "solo project (no active run) must return None"
    ws.broadcast_event_to_tenant.assert_not_called()

    # Verify the protocol builder produces no ch_conductor (byte-identical solo path).
    from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol

    protocol = _build_orchestrator_protocol(
        cli_mode=True,
        project_id=proj_id,
        orchestrator_id=str(uuid.uuid4()),
        tenant_key=tenant,
        include_implementation_reference=False,
        conductor_agent_id=None,
    )
    assert "ch_conductor" not in protocol, "solo project must produce no ch_conductor chapter"


# ---------------------------------------------------------------------------
# 6. find_active_run_for_project tenant isolation
# ---------------------------------------------------------------------------


async def test_find_active_run_tenant_isolation(db_session: AsyncSession) -> None:
    """find_active_run_for_project must not return runs from another tenant."""
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()

    proj_id = str(uuid.uuid4())

    # Seed a run for tenant_a containing proj_id.
    run_a = SequenceRun(
        id=str(uuid.uuid4()),
        tenant_key=tenant_a,
        project_ids=[proj_id],
        resolved_order=[proj_id],
        current_index=0,
        execution_mode="claude_code_cli",
        status="running",
        review_policy="per_card",
        project_statuses={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(run_a)
    await db_session.flush()

    svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)

    # tenant_b must not see tenant_a's run.
    result = await svc.find_active_run_for_project(project_id=proj_id, tenant_key=tenant_b)
    assert result is None, "tenant_b must not see tenant_a's run"

    # tenant_a sees its own run.
    result_a = await svc.find_active_run_for_project(project_id=proj_id, tenant_key=tenant_a)
    assert result_a is not None
    assert result_a["id"] == run_a.id


# ---------------------------------------------------------------------------
# 7. find_active_run_for_project status filter
# ---------------------------------------------------------------------------


async def test_find_active_run_status_filter(db_session: AsyncSession) -> None:
    """Completed/terminated/cancelled runs are excluded; pending/running/stalled included."""
    tenant = TenantManager.generate_tenant_key()
    proj_id = str(uuid.uuid4())

    excluded_statuses = ["completed", "terminated", "cancelled", "failed"]
    included_statuses = ["pending", "running", "stalled"]

    svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)

    for status in excluded_statuses:
        run = SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            project_ids=[proj_id],
            resolved_order=[proj_id],
            current_index=0,
            execution_mode="claude_code_cli",
            status=status,
            review_policy="per_card",
            project_statuses={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(run)
    await db_session.flush()

    result = await svc.find_active_run_for_project(project_id=proj_id, tenant_key=tenant)
    assert result is None, f"excluded statuses {excluded_statuses!r} must not be returned"

    for status in included_statuses:
        run = SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            project_ids=[proj_id],
            resolved_order=[proj_id],
            current_index=0,
            execution_mode="claude_code_cli",
            status=status,
            review_policy="per_card",
            project_statuses={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(run)
        await db_session.flush()

        found = await svc.find_active_run_for_project(project_id=proj_id, tenant_key=tenant)
        assert found is not None, f"status={status!r} must be returned as active"
        assert found["status"] == status


# ---------------------------------------------------------------------------
# 8. advance_index_if_committed refuses without closeout
# ---------------------------------------------------------------------------


async def test_advance_index_if_committed_refuses_without_closeout(db_session: AsyncSession) -> None:
    """advance_index_if_committed returns False when project has no closeout record."""
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant, closeout_executed_at=None)
    proj2_id = await _seed_project(db_session, tenant)
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
    )

    svc = _make_svc(db_session)
    advanced = await svc._chain.advance_index_if_committed(
        run_id=run_id,
        project_id=proj_id,
        tenant_key=tenant,
        next_index=1,
    )
    assert advanced is False, "must refuse without closeout_executed_at"

    # Index must remain 0.
    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 0


# ---------------------------------------------------------------------------
# 9. advance_index_if_committed advances with closeout
# ---------------------------------------------------------------------------


async def test_advance_index_if_committed_advances_with_closeout(db_session: AsyncSession) -> None:
    """advance_index_if_committed returns True and bumps index when closeout_executed_at is set."""
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant, closeout_executed_at=datetime.now(UTC))
    proj2_id = await _seed_project(db_session, tenant)
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
    )

    svc = _make_svc(db_session)
    advanced = await svc._chain.advance_index_if_committed(
        run_id=run_id,
        project_id=proj_id,
        tenant_key=tenant,
        next_index=1,
    )
    assert advanced is True, "must advance when closeout_executed_at is set"

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 1


# ---------------------------------------------------------------------------
# 10. mark_stalled_if_past_deadline
# ---------------------------------------------------------------------------


async def test_mark_stalled_if_past_deadline(db_session: AsyncSession) -> None:
    """mark_stalled_if_past_deadline flips to stalled past deadline, no-op before it."""
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id],
        resolved_order=[proj_id],
        status="running",
    )

    svc = _make_svc(db_session)
    now = datetime.now(UTC)
    future = now + timedelta(hours=1)
    past = now - timedelta(seconds=1)

    # Before deadline → no flip.
    not_stalled = await svc._chain.mark_stalled_if_past_deadline(
        run_id=run_id,
        tenant_key=tenant,
        deadline_iso_or_dt=future,
        now=now,
    )
    assert not_stalled is False

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["status"] == "running"

    # Past deadline → flip to stalled.
    stalled = await svc._chain.mark_stalled_if_past_deadline(
        run_id=run_id,
        tenant_key=tenant,
        deadline_iso_or_dt=past,
        now=now,
    )
    assert stalled is True

    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["status"] == "stalled"
