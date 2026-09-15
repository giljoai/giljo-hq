# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.services.message_routing_service import MessageRoutingService


def _build_service(order: list[str], ws_manager) -> MessageRoutingService:
    svc = MessageRoutingService(db_manager=Mock(), tenant_manager=Mock(), websocket_manager=ws_manager)

    completed = Mock()
    completed.status = "complete"
    completed.job_id = "job-1"
    completed.agent_display_name = "agent-x"

    repo = Mock()
    repo.get_execution_by_agent_id = AsyncMock(return_value=completed)

    async def _flush(_session):
        order.append("flush")

    repo.flush = AsyncMock(side_effect=_flush)
    job_row = Mock()
    job_row.project_id = "proj-1"
    job_row.product_id = "prod-1"
    repo.get_job_id_and_project_for_execution = AsyncMock(return_value=job_row)
    svc._repo = repo
    return svc


def _build_session(order: list[str]) -> Mock:
    session = Mock()

    async def _commit():
        order.append("commit")

    session.commit = AsyncMock(side_effect=_commit)
    return session


def _build_project():
    project = Mock()
    project.tenant_key = "tk_a"
    project.status = "active"
    return project


@pytest.mark.asyncio
async def test_auto_block_broadcast_is_scheduled_after_commit():
    order: list[str] = []

    ws = Mock()
    ws.broadcast_job_status_update = AsyncMock()

    def _schedule(coro):
        order.append("broadcast")
        coro.close()

    ws.schedule = _schedule

    svc = _build_service(order, ws)
    session = _build_session(order)

    blocked = await svc._auto_block_completed_recipients(
        session=session,
        resolved_to_agents=["agent-x"],
        project=_build_project(),
        sender_display_name="orchestrator",
        is_broadcast_fanout=False,
        requires_action=True,
    )

    assert blocked == ["agent-x"]
    assert "commit" in order
    assert "broadcast" in order
    assert order.index("commit") < order.index("broadcast"), order
    ws.broadcast_job_status_update.assert_called_once()
    kwargs = ws.broadcast_job_status_update.call_args.kwargs
    assert kwargs["new_status"] == "blocked"
    assert kwargs["old_status"] == "complete"
    assert kwargs["project_id"] == "proj-1"
    assert kwargs["tenant_key"] == "tk_a"
    assert kwargs["product_id"] == "prod-1"


@pytest.mark.asyncio
async def test_auto_block_falls_back_to_inline_await_without_schedule():
    order: list[str] = []

    ws = Mock(spec=["broadcast_job_status_update"])

    async def _broadcast(**_kwargs):
        order.append("broadcast")

    ws.broadcast_job_status_update = AsyncMock(side_effect=_broadcast)

    svc = _build_service(order, ws)
    session = _build_session(order)

    await svc._auto_block_completed_recipients(
        session=session,
        resolved_to_agents=["agent-x"],
        project=_build_project(),
        sender_display_name="orchestrator",
        is_broadcast_fanout=False,
        requires_action=True,
    )

    assert order.index("commit") < order.index("broadcast"), order


@pytest.mark.asyncio
async def test_no_broadcast_when_no_recipient_auto_blocked():
    order: list[str] = []
    ws = Mock()
    ws.schedule = Mock()
    ws.broadcast_job_status_update = AsyncMock()

    svc = _build_service(order, ws)
    working = Mock()
    working.status = "working"
    svc._repo.get_execution_by_agent_id = AsyncMock(return_value=working)
    session = _build_session(order)

    blocked = await svc._auto_block_completed_recipients(
        session=session,
        resolved_to_agents=["agent-x"],
        project=_build_project(),
        sender_display_name="orchestrator",
        is_broadcast_fanout=False,
        requires_action=True,
    )

    assert blocked == []
    assert order == []
    ws.schedule.assert_not_called()
    ws.broadcast_job_status_update.assert_not_called()
