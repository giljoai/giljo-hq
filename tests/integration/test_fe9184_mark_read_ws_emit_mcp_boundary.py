# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary tests for FE-9184 — mark_read drain pushes a live
``thread_update(update_type="read")`` WS event.

An agent's ``get_thread_history(mark_read=True)`` drain writes
``message_acknowledgments`` rows, which decrement the /jobs "Messages Waiting"
badge — but until FE-9184 nothing told the dashboard, so a drained badge stayed
stale through quiet periods. The emit lives at the FastMCP ``@mcp.tool`` wrapper
(``api/endpoints/mcp_tools/_comm_tools.py``), the same boundary the other three
hub WS emits use, so per the regression-at-the-failing-layer rule these tests
exercise the ACTUAL transport (``create_connected_server_and_client_session``).

Behaviors under test (over the wire):
- a drain that acks >= 1 message emits exactly one thread_update with
  update_type="read" carrying thread_id/chat_id/status to the right tenant.
- a plain read (no mark_read) emits nothing.
- a drain that acks nothing (marked_read == 0) emits nothing.
- the NOT_A_PARTICIPANT domain rejection emits nothing.
- the emit is best-effort: a WS manager that raises never fails the drain.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


class _RecordingWsManager:
    """Captures broadcast_event_to_tenant calls for assertion."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def broadcast_event_to_tenant(self, tenant_key, event):
        self.events.append((tenant_key, event))


class _ExplodingWsManager:
    """Raises on every broadcast — proves the emit is best-effort."""

    async def broadcast_event_to_tenant(self, tenant_key, event):
        raise RuntimeError("ws send failed")


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        return res.structured_content
    block = res.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


def _read_events(ws) -> list[tuple[str, dict]]:
    """Only the thread_update/update_type=read events (create/post also broadcast)."""
    return [
        (tk, e)
        for tk, e in ws.events
        if e.get("type") == "thread_update" and e.get("data", {}).get("update_type") == "read"
    ]


@pytest_asyncio.fixture
async def comm_mcp_client_ws(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_key, ws_recorder)`` for FastMCP transport tests.

    Same shape as test_be9012a's comm_mcp_client, plus a recording WS manager on
    app state so the wrapper's best-effort broadcasts become observable.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager
    prior_ws_manager = state.websocket_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    ws_recorder = _RecordingWsManager()
    state.websocket_manager = ws_recorder

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]

    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    user = User(id=str(uuid4()), tenant_key=tenant_key, username=f"patrik_{suffix}")
    db_session.add(user)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, ws_recorder
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager
        state.websocket_manager = prior_ws_manager


async def _setup_thread_with_beta(new_client):
    """A thread whose creator is alpha, with beta joined and 2 posts. Returns (thread_id, chat_id)."""
    async with new_client() as s:
        res = await s.call_tool("create_thread", {"subject": "badge drain", "creator_id": "alpha"})
    assert res.is_error is False, _error_text(res)
    thread = _payload(res)
    tid = thread["thread_id"]
    async with new_client() as s:
        join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "beta"})
        assert join.is_error is False, _error_text(join)
    for content in ("one", "two"):
        async with new_client() as s:
            post = await s.call_tool("post_to_thread", {"thread_id": tid, "content": content, "from_agent": "alpha"})
            assert post.is_error is False, _error_text(post)
    return tid, thread.get("chat_id")


async def test_mark_read_drain_emits_thread_update_read(comm_mcp_client_ws):
    """A drain that acks messages pushes exactly one thread_update/read to the tenant."""
    new_client, tenant_key, ws = comm_mcp_client_ws
    tid, chat_id = await _setup_thread_with_beta(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "mark_read": True},
        )
    assert res.is_error is False, _error_text(res)
    assert _payload(res)["marked_read"] == 2

    read_events = _read_events(ws)
    assert len(read_events) == 1
    event_tenant, event = read_events[0]
    assert event_tenant == tenant_key
    assert event["data"]["thread_id"] == tid
    assert event["data"]["chat_id"] == chat_id
    assert event["data"]["status"] == "open"


async def test_plain_read_emits_nothing(comm_mcp_client_ws):
    """No mark_read => no read event (mark_read=False explicit and absent alike)."""
    new_client, _tk, ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread_with_beta(new_client)

    async with new_client() as s:
        res = await s.call_tool("get_thread_history", {"thread_id": tid})
        assert res.is_error is False, _error_text(res)
    async with new_client() as s:
        res = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "mark_read": False},
        )
        assert res.is_error is False, _error_text(res)

    assert _read_events(ws) == []


async def test_drain_with_nothing_to_ack_emits_nothing(comm_mcp_client_ws):
    """marked_read == 0 (already-drained unread cursor) => badge unchanged => no event."""
    new_client, _tk, ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread_with_beta(new_client)

    # First drain acks both posts and emits once.
    async with new_client() as s:
        first = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "unread_only": True, "mark_read": True},
        )
        assert first.is_error is False, _error_text(first)
    assert _payload(first)["marked_read"] == 2
    assert len(_read_events(ws)) == 1

    # Second drain: nothing unread, marked_read == 0 => NO second event.
    async with new_client() as s:
        second = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "unread_only": True, "mark_read": True},
        )
        assert second.is_error is False, _error_text(second)
    assert _payload(second)["marked_read"] == 0
    assert len(_read_events(ws)) == 1


async def test_not_a_participant_rejection_emits_nothing(comm_mcp_client_ws):
    """The structured NOT_A_PARTICIPANT rejection never emits (no acks written)."""
    new_client, _tk, ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread_with_beta(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "ghost", "mark_read": True},
        )
    assert res.is_error is False, _error_text(res)
    assert _payload(res)["success"] is False

    assert _read_events(ws) == []


async def test_emit_is_best_effort_never_fails_the_drain(comm_mcp_client_ws):
    """A WS manager that raises must not surface: the drain still succeeds and acks."""
    new_client, _tk, _ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread_with_beta(new_client)

    from api import app_state

    app_state.state.websocket_manager = _ExplodingWsManager()
    try:
        async with new_client() as s:
            res = await s.call_tool(
                "get_thread_history",
                {"thread_id": tid, "as_participant": "beta", "mark_read": True},
            )
        assert res.is_error is False, _error_text(res)
        assert _payload(res)["marked_read"] == 2
    finally:
        app_state.state.websocket_manager = _ws
