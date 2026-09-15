# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def broadcast_event_to_tenant(self, tenant_key, event):
        self.events.append((tenant_key, event))


class _ExplodingWsManager:

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


def _baton_events(ws) -> list[tuple[str, dict]]:
    return [
        (tk, e)
        for tk, e in ws.events
        if e.get("type") == "thread_update" and e.get("data", {}).get("update_type") == "baton"
    ]


@pytest_asyncio.fixture
async def comm_mcp_client_ws(db_manager, db_session, monkeypatch):
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


async def _setup_thread(new_client):
    async with new_client() as s:
        res = await s.call_tool("create_thread", {"subject": "baton ergonomics", "creator_id": "alpha"})
    assert res.is_error is False, _error_text(res)
    thread = _payload(res)
    tid = thread["thread_id"]
    for agent in ("beta", "gamma"):
        async with new_client() as s:
            join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": agent})
            assert join.is_error is False, _error_text(join)
    return tid, thread.get("chat_id")


async def _owner_sees_turn(new_client, agent_id: str, thread_id: str) -> bool:
    async with new_client() as s:
        res = await s.call_tool("get_my_turn", {"agent_id": agent_id})
    assert res.is_error is False, _error_text(res)
    return any(t["thread_id"] == thread_id for t in _payload(res)["threads"])


async def test_explicit_pass_baton_to_respected(comm_mcp_client_ws):
    new_client, tenant_key, ws = comm_mcp_client_ws
    tid, chat_id = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "over to you", "from_agent": "alpha", "pass_baton_to": "gamma"},
        )
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)
    assert payload["baton_passed"] is True
    assert payload["next_action_owner"] == "gamma"
    assert await _owner_sees_turn(new_client, "gamma", tid)

    baton_events = _baton_events(ws)
    assert len(baton_events) == 1
    event_tenant, event = baton_events[0]
    assert event_tenant == tenant_key
    assert event["data"]["thread_id"] == tid
    assert event["data"]["chat_id"] == chat_id
    assert event["data"]["status"] == "open"
    assert event["data"]["next_action_owner"] == "gamma"


async def test_pass_baton_to_all_opens_turn_to_anyone(comm_mcp_client_ws):
    new_client, _tk, _ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "ACCEPTED", "from_agent": "alpha", "pass_baton_to": "all"},
        )
    assert res.is_error is False, _error_text(res)
    assert _payload(res)["next_action_owner"] == "all"
    assert await _owner_sees_turn(new_client, "beta", tid)
    assert await _owner_sees_turn(new_client, "gamma", tid)


async def test_auto_pass_on_directed_action_request(comm_mcp_client_ws):
    new_client, _tk, ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": "QUESTION: which approach?",
                "from_agent": "alpha",
                "to_participant": "beta",
                "requires_action": True,
            },
        )
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)
    assert payload["baton_passed"] is True
    assert payload["next_action_owner"] == "beta"
    assert await _owner_sees_turn(new_client, "beta", tid)
    assert len(_baton_events(ws)) == 1


async def test_explicit_param_beats_auto_rule(comm_mcp_client_ws):
    new_client, _tk, _ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": "beta please review, gamma decides",
                "from_agent": "alpha",
                "to_participant": "beta",
                "requires_action": True,
                "pass_baton_to": "gamma",
            },
        )
    assert res.is_error is False, _error_text(res)
    assert _payload(res)["next_action_owner"] == "gamma"
    assert await _owner_sees_turn(new_client, "gamma", tid)
    assert await _owner_sees_turn(new_client, "beta", tid)


async def test_explicit_none_suppresses_auto_pass(comm_mcp_client_ws):
    new_client, _tk, ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": "FYI action later, keeping the baton",
                "from_agent": "alpha",
                "to_participant": "beta",
                "requires_action": True,
                "pass_baton_to": "none",
            },
        )
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)
    assert payload["baton_passed"] is False
    assert payload["next_action_owner"] == "alpha"
    assert await _owner_sees_turn(new_client, "beta", tid)
    assert _baton_events(ws) == []


async def test_broadcast_without_param_unchanged(comm_mcp_client_ws):
    new_client, _tk, ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "plain broadcast", "from_agent": "alpha"},
        )
        assert res.is_error is False, _error_text(res)
    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": "ACTION for whoever picks it up",
                "from_agent": "alpha",
                "requires_action": True,
            },
        )
        assert res.is_error is False, _error_text(res)

    payload = _payload(res)
    assert payload["baton_passed"] is False
    assert payload["next_action_owner"] == "alpha"
    assert not await _owner_sees_turn(new_client, "beta", tid)
    assert _baton_events(ws) == []


async def test_emission_parity_with_pass_baton(comm_mcp_client_ws):
    new_client, tenant_key, ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "handing off", "from_agent": "alpha", "pass_baton_to": "beta"},
        )
        assert res.is_error is False, _error_text(res)
    async with new_client() as s:
        res = await s.call_tool("set_next_actor", {"thread_id": tid, "to": "beta", "from_agent": "alpha"})
        assert res.is_error is False, _error_text(res)

    baton_events = _baton_events(ws)
    assert len(baton_events) == 2
    (tenant_a, event_a), (tenant_b, event_b) = baton_events
    assert tenant_a == tenant_b == tenant_key
    assert event_a == event_b
    assert event_a["data"]["from_display_name"]
    assert event_a["data"]["from_kind"] == "agent"

    flat = [e for _t, e in ws.events]
    msg_idx = next(
        i for i, e in enumerate(flat) if e["type"] == "thread_message" and e["data"]["content"] == "handing off"
    )
    baton_idx = next(
        i for i, e in enumerate(flat) if e["type"] == "thread_update" and e["data"]["update_type"] == "baton"
    )
    assert msg_idx < baton_idx


async def test_emit_is_best_effort_never_fails_the_post(comm_mcp_client_ws):
    new_client, _tk, _ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    from api import app_state

    app_state.state.websocket_manager = _ExplodingWsManager()
    try:
        async with new_client() as s:
            res = await s.call_tool(
                "post_to_thread",
                {"thread_id": tid, "content": "over to you", "from_agent": "alpha", "pass_baton_to": "beta"},
            )
        assert res.is_error is False, _error_text(res)
        assert _payload(res)["baton_passed"] is True
    finally:
        app_state.state.websocket_manager = _ws
    assert await _owner_sees_turn(new_client, "beta", tid)
