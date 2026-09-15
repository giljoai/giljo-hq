# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    events: list[dict[str, Any]] = []
    for call in mock_ws.broadcast_to_tenant.await_args_list:
        kwargs = call.kwargs
        if kwargs.get("event_type") == "agent:status_changed":
            events.append(kwargs.get("data") or {})
    return events


async def _seed_project(session: AsyncSession, tenant_key: str, *, product_id: str | None = None) -> str:
    if product_id is None:
        product = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=f"BE-9246 product {uuid.uuid4().hex[:8]}",
            description="Owning product for the BE-9246 project seed.",
            is_active=False,
        )
        session.add(product)
        await session.flush()
        product_id = product.id

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




async def test_close_completed_agents_with_commit_broadcasts_post_commit(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9518 product {uuid.uuid4().hex[:8]}",
        description="Owning product for the BE-9518 product_id assertion.",
        is_active=False,
    )
    db_session.add(product)
    await db_session.flush()
    project_id = await _seed_project(db_session, tenant_key, product_id=product.id)
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
    assert event["product_id"] == product.id


async def test_close_completed_agents_with_commit_never_emits_before_commit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
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




async def test_build_agent_status_change_events_captures_pre_transition_status() -> None:
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




async def test_force_close_broadcasts_status_changed_post_commit(db_manager) -> None:
    tenant_key = TenantManager.generate_tenant_key()
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
