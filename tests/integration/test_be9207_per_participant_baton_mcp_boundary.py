# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary tests for BE-9207 — per-participant baton visibility.

The single ``next_action_owner`` baton is SINGLE-owner, so on a multi-lane thread
consecutive directed ``requires_action`` posts to DIFFERENT lanes clobber each
other: lane A's open directive vanishes from ``get_my_turn`` the moment the EM
directs lane B, and a worker sleep-polling ``get_my_turn`` idles past its own open
action-request (live incident 2026-07-16/17; this very operation thread briefly
showed the failure mode). ``get_my_turn`` now ALSO surfaces threads where the
caller has an UNRESOLVED directed ``requires_action`` post, independent of the
baton — reusing the message_recipients + message_acknowledgments junctions (NO
schema change). These tests exercise the ACTUAL transport
(``create_connected_server_and_client_session``), per CLAUDE.md's "regression at
the failing layer" — the failing surface is the ``@mcp.tool`` get_my_turn wrapper.

Behaviors under test (over the wire):
- the clobber repro: direct A, then direct B; get_my_turn(A) STILL lists the
  thread though next_action_owner has moved to B (the core DoD);
- both addressees see their own directed thread + it is named in directed_action;
- resolve = ack: mark_read clears A's pending directive (B's stays);
- a plain / after_message_id delta-read does NOT ack — the directive stays pending
  (condition 3: only an explicit mark_read clears it);
- participation is required: a DM aimed at B never leaks into A's turn list
  (condition 1: message_recipients row implied);
- a terminal thread status silences the pending directive;
- the legacy shape is intact: directed_action is additive; the baton path is
  unchanged when no directed requires_action post exists.
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


@pytest_asyncio.fixture
async def comm_mcp_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_key)`` for FastMCP transport tests.

    Mirrors the BE-6054b/BE-9197 house pattern: the ToolAccessor receives the
    rolled-back ``test_session``; the CHT taxonomy type is seeded so thread minting
    does not 422; a user + org back the tenant.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

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
        yield _new_client, tenant_key
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _setup_thread(new_client):
    """A thread created by the EM (holds the baton), with lanes A and B joined."""
    async with new_client() as s:
        res = await s.call_tool("create_thread", {"subject": "multi-lane op", "creator_id": "EM"})
    assert res.is_error is False, _error_text(res)
    thread = _payload(res)
    tid = thread["thread_id"]
    for agent in ("lane-A", "lane-B"):
        async with new_client() as s:
            join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": agent})
            assert join.is_error is False, _error_text(join)
    return tid, thread["chat_id"]


async def _direct_action_request(new_client, tid, to_participant):
    """EM posts a directed requires_action message (auto-passes the baton to it)."""
    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": f"please handle this, {to_participant}",
                "from_agent": "EM",
                "to_participant": to_participant,
                "requires_action": True,
            },
        )
    assert res.is_error is False, _error_text(res)
    return _payload(res)


async def _get_my_turn(new_client, agent_id):
    async with new_client() as s:
        res = await s.call_tool("get_my_turn", {"agent_id": agent_id})
    assert res.is_error is False, _error_text(res)
    return _payload(res)


def _sees_thread(turn, tid) -> bool:
    return any(t["thread_id"] == tid for t in turn["threads"])


def _directed_ids(turn) -> set[str]:
    return {d["thread_id"] for d in turn["directed_action"]}


async def test_directed_action_survives_baton_move_to_another_lane(comm_mcp_client):
    """THE clobber repro (core DoD): direct A, then direct B. Even though the
    thread-level baton has moved to B, get_my_turn(A) STILL surfaces A's thread
    (both in threads and in directed_action)."""
    new_client, _tk = comm_mcp_client
    tid, chat_id = await _setup_thread(new_client)

    a_post = await _direct_action_request(new_client, tid, "lane-A")
    assert a_post["next_action_owner"] == "lane-A"  # auto-passed to A

    b_post = await _direct_action_request(new_client, tid, "lane-B")
    assert b_post["next_action_owner"] == "lane-B"  # baton clobbers over to B

    # Pre-BE-9207 this was the bug: A's open directive is now invisible because the
    # single next_action_owner moved to B. Post-fix A still sees its turn.
    a_turn = await _get_my_turn(new_client, "lane-A")
    assert _sees_thread(a_turn, tid), "lane-A lost its directed action when the baton moved to lane-B"
    assert tid in _directed_ids(a_turn)
    assert a_turn["directed_action"][0]["chat_id"] == chat_id

    # B, the current baton holder, also sees it (via the baton AND the directive).
    b_turn = await _get_my_turn(new_client, "lane-B")
    assert _sees_thread(b_turn, tid)
    assert tid in _directed_ids(b_turn)


async def test_mark_read_resolves_the_pending_directive(comm_mcp_client):
    """Resolve = ack. After lane-A mark_reads the thread, its pending directive
    clears from get_my_turn; lane-B's independent directive stays pending."""
    new_client, _tk = comm_mcp_client
    tid, _chat = await _setup_thread(new_client)
    await _direct_action_request(new_client, tid, "lane-A")
    await _direct_action_request(new_client, tid, "lane-B")

    assert tid in _directed_ids(await _get_my_turn(new_client, "lane-A"))

    # lane-A reads + acknowledges the thread (the durable resolve signal).
    async with new_client() as s:
        read = await s.call_tool(
            "get_thread_history", {"thread_id": tid, "as_participant": "lane-A", "mark_read": True}
        )
    assert read.is_error is False, _error_text(read)
    assert _payload(read).get("marked_read", 0) > 0

    a_turn = await _get_my_turn(new_client, "lane-A")
    assert tid not in _directed_ids(a_turn)
    assert not _sees_thread(a_turn, tid), "lane-A's directive should clear once acknowledged"

    # lane-B never acked — still pending (per-participant resolution, not thread-wide).
    assert tid in _directed_ids(await _get_my_turn(new_client, "lane-B"))


async def test_delta_read_without_mark_read_does_not_resolve(comm_mcp_client):
    """Condition 3: a plain / after_message_id delta-read does NOT acknowledge — only
    an explicit mark_read clears the pending directive (safe-side behavior)."""
    new_client, _tk = comm_mcp_client
    tid, _chat = await _setup_thread(new_client)
    a_post = await _direct_action_request(new_client, tid, "lane-A")

    # A plain read, and an incremental after_message_id read — neither may ack.
    async with new_client() as s:
        plain = await s.call_tool("get_thread_history", {"thread_id": tid})
        assert plain.is_error is False, _error_text(plain)
        delta = await s.call_tool("get_thread_history", {"thread_id": tid, "after_message_id": a_post["message_id"]})
        assert delta.is_error is False, _error_text(delta)

    # Still pending — the directive only resolves on an explicit mark_read.
    assert tid in _directed_ids(await _get_my_turn(new_client, "lane-A"))


async def test_dm_to_another_lane_does_not_leak(comm_mcp_client):
    """Condition 1: participation is implied by a message_recipients row — a directed
    action-request aimed at lane-B never appears in lane-A's turn list."""
    new_client, _tk = comm_mcp_client
    tid, _chat = await _setup_thread(new_client)
    await _direct_action_request(new_client, tid, "lane-B")

    a_turn = await _get_my_turn(new_client, "lane-A")
    assert tid not in _directed_ids(a_turn)
    assert not _sees_thread(a_turn, tid), "a DM to lane-B must not surface on lane-A's get_my_turn"


async def test_terminal_status_silences_pending_directive(comm_mcp_client):
    """A resolved/closed thread silences the pending directive — the same gate that
    terminates a loop directive."""
    new_client, _tk = comm_mcp_client
    tid, _chat = await _setup_thread(new_client)
    await _direct_action_request(new_client, tid, "lane-A")
    assert tid in _directed_ids(await _get_my_turn(new_client, "lane-A"))

    async with new_client() as s:
        close = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "wrapping up", "from_agent": "EM", "set_status": "resolved"},
        )
    assert close.is_error is False, _error_text(close)

    a_turn = await _get_my_turn(new_client, "lane-A")
    assert tid not in _directed_ids(a_turn)


async def test_legacy_baton_shape_unchanged_without_directed_action(comm_mcp_client):
    """DoD-2: with no directed requires_action post, get_my_turn is byte-equivalent
    to the legacy baton behavior — directed_action is empty and the thread is
    surfaced purely by the baton; after a plain pass_baton it leaves the holder."""
    new_client, _tk = comm_mcp_client
    tid, _chat = await _setup_thread(new_client)  # EM holds the baton

    em_turn = await _get_my_turn(new_client, "EM")
    assert _sees_thread(em_turn, tid)
    assert em_turn["directed_action"] == []

    async with new_client() as s:
        handoff = await s.call_tool("pass_baton", {"thread_id": tid, "to": "lane-A"})
        assert handoff.is_error is False, _error_text(handoff)

    # Baton moved: EM no longer sees it (no directed post keeps it alive), A does.
    em_after = await _get_my_turn(new_client, "EM")
    assert not _sees_thread(em_after, tid)
    assert em_after["directed_action"] == []
    assert _sees_thread(await _get_my_turn(new_client, "lane-A"), tid)


async def test_broadcast_action_request_does_not_obligate_a_lane(comm_mcp_client):
    """Scope guard (preserves the BE-9197 museum rule): a BROADCAST requires_action
    post is "whoever picks it up" — it does NOT move the baton and must NOT land on
    any specific participant's directed_action. Only a DM (to_participant) is the
    per-lane directive this fix restores."""
    new_client, _tk = comm_mcp_client
    tid, _chat = await _setup_thread(new_client)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": "ACTION for whoever picks it up",
                "from_agent": "EM",
                "requires_action": True,
            },
        )
    assert res.is_error is False, _error_text(res)
    assert _payload(res)["baton_passed"] is False  # broadcast leaves the baton put

    for lane in ("lane-A", "lane-B"):
        turn = await _get_my_turn(new_client, lane)
        assert tid not in _directed_ids(turn), f"broadcast requires_action leaked onto {lane}'s directed_action"
        assert not _sees_thread(turn, tid)
