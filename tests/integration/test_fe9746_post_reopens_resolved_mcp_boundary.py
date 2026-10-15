# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from giljo_mcp.models.comm import CommThread
from tests.integration.test_be9502a_thread_rename_mcp_boundary import (  # noqa: F401 - fixture reuse
    _create_thread,
    _error_text,
    _payload,
    rename_mcp_client,
)


pytestmark = pytest.mark.asyncio


async def _status(session, tid: str) -> str:
    row = (await session.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
    await session.refresh(row)
    return row.status


async def _set(new_client, tid: str, status: str) -> None:
    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": f"marking {status}", "from_agent": "alpha", "set_status": status},
        )
    assert res.is_error is False, _error_text(res)


async def test_post_to_resolved_thread_reopens_it_and_broadcasts(rename_mcp_client):  # noqa: F811
    from api.app_state import state

    new_client, _tenant_key, session = rename_mcp_client
    tid = await _create_thread(new_client, "resolved then answered")
    await _set(new_client, tid, "resolved")
    assert await _status(session, tid) == "resolved"

    mock_ws = AsyncMock()
    original = state.websocket_manager
    state.websocket_manager = mock_ws
    try:
        async with new_client() as s:
            res = await s.call_tool(
                "post_to_thread", {"thread_id": tid, "content": "new information", "from_agent": "alpha"}
            )
    finally:
        state.websocket_manager = original
    assert res.is_error is False, _error_text(res)
    assert _payload(res)["thread_reopened"] is True
    assert await _status(session, tid) == "active"

    events = [(c.args[1] if c.args else c.kwargs["event"]) for c in mock_ws.broadcast_event_to_tenant.call_args_list]
    status_events = [e for e in events if e["type"] == "thread_update" and e["data"].get("update_type") == "status"]
    assert status_events and status_events[0]["data"]["status"] == "active"


async def test_post_to_closed_thread_stays_closed(rename_mcp_client):  # noqa: F811
    new_client, _tenant_key, session = rename_mcp_client
    tid = await _create_thread(new_client, "closed for good")
    await _set(new_client, tid, "closed")

    async with new_client() as s:
        res = await s.call_tool("post_to_thread", {"thread_id": tid, "content": "hello?", "from_agent": "alpha"})
    assert res.is_error is False, _error_text(res)
    assert await _status(session, tid) == "closed"


async def test_explicit_set_status_resolved_wins_over_the_reopen(rename_mcp_client):  # noqa: F811
    new_client, _tenant_key, session = rename_mcp_client
    tid = await _create_thread(new_client, "final message")
    await _set(new_client, tid, "resolved")

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "last word", "from_agent": "alpha", "set_status": "resolved"},
        )
    assert res.is_error is False, _error_text(res)
    assert await _status(session, tid) == "resolved"
