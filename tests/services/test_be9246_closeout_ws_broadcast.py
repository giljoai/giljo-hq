# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9246 — closeout agent-status transitions must broadcast agent:status_changed.

The bug: two closeout transitions land in the DB but emit no per-agent WebSocket
event, so dashboard agent tiles go stale until a manual refresh:

1. Force-decommission (``ProjectCloseoutService.decommission_project_agents``,
   driven by ``tools/project_closeout._handle_force_close`` under
   ``write_project_closeout(force=true)``): active agents -> 'decommissioned'.
2. Complete -> closed (``ProjectCloseoutService.close_completed_agents``, driven
   by ``close_completed_agents_with_commit`` from the archive REST endpoint):
   'complete' agents -> 'closed'.

Fix contract: both service helpers now additionally return one
``AgentStatusChangeEvent`` per transitioned agent (old_status captured BEFORE the
status overwrite), and the owning caller broadcasts ``agent:status_changed`` (the
SAME shape ``OrchestrationAgentStateService._broadcast_completion`` / ``close_job``
already emit) exactly once per agent, strictly POST-COMMIT.

Tests 1-2 exercise ``close_completed_agents_with_commit`` (owns its own commit
even under an injected test_session, so "post-commit, never mid-flush" is
directly provable via commit-then-emit ordering).

Tests 3-4 exercise the decommission-side data contract at the service/tool seam
(``decommission_project_agents`` / ``_handle_force_close``) — the two-hop
build-then-broadcast split the design mandates so a rollback can never announce
a status change that didn't happen.

Test 5 drives the real force-close entrypoint end-to-end
(``close_project_and_update_memory``) with a session it OWNS (the normal
MCP-tool call shape: ``session=None``), proving the broadcast fires once the
outer ``async with`` has actually committed. This intentionally uses a real
committed ``db_manager`` session (not the rollback-based ``db_session``
TransactionalTestContext fixture): ``close_project_and_update_memory`` only
broadcasts when it owns the session, and every other seam in this suite is
covered by tests 1-4, which are TransactionalTestContext-safe.

DB-touching: tests 1-4 use ``db_session`` (TransactionalTestContext, rolled
back). Test 5 commits through a real ``db_manager`` session and cleans up via
``purge_tenant_rows``. No module-level mutable state, no ordering dependencies,
parallel-safe (pytest-xdist -n auto). Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.closeout_ws_broadcast import build_agent_status_change_events
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.project_closeout import _handle_force_close, close_project_and_update_memory
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    ws.broadcast_project_update = AsyncMock()
    return ws


def _status_changed_events(mock_ws: MagicMock) -> list[dict[str, Any]]:
    """Every agent:status_changed payload the mock's broadcast_to_tenant received."""
    events: list[dict[str, Any]] = []
    for call in mock_ws.broadcast_to_tenant.await_args_list:
        kwargs = call.kwargs
        if kwargs.get("event_type") == "agent:status_changed":
            events.append(kwargs.get("data") or {})
    return events


async def _seed_project(session: AsyncSession, tenant_key: str, *, product_id: str | None = None) -> str:
    """Minimal project row (FK target for AgentJob.project_id); product_id optional."""
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE-9246 {uuid.uuid4().hex[:8]}",
        description="BE-9246 closeout WS broadcast regression.",
        mission="Prove closeout emits per-agent status events.",
        status="active",
    )
    session.add(project)
    await session.flush()
    return project.id


async def _seed_execution(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    status: str,
    display_name: str = "implementer",
) -> tuple[str, str]:
    """Seed one AgentJob + AgentExecution; returns (job_id, agent_id)."""
    job_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=display_name if display_name == "orchestrator" else "implementer",
        mission="BE-9246 fixture agent",
        status="active",
        created_at=datetime.now(UTC),
    )
    session.add(job)
    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name=display_name,
        agent_name=display_name,
        status=status,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        completed_at=datetime.now(UTC) - timedelta(minutes=1) if status in ("complete", "closed") else None,
    )
    session.add(execution)
    await session.flush()
    return job_id, agent_id


# ---------------------------------------------------------------------------
# 1-2: close_completed_agents_with_commit (complete -> closed)
# ---------------------------------------------------------------------------


async def test_close_completed_agents_with_commit_broadcasts_post_commit(db_session: AsyncSession) -> None:
    """The fail-first case: today this never emits anything at all."""
    tenant_key = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant_key)
    job_id, _agent_id = await _seed_execution(db_session, tenant_key, project_id, status="complete")

    mock_ws = _mock_ws()
    svc = ProjectCloseoutService(
        db_manager=None,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=mock_ws,
    )

    closed_names = await svc.close_completed_agents_with_commit(project_id=project_id, tenant_key=tenant_key)

    assert closed_names == ["implementer"], "existing list[str] return contract must stay unchanged"

    events = _status_changed_events(mock_ws)
    assert len(events) == 1, "exactly one agent:status_changed event for the one transitioned agent"
    event = events[0]
    assert event["job_id"] == job_id
    assert event["old_status"] == "complete"
    assert event["status"] == "closed"
    assert event["agent_display_name"] == "implementer"


async def test_close_completed_agents_with_commit_never_emits_before_commit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mid-flush guard: if the commit itself fails, no broadcast may have fired.

    Proves the ordering is commit-THEN-emit, not emit-regardless-of-commit --
    the DoD's "no emit occurs if the transaction rolls back."
    """
    tenant_key = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant_key)
    await _seed_execution(db_session, tenant_key, project_id, status="complete")

    mock_ws = _mock_ws()
    svc = ProjectCloseoutService(
        db_manager=None,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=mock_ws,
    )

    monkeypatch.setattr(db_session, "commit", AsyncMock(side_effect=RuntimeError("simulated commit failure")))

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await svc.close_completed_agents_with_commit(project_id=project_id, tenant_key=tenant_key)

    mock_ws.broadcast_to_tenant.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3-4: decommission_project_agents / _handle_force_close data contract
# ---------------------------------------------------------------------------


async def test_decommission_project_agents_captures_old_status_before_overwrite(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant_key)
    job_id, agent_id = await _seed_execution(db_session, tenant_key, project_id, status="working")

    svc = ProjectCloseoutService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)

    names, events = await svc.decommission_project_agents(
        session=db_session, project_id=project_id, tenant_key=tenant_key
    )

    assert names == ["implementer"], "existing list[str] return contract must stay unchanged"
    assert len(events) == 1
    event = events[0]
    assert event.job_id == job_id
    assert event.agent_id == agent_id
    assert event.old_status == "working", "must be the PRE-overwrite status, not 'decommissioned'"
    assert event.new_status == "decommissioned"

    refreshed = (await db_session.execute(select(AgentExecution).where(AgentExecution.job_id == job_id))).scalar_one()
    assert refreshed.status == "decommissioned"


async def test_handle_force_close_returns_events_for_caller_to_broadcast(db_session: AsyncSession) -> None:
    """The tools-layer seam: _handle_force_close must hand the caller events to
    broadcast POST-COMMIT rather than emitting (or dropping) anything itself.
    """
    tenant_key = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant_key)
    job_id, agent_id = await _seed_execution(db_session, tenant_key, project_id, status="blocked")

    closeout_service = ProjectCloseoutService(db_manager=None, tenant_manager=TenantManager())
    blockers = [{"agent_id": agent_id, "job_id": job_id, "issue_type": "still_working"}]

    events = await _handle_force_close(
        session=db_session,
        project_id=project_id,
        tenant_key=tenant_key,
        force=True,
        blockers=blockers,
        closeout_service=closeout_service,
    )

    assert len(events) == 1
    assert events[0].job_id == job_id
    assert events[0].old_status == "blocked"
    assert events[0].new_status == "decommissioned"


async def test_handle_force_close_returns_empty_when_not_forced(db_session: AsyncSession) -> None:
    """force=False (or no blockers) must return an empty list, never None --
    the caller unconditionally iterates the return value."""
    tenant_key = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant_key)
    closeout_service = ProjectCloseoutService(db_manager=None, tenant_manager=TenantManager())

    events = await _handle_force_close(
        session=db_session,
        project_id=project_id,
        tenant_key=tenant_key,
        force=False,
        blockers=[{"agent_id": "x"}],
        closeout_service=closeout_service,
    )

    assert events == []


# ---------------------------------------------------------------------------
# 6: extracted builder (closeout_ws_broadcast.build_agent_status_change_events)
# ---------------------------------------------------------------------------


async def test_build_agent_status_change_events_captures_pre_transition_status() -> None:
    """The extracted builder records each execution's CURRENT status as old_status
    (BE-9246 contract: build BEFORE the overwrite). Pure, no DB, order-preserving."""
    execs = [
        SimpleNamespace(
            job_id=f"job-{i}",
            agent_id=f"agent-{i}",
            agent_display_name=name,
            agent_name=name,
            status="working",
        )
        for i, name in enumerate(("implementer", "orchestrator"))
    ]

    events = build_agent_status_change_events(execs, "decommissioned")

    assert [e.job_id for e in events] == ["job-0", "job-1"], "one event per execution, order preserved"
    assert all(e.old_status == "working" for e in events), "old_status must be the PRE-overwrite status"
    assert all(e.new_status == "decommissioned" for e in events)
    assert events[0].agent_display_name == "implementer"


# ---------------------------------------------------------------------------
# 5: close_project_and_update_memory(force=True) end-to-end, real commit
# ---------------------------------------------------------------------------


async def test_force_close_broadcasts_status_changed_post_commit(db_manager) -> None:
    """The real MCP-tool call shape: session=None, so this call OWNS its
    session and genuinely commits before returning -- the exact case the
    design contract requires the broadcast be gated on.
    """
    tenant_key = TenantManager.generate_tenant_key()
    # close_project_and_update_memory, when it owns its session (session=None,
    # the real MCP-tool shape), opens it via db_manager.get_session_async()
    # WITHOUT a tenant_key kwarg -- the tenant guard then falls back to the
    # TenantManager contextvar, which the real MCP boundary sets upstream of
    # this call. Mirror that here.
    TenantManager.set_current_tenant(tenant_key)
    try:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product = Product(
                id=str(uuid.uuid4()),
                name=f"BE-9246 Product {uuid.uuid4().hex[:8]}",
                description="BE-9246 force-close regression.",
                tenant_key=tenant_key,
                is_active=False,
            )
            session.add(product)
            await session.flush()

            project_id = await _seed_project(session, tenant_key, product_id=product.id)
            job_id, _agent_id = await _seed_execution(session, tenant_key, project_id, status="working")
            await session.commit()

        mock_ws = _mock_ws()
        result = await close_project_and_update_memory(
            project_id=project_id,
            summary="BE-9246 force-close regression",
            key_outcomes=["Proved the post-commit broadcast fires"],
            decisions_made=["Gate the emit on owns_session"],
            tenant_key=tenant_key,
            db_manager=db_manager,
            force=True,
            websocket_manager=mock_ws,
        )

        assert result.get("error") is None, f"closeout must succeed, got: {result}"

        events = _status_changed_events(mock_ws)
        assert len(events) == 1, "exactly one agent:status_changed for the force-decommissioned agent"
        event = events[0]
        assert event["job_id"] == job_id
        assert event["old_status"] == "working"
        assert event["status"] == "decommissioned"
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
        TenantManager.clear_current_tenant()
