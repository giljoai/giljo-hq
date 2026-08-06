# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary tests for BE-9197 — atomic post-with-baton.

Agents repeatedly post a question but forget the separate ``pass_baton`` call,
leaving the addressee's ``get_my_turn`` blind (live incident 2026-07-16: two
workers idled 60+/25+ minutes past their ACCEPTED broadcasts because
``next_action_owner`` never moved). ``post_to_thread`` now takes an optional
``pass_baton_to`` and auto-passes on a directed action-request, so the hand-off
happens in the same call — these tests exercise the ACTUAL transport
(``create_connected_server_and_client_session``), the same harness as FE-9184.

Behaviors under test (over the wire):
- explicit ``pass_baton_to`` moves the baton (and 'all' opens the turn to anyone);
- the auto-pass default fires EXACTLY on requires_action=true + to_participant;
- an explicit ``pass_baton_to`` beats the auto-pass default;
- ``pass_baton_to='none'`` posts WITHOUT moving the baton (suppresses the default);
- a broadcast without the param keeps today's behavior (baton untouched);
- the atomic path emits a thread_update byte-identical to pass_baton's emission;
- the emit is best-effort: a WS manager that raises never fails the post.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import delete

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


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
        return res.structuredContent
    block = res.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


def _baton_events(ws) -> list[tuple[str, dict]]:
    """Only the thread_update/update_type=baton events (create/post also broadcast)."""
    return [
        (tk, e)
        for tk, e in ws.events
        if e.get("type") == "thread_update" and e.get("data", {}).get("update_type") == "baton"
    ]


@pytest_asyncio.fixture
async def comm_mcp_client_ws(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_key, ws_recorder)`` for FastMCP transport tests.

    Same shape as test_fe9184's comm_mcp_client_ws (the house pattern for hub
    WS-emission boundary tests): recording WS manager on app state so the
    wrapper's best-effort broadcasts become observable.
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


async def _setup_thread(new_client):
    """A thread created by alpha (alpha holds the baton), with beta and gamma joined."""
    async with new_client() as s:
        res = await s.call_tool("create_thread", {"subject": "baton ergonomics", "creator_id": "alpha"})
    assert res.isError is False, _error_text(res)
    thread = _payload(res)
    tid = thread["thread_id"]
    for agent in ("beta", "gamma"):
        async with new_client() as s:
            join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": agent})
            assert join.isError is False, _error_text(join)
    return tid, thread.get("chat_id")


async def _owner_sees_turn(new_client, agent_id: str, thread_id: str) -> bool:
    """The incident surface: does get_my_turn(agent_id) list this thread?"""
    async with new_client() as s:
        res = await s.call_tool("get_my_turn", {"agent_id": agent_id})
    assert res.isError is False, _error_text(res)
    return any(t["thread_id"] == thread_id for t in _payload(res)["threads"])


async def test_explicit_pass_baton_to_respected(comm_mcp_client_ws):
    """A broadcast post with pass_baton_to moves the baton and emits one baton event."""
    new_client, tenant_key, ws = comm_mcp_client_ws
    tid, chat_id = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "over to you", "from_agent": "alpha", "pass_baton_to": "gamma"},
        )
    assert res.isError is False, _error_text(res)
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
    """The incident fix shape: an ACCEPTED-style broadcast with pass_baton_to='all'
    lands on EVERY participant's get_my_turn."""
    new_client, _tk, _ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "ACCEPTED", "from_agent": "alpha", "pass_baton_to": "all"},
        )
    assert res.isError is False, _error_text(res)
    assert _payload(res)["next_action_owner"] == "all"
    # 'all' threads surface for any polling agent, even one never addressed.
    assert await _owner_sees_turn(new_client, "beta", tid)
    assert await _owner_sees_turn(new_client, "gamma", tid)


async def test_auto_pass_on_directed_action_request(comm_mcp_client_ws):
    """requires_action=true + to_participant, no param => baton auto-passes to that participant."""
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
    assert res.isError is False, _error_text(res)
    payload = _payload(res)
    assert payload["baton_passed"] is True
    assert payload["next_action_owner"] == "beta"
    assert await _owner_sees_turn(new_client, "beta", tid)
    assert len(_baton_events(ws)) == 1


async def test_explicit_param_beats_auto_rule(comm_mcp_client_ws):
    """An explicit pass_baton_to wins over the directed-action-request default."""
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
    assert res.isError is False, _error_text(res)
    assert _payload(res)["next_action_owner"] == "gamma"
    assert await _owner_sees_turn(new_client, "gamma", tid)
    # BE-9207: get_my_turn is no longer a pure baton proxy. beta received a directed
    # requires_action post, so beta's own get_my_turn now surfaces this thread (via the
    # additive directed_action list) even though the baton went to gamma — that
    # decoupling IS the BE-9207 fix (a directed action must not vanish from its
    # addressee's turn list when the baton moves to another lane). The baton-placement
    # contract this test guards is asserted above (next_action_owner == gamma); the old
    # `assert not _owner_sees_turn(beta)` conflated get_my_turn visibility with baton
    # ownership and is intentionally replaced.
    assert await _owner_sees_turn(new_client, "beta", tid)


async def test_explicit_none_suppresses_auto_pass(comm_mcp_client_ws):
    """pass_baton_to='none' posts a directed action-request WITHOUT moving the baton."""
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
    assert res.isError is False, _error_text(res)
    payload = _payload(res)
    assert payload["baton_passed"] is False
    # Creator alpha still holds the baton (pass_baton_to='none' suppressed the auto-pass).
    assert payload["next_action_owner"] == "alpha"
    # BE-9207: beta received a directed requires_action post, so beta's get_my_turn now
    # surfaces this thread via the additive directed_action list even though the baton
    # never moved off alpha. The old `assert not _owner_sees_turn(beta)` used get_my_turn
    # as a baton proxy; BE-9207 decouples the two (a directed action stays visible to its
    # addressee regardless of baton position). The baton-suppression contract this test
    # guards is asserted above (baton_passed False, next_action_owner == alpha, no baton event).
    assert await _owner_sees_turn(new_client, "beta", tid)
    assert _baton_events(ws) == []


async def test_broadcast_without_param_unchanged(comm_mcp_client_ws):
    """Museum guard: broadcasts without pass_baton_to keep today's behavior exactly —
    baton untouched, no baton event — even with requires_action=true."""
    new_client, _tk, ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "plain broadcast", "from_agent": "alpha"},
        )
        assert res.isError is False, _error_text(res)
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
        assert res.isError is False, _error_text(res)

    payload = _payload(res)
    assert payload["baton_passed"] is False
    assert payload["next_action_owner"] == "alpha"  # creator still holds it
    assert not await _owner_sees_turn(new_client, "beta", tid)
    assert _baton_events(ws) == []


async def test_emission_parity_with_pass_baton(comm_mcp_client_ws):
    """The atomic path's thread_update must be byte-identical to pass_baton's:
    same thread, same target => the two event payloads compare equal. Also
    asserts ORDER: the atomic path emits the message event first, then the
    baton update — mirroring the post-then-pass two-call sequence."""
    new_client, tenant_key, ws = comm_mcp_client_ws
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "handing off", "from_agent": "alpha", "pass_baton_to": "beta"},
        )
        assert res.isError is False, _error_text(res)
    async with new_client() as s:
        res = await s.call_tool("pass_baton", {"thread_id": tid, "to": "beta"})
        assert res.isError is False, _error_text(res)

    baton_events = _baton_events(ws)
    assert len(baton_events) == 2
    (tenant_a, event_a), (tenant_b, event_b) = baton_events
    assert tenant_a == tenant_b == tenant_key
    assert event_a == event_b  # full event equality: type + every data field

    # ORDER: the atomic post's thread_message precedes its baton thread_update.
    flat = [e for _t, e in ws.events]
    msg_idx = next(
        i for i, e in enumerate(flat) if e["type"] == "thread_message" and e["data"]["content"] == "handing off"
    )
    baton_idx = next(
        i for i, e in enumerate(flat) if e["type"] == "thread_update" and e["data"]["update_type"] == "baton"
    )
    assert msg_idx < baton_idx


async def test_emit_is_best_effort_never_fails_the_post(comm_mcp_client_ws):
    """A WS manager that raises must not surface: the post succeeds AND the baton moved."""
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
        assert res.isError is False, _error_text(res)
        assert _payload(res)["baton_passed"] is True
    finally:
        app_state.state.websocket_manager = _ws
    # The baton write is authoritative despite the WS failure.
    assert await _owner_sees_turn(new_client, "beta", tid)
