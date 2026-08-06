# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary tests for BE-6054b — Agent Message Hub tool surface.

CLAUDE.md / BE-5042 mandate a regression at the layer the behavior lives. The 8
thread tools live at the FastMCP ``@mcp.tool`` wrapper layer
(``api/endpoints/mcp_tools/_comm_tools.py``) + ``_call_tool`` dispatch. This file
exercises the ACTUAL transport (``create_connected_server_and_client_session``)
so the wrapper + dispatch + scope gate are covered, not just the service.

Behaviors under test (over the wire):
- create_thread mints a CHT-#### chat id + registers the creator (baton holder).
- join_thread + post_to_thread (broadcast) persists a message; get_thread_history
  reads it back WITHOUT acknowledging.
- get_my_turn returns threads where next_action_owner == me; pass_baton hands it on.
- (A) username injection: a USER post stamps the user's display_name as sender.
- post_to_thread does NOT require project_id (standalone thread) and skips the
  orchestration side-effects.
- input validation at the boundary -> clean error (empty content; unknown thread).
- search_threads finds a thread by subject keyword.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import delete, select
from sqlalchemy import update as sa_update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.models.tasks import (
    Message,
    MessageAcknowledgment,
    MessageCompletion,
    MessageRecipient,
)
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structuredContent
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


@pytest_asyncio.fixture
async def comm_mcp_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_key, user_id)`` for FastMCP transport tests.

    CommThreadService receives ``test_session`` from ToolAccessor.__init__, so its
    writes land in the rolled-back transaction (no rebind needed). The CHT
    taxonomy type is seeded for the synthetic tenant so thread minting does not 422.
    A user is seeded for the username-injection test.
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
    # Seed default taxonomy types (incl. CHT) so create_thread minting succeeds.
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
        yield _new_client, tenant_key, user.id, _base, monkeypatch
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _create_thread(client, **kwargs):
    async with client() as s:
        res = await s.call_tool("create_thread", kwargs)
    assert res.isError is False, _error_text(res)
    return _payload(res)


async def test_create_thread_returns_cht_chat_id(comm_mcp_client):
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    payload = await _create_thread(new_client, subject="design sync", creator_id="agent-alpha")
    assert payload["chat_id"].startswith("CHT-")
    assert payload["thread_id"]
    assert payload["status"] == "open"
    # Creator holds the baton.
    assert payload["next_action_owner"] == "agent-alpha"


async def test_create_thread_broadcasts_created_ws_event(comm_mcp_client):
    """Regression: an agent-created thread MUST push a live ``thread_update`` WS
    event (update_type='created') so the Hub auto-shows the new chat — matching
    the user/REST create path (comm_threads.py). Previously the MCP wrapper wrote
    the thread to the DB but emitted no event, so an agent-created chat only
    appeared on a manual reload.
    """
    new_client, tenant_key, _uid, _base, monkeypatch = comm_mcp_client
    from api import app_state

    events: list = []

    class _SpyWsManager:
        async def broadcast_event_to_tenant(self, tk, event):
            events.append((tk, event))

    monkeypatch.setattr(app_state.state, "websocket_manager", _SpyWsManager())

    payload = await _create_thread(new_client, subject="auto appear", creator_id="agent-alpha")

    created = [
        e
        for (_tk, e) in events
        if e.get("type") == "thread_update" and e.get("data", {}).get("update_type") == "created"
    ]
    assert len(created) == 1, f"expected exactly one 'created' broadcast, got: {events!r}"
    data = created[0]["data"]
    assert data["tenant_key"] == tenant_key
    assert data["thread_id"] == payload["thread_id"]
    assert data["chat_id"] == payload["chat_id"]
    assert data["chat_id"].startswith("CHT-")
    assert data["next_action_owner"] == "agent-alpha"


async def test_post_broadcast_and_read_history(comm_mcp_client):
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="topic", creator_id="agent-alpha")
    tid = thread["thread_id"]

    async with new_client() as s:
        join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "agent-beta"})
        assert join.isError is False, _error_text(join)
        post = await s.call_tool(
            "post_to_thread", {"thread_id": tid, "content": "hello board", "from_agent": "agent-alpha"}
        )
        assert post.isError is False, _error_text(post)
        post_payload = _payload(post)
        # broadcast reached the other participant (beta), not the sender (alpha)
        assert "agent-beta" in post_payload["recipients"]
        assert "agent-alpha" not in post_payload["recipients"]

        hist = await s.call_tool("get_thread_history", {"thread_id": tid})
        assert hist.isError is False, _error_text(hist)
        hist_payload = _payload(hist)
    assert hist_payload["count"] == 1
    msg = hist_payload["messages"][0]
    assert msg["content"] == "hello board"
    assert msg["from_display_name"] == "agent-alpha"
    # READ-ONLY: history does not acknowledge — message stays 'pending'.
    assert msg["status"] == "pending"


async def test_get_my_turn_and_pass_baton(comm_mcp_client):
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="baton", creator_id="agent-alpha")
    tid = thread["thread_id"]

    async with new_client() as s:
        # BE-9292a: the baton target must be reachable, so beta joins before receiving
        # it. What this test guards is unchanged — the baton moves and get_my_turn
        # follows it from alpha to beta.
        joined = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "agent-beta"})
        assert joined.isError is False, _error_text(joined)

        mine = await s.call_tool("get_my_turn", {"agent_id": "agent-alpha"})
        assert mine.isError is False, _error_text(mine)
        assert tid in {t["thread_id"] for t in _payload(mine)["threads"]}

        handoff = await s.call_tool("pass_baton", {"thread_id": tid, "to": "agent-beta"})
        assert handoff.isError is False, _error_text(handoff)
        assert _payload(handoff)["next_action_owner"] == "agent-beta"

        # Now it's beta's turn, not alpha's.
        beta = await s.call_tool("get_my_turn", {"agent_id": "agent-beta"})
        alpha = await s.call_tool("get_my_turn", {"agent_id": "agent-alpha"})
    assert tid in {t["thread_id"] for t in _payload(beta)["threads"]}
    assert tid not in {t["thread_id"] for t in _payload(alpha)["threads"]}


async def test_username_injection_on_user_post(comm_mcp_client):
    new_client, _tk, user_id, _base, monkeypatch = comm_mcp_client
    thread = await _create_thread(new_client, subject="user chat", creator_id="agent-alpha")
    tid = thread["thread_id"]

    # Simulate an authenticated USER (not an agent) posting.
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: user_id)
    async with new_client() as s:
        post = await s.call_tool("post_to_thread", {"thread_id": tid, "content": "from the operator"})
        assert post.isError is False, _error_text(post)
        hist = await s.call_tool("get_thread_history", {"thread_id": tid})
    msg = _payload(hist)["messages"][0]
    # The user's username/display_name is stamped, not an agent id.
    assert msg["from_display_name"].startswith("patrik_")
    assert msg["from_agent_id"] == user_id


async def test_agent_attribution_wins_over_authenticated_user(comm_mcp_client):
    """FE-6122 regression at the bug's layer (the @mcp.tool wrapper + dispatch).

    The wrapper ALWAYS injects the verified principal's user_id, yet a post that
    carries a non-empty from_agent must attribute to the AGENT (its activated-
    template role), NOT collapse to the human principal. This is the precedence
    flip: from_agent wins, user_id is the fallback. Authz/tenant context is
    unchanged (user_id is still injected) — only the displayed author differs.
    """
    new_client, _tk, user_id, _base, monkeypatch = comm_mcp_client
    thread = await _create_thread(new_client, subject="agent identity", creator_id="implementer")
    tid = thread["thread_id"]

    # Authenticated principal present (exactly as on the real MCP path) AND from_agent set.
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: user_id)
    async with new_client() as s:
        post = await s.call_tool(
            "post_to_thread", {"thread_id": tid, "content": "building it", "from_agent": "implementer"}
        )
        assert post.isError is False, _error_text(post)
        hist = await s.call_tool("get_thread_history", {"thread_id": tid})
    msg = _payload(hist)["messages"][0]
    # Attributed to the agent role — NOT collapsed to the user principal.
    assert msg["from_agent_id"] == "implementer"
    assert msg["from_display_name"] == "implementer"
    assert msg["from_agent_id"] != user_id


async def test_post_resolves_display_name_from_participant_directory(comm_mcp_client):
    """Bug-fix regression at the @mcp.tool boundary: a poster's ``from_agent`` UUID
    must resolve to its comm_participants ``display_name`` (set via join_thread),
    not be echoed verbatim as the stored/displayed author name."""
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="badge resolution", creator_id="orchestrator")
    tid = thread["thread_id"]
    agent_uuid = "aeaeb3eb-ea5c-4c1a-9b1a-000000000002"

    async with new_client() as s:
        join = await s.call_tool(
            "join_thread", {"thread_id": tid, "agent_id": agent_uuid, "display_name": "orchestrator"}
        )
        assert join.isError is False, _error_text(join)
        post = await s.call_tool("post_to_thread", {"thread_id": tid, "content": "status", "from_agent": agent_uuid})
        assert post.isError is False, _error_text(post)
        post_payload = _payload(post)
        hist = await s.call_tool("get_thread_history", {"thread_id": tid})
    assert post_payload["from_display_name"] == "orchestrator"
    assert post_payload["from_agent_id"] == agent_uuid
    msg = _payload(hist)["messages"][0]
    assert msg["from_display_name"] == "orchestrator"
    assert msg["from_agent_id"] == agent_uuid


async def test_from_agent_over_id_max_is_rejected(comm_mcp_client):
    """from_agent is agent-supplied input: an over-long value is rejected at the
    boundary (length cap), not silently truncated or written to the DB."""
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="cap", creator_id="agent-alpha")
    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": thread["thread_id"], "content": "x", "from_agent": "a" * 65},
        )
    assert res.isError is True


async def test_post_empty_content_is_rejected(comm_mcp_client):
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="x", creator_id="agent-alpha")
    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread", {"thread_id": thread["thread_id"], "content": "   ", "from_agent": "agent-alpha"}
        )
    assert res.isError is True
    assert "content" in _error_text(res).lower()


async def test_unknown_thread_is_not_found(comm_mcp_client):
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    async with new_client() as s:
        res = await s.call_tool("get_thread_history", {"thread_id": str(uuid4())})
    assert res.isError is True
    assert "not found" in _error_text(res).lower()


async def test_search_threads_by_subject(comm_mcp_client):
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    await _create_thread(new_client, subject="migration rollout plan", creator_id="agent-alpha")
    async with new_client() as s:
        res = await s.call_tool("search_threads", {"query": "rollout"})
    assert res.isError is False, _error_text(res)
    payload = _payload(res)
    assert payload["count"] >= 1
    assert any("rollout" in (t["subject"] or "") for t in payload["threads"])


async def test_loop_directive_interval_round_trips_over_mcp(comm_mcp_client):
    """FE-6140 regression at the @mcp.tool boundary.

    An armed loop directive's interval must round-trip over the wire and surface on
    BOTH poll surfaces (get_thread_history + get_my_turn) — and reach a participant
    that does NOT hold the baton (the design's "ALL participants" intent).
    """
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="checkin", creator_id="orchestrator")
    tid = thread["thread_id"]

    async with new_client() as s:
        join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "worker-1"})
        assert join.isError is False, _error_text(join)
        post = await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": "please check in",
                "from_agent": "orchestrator",
                "loop_directive": True,
                "loop_interval_minutes": 15,
            },
        )
        assert post.isError is False, _error_text(post)
        assert _payload(post)["loop_interval_minutes"] == 15

        hist = await s.call_tool("get_thread_history", {"thread_id": tid})
        assert hist.isError is False, _error_text(hist)
        # worker-1 does NOT hold the baton (orchestrator created the thread).
        mine = await s.call_tool("get_my_turn", {"agent_id": "worker-1"})
        assert mine.isError is False, _error_text(mine)

    assert _payload(hist)["loop_directive"] == {"active": True, "interval_minutes": 15}
    directives = _payload(mine)["loop_directives"]
    assert len(directives) == 1
    assert directives[0]["thread_id"] == tid
    assert directives[0]["interval_minutes"] == 15


async def test_loop_directive_interval_silenced_after_close_over_mcp(comm_mcp_client):
    """Closing the thread flips the poll-surface directive to inactive (the loop's
    provable termination), over the wire."""
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="closeable loop", creator_id="orchestrator")
    tid = thread["thread_id"]
    async with new_client() as s:
        await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "worker-1"})
        await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": "loop",
                "from_agent": "orchestrator",
                "loop_directive": True,
                "loop_interval_minutes": 10,
            },
        )
        await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "done", "from_agent": "orchestrator", "set_status": "closed"},
        )
        hist = await s.call_tool("get_thread_history", {"thread_id": tid})
        mine = await s.call_tool("get_my_turn", {"agent_id": "worker-1"})
    assert _payload(hist)["loop_directive"] == {"active": False, "interval_minutes": None}
    assert _payload(mine)["loop_directives"] == []


async def test_set_status_closes_thread(comm_mcp_client):
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="closable", creator_id="agent-alpha")
    tid = thread["thread_id"]
    async with new_client() as s:
        post = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "wrapping up", "from_agent": "agent-alpha", "set_status": "closed"},
        )
        assert post.isError is False, _error_text(post)
        listed = await s.call_tool("list_threads", {"status": "closed"})
    assert tid in {t["thread_id"] for t in _payload(listed)["threads"]}


# ── BE-6226 — get_thread_history incremental fetch (boundary regression) ──────
#
# These exercise the new since/after_message_id/tail params over the MCP transport
# (the failing layer is the @mcp.tool wrapper + dispatch + service). created_at is
# server_default=func.now() = Postgres transaction time, so messages posted in this
# test's single (rolled-back) transaction share a timestamp; we request the SAME
# db_session the MCP path reads via test_session and stamp DISTINCT created_at so the
# marker/tail filters bite deterministically (in prod each post is its own
# transaction, so created_at differs naturally).

_T1 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
_T2 = datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)
_T3 = datetime(2026, 1, 1, 0, 0, 3, tzinfo=UTC)


async def _seed_three_messages(new_client, db_session, tenant_key):
    """Create a thread with 3 messages m1<m2<m3 at distinct, increasing created_at.

    Returns (thread_id, [id1, id2, id3]). Stamps created_at via the shared db_session
    (same transaction the MCP reads see) because func.now() is transaction-time."""
    thread = await _create_thread(new_client, subject="incremental", creator_id="agent-alpha")
    tid = thread["thread_id"]
    ids: list[str] = []
    async with new_client() as s:
        await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "agent-beta"})
        for n in (1, 2, 3):
            post = await s.call_tool(
                "post_to_thread", {"thread_id": tid, "content": f"m{n}", "from_agent": "agent-alpha"}
            )
            assert post.isError is False, _error_text(post)
            ids.append(_payload(post)["message_id"])
    with tenant_session_context(db_session, tenant_key):
        for mid, ts in zip(ids, (_T1, _T2, _T3), strict=True):
            await db_session.execute(sa_update(Message).where(Message.id == mid).values(created_at=ts))
        await db_session.flush()
    return tid, ids


async def test_history_omitted_params_returns_full_timeline(comm_mcp_client, db_session):
    """Backward-compat: omitting all incremental params returns the FULL timeline,
    oldest-first, with the unchanged response shape (the conductor's today behaviour)."""
    new_client, tenant_key, _uid, _base, _mp = comm_mcp_client
    tid, _ids = await _seed_three_messages(new_client, db_session, tenant_key)
    async with new_client() as s:
        hist = await s.call_tool("get_thread_history", {"thread_id": tid})
    payload = _payload(hist)
    assert hist.isError is False, _error_text(hist)
    # Response shape unchanged (thread + count + messages + loop_directive); the MCP
    # transport adds its own _meta envelope key, so assert the payload keys are present.
    assert {"thread", "count", "messages", "loop_directive"} <= set(payload)
    assert payload["count"] == 3
    assert [m["content"] for m in payload["messages"]] == ["m1", "m2", "m3"]


async def test_history_after_message_id_returns_only_newer(comm_mcp_client, db_session):
    """after_message_id is the poll cursor: only messages created AFTER it come back."""
    new_client, tenant_key, _uid, _base, _mp = comm_mcp_client
    tid, ids = await _seed_three_messages(new_client, db_session, tenant_key)
    async with new_client() as s:
        hist = await s.call_tool("get_thread_history", {"thread_id": tid, "after_message_id": ids[0]})
    payload = _payload(hist)
    assert hist.isError is False, _error_text(hist)
    assert payload["count"] == 2
    assert [m["content"] for m in payload["messages"]] == ["m2", "m3"]


async def test_history_after_unknown_id_returns_empty(comm_mcp_client, db_session):
    """A cursor that is not on this thread => nothing newer to fetch (empty, not error)."""
    new_client, tenant_key, _uid, _base, _mp = comm_mcp_client
    tid, _ids = await _seed_three_messages(new_client, db_session, tenant_key)
    async with new_client() as s:
        hist = await s.call_tool("get_thread_history", {"thread_id": tid, "after_message_id": str(uuid4())})
    payload = _payload(hist)
    assert hist.isError is False, _error_text(hist)
    assert payload["count"] == 0
    assert payload["messages"] == []


async def test_history_tail_returns_last_n(comm_mcp_client, db_session):
    """tail=N returns the LAST N messages, still oldest-first."""
    new_client, tenant_key, _uid, _base, _mp = comm_mcp_client
    tid, _ids = await _seed_three_messages(new_client, db_session, tenant_key)
    async with new_client() as s:
        hist = await s.call_tool("get_thread_history", {"thread_id": tid, "tail": 2})
    payload = _payload(hist)
    assert hist.isError is False, _error_text(hist)
    assert payload["count"] == 2
    assert [m["content"] for m in payload["messages"]] == ["m2", "m3"]


async def test_history_since_returns_only_after_timestamp(comm_mcp_client, db_session):
    """since (ISO-8601) returns only messages created strictly after that time."""
    new_client, tenant_key, _uid, _base, _mp = comm_mcp_client
    tid, _ids = await _seed_three_messages(new_client, db_session, tenant_key)
    async with new_client() as s:
        hist = await s.call_tool("get_thread_history", {"thread_id": tid, "since": _T1.isoformat()})
    payload = _payload(hist)
    assert hist.isError is False, _error_text(hist)
    assert payload["count"] == 2
    assert [m["content"] for m in payload["messages"]] == ["m2", "m3"]


async def test_history_after_and_since_mutually_exclusive(comm_mcp_client, db_session):
    """after_message_id and since both name a start marker -> clean boundary rejection."""
    new_client, tenant_key, _uid, _base, _mp = comm_mcp_client
    tid, ids = await _seed_three_messages(new_client, db_session, tenant_key)
    async with new_client() as s:
        res = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "after_message_id": ids[0], "since": _T1.isoformat()},
        )
    assert res.isError is True
    assert "at most one" in _error_text(res).lower()


async def test_history_bad_since_rejected(comm_mcp_client, db_session):
    """A non-ISO since is rejected at the boundary (422), not a 500."""
    new_client, tenant_key, _uid, _base, _mp = comm_mcp_client
    tid, _ids = await _seed_three_messages(new_client, db_session, tenant_key)
    async with new_client() as s:
        res = await s.call_tool("get_thread_history", {"thread_id": tid, "since": "not-a-timestamp"})
    assert res.isError is True
    assert "iso" in _error_text(res).lower()


# ── BE-9037 — from_agent hardening over the MCP transport ─────────────────────
#
# The failing layer is the @mcp.tool wrapper + dispatch + service. These prove:
# an ad-hoc lane id (not a registered template) is sanitized + accepted + slug-
# attributed (the live-coordination-thread guarantee), all-garbage is a clean
# error (never a 500 / blank identity), and an omitted from_agent surfaces an
# advisory instead of silently stamping the owner.


async def test_be9037_ad_hoc_lane_id_sanitized_and_attributed_over_transport(comm_mcp_client):
    """An ad-hoc lane id (e.g. BE-9037) carrying trailing zero-width chars is
    sanitized and accepted, attributed by its SLUG (no UUID rewrite), and still
    self-excludes from its own broadcast — the running-operation guarantee."""
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="lane", creator_id="BE-9037")
    tid = thread["thread_id"]
    async with new_client() as s:
        join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "SEC-3001b"})
        assert join.isError is False, _error_text(join)
        post = await s.call_tool(
            "post_to_thread", {"thread_id": tid, "content": "status", "from_agent": "BE-9037\u200b"}
        )
        assert post.isError is False, _error_text(post)
        pp = _payload(post)
    assert pp["from_agent_id"] == "BE-9037"  # zero-width stripped, slug preserved (not a UUID)
    assert "SEC-3001b" in pp["recipients"]
    assert "BE-9037" not in pp["recipients"]  # slug self-exclusion intact


async def test_be9037_all_garbage_from_agent_is_clean_error_over_transport(comm_mcp_client):
    """A from_agent that is ONLY zero-width/control chars is rejected cleanly at the
    boundary (isError) — never a 500, never a blank identity written to the DB."""
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="garbage", creator_id="agent-alpha")
    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread", {"thread_id": thread["thread_id"], "content": "x", "from_agent": "\u200b\ufeff"}
        )
    assert res.isError is True


async def test_be9037_omitted_from_agent_surfaces_attribution_warning_over_transport(comm_mcp_client):
    """TSK-0008 over the wire: an omitted from_agent returns an advisory in the
    response (surface-don't-stamp); a from_agent-bearing post returns none."""
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="warn", creator_id="agent-alpha")
    tid = thread["thread_id"]
    async with new_client() as s:
        omitted = await s.call_tool("post_to_thread", {"thread_id": tid, "content": "no id"})
        assert omitted.isError is False, _error_text(omitted)
        supplied = await s.call_tool(
            "post_to_thread", {"thread_id": tid, "content": "with id", "from_agent": "implementer"}
        )
        assert supplied.isError is False, _error_text(supplied)
    assert _payload(omitted)["attribution_warning"]  # non-empty advisory surfaced
    assert _payload(supplied)["attribution_warning"] is None


# ---------------------------------------------------------------------------
# BE-9214 — agent-id column width: the hub validates agent_id up to 64 chars,
# but the reused legacy message-persistence columns were varchar(36). Once a
# participant with a >36-char id joined, EVERY broadcast to that thread 500'd on
# the recipient fan-out INSERT (StringDataRightTruncation). Regression at the
# @mcp.tool transport (where the bug was observed) + a direct model-layer check
# that every widened agent-id column in the fan-out family holds the full 64.
# ---------------------------------------------------------------------------

# The incident id was 45 chars; exercise the full validated 64-char ceiling.
_BE9214_LONG_ID = ("gil-reviewer-yapper-implementer-pr11-20260717-lane-m2-conductor-0123456789")[:64]


async def test_be9214_broadcast_and_directed_post_to_64char_agent(comm_mcp_client):
    """Live-blocker regression at the @mcp.tool boundary: a 64-char agent id must
    survive the whole broadcast/baton/directed-post fan-out. Pre-fix this 500'd on
    the message_recipients (and messages.from_agent_id) INSERT against varchar(36).
    """
    assert len(_BE9214_LONG_ID) == 64
    new_client, _tk, _uid, _base, _mp = comm_mcp_client
    thread = await _create_thread(new_client, subject="long id", creator_id="orchestrator")
    tid = thread["thread_id"]

    async with new_client() as s:
        join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": _BE9214_LONG_ID})
        assert join.isError is False, _error_text(join)

        # (a) POST FROM the 64-char agent -> exercises messages.from_agent_id at 64.
        from_long = await s.call_tool(
            "post_to_thread", {"thread_id": tid, "content": "from the long id", "from_agent": _BE9214_LONG_ID}
        )
        assert from_long.isError is False, _error_text(from_long)
        assert _payload(from_long)["from_agent_id"] == _BE9214_LONG_ID

        # (b) BROADCAST from the short creator -> the 64-char participant lands in
        # the message_recipients fan-out (the exact incident).
        broadcast = await s.call_tool(
            "post_to_thread", {"thread_id": tid, "content": "hello board", "from_agent": "orchestrator"}
        )
        assert broadcast.isError is False, _error_text(broadcast)
        assert _BE9214_LONG_ID in _payload(broadcast)["recipients"]

        # (c) DIRECTED post to the 64-char agent -> single recipient row at 64.
        directed = await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": "just for you",
                "from_agent": "orchestrator",
                "to_participant": _BE9214_LONG_ID,
            },
        )
        assert directed.isError is False, _error_text(directed)
        assert _payload(directed)["recipients"] == [_BE9214_LONG_ID]

        # (d) pass_baton to the 64-char id -> baton column holds it.
        handoff = await s.call_tool("pass_baton", {"thread_id": tid, "to": _BE9214_LONG_ID})
        assert handoff.isError is False, _error_text(handoff)
        assert _payload(handoff)["next_action_owner"] == _BE9214_LONG_ID

        mine = await s.call_tool("get_my_turn", {"agent_id": _BE9214_LONG_ID})
        assert mine.isError is False, _error_text(mine)
    assert tid in {t["thread_id"] for t in _payload(mine)["threads"]}


async def test_be9214_all_message_fanout_agent_id_columns_hold_64(db_session):
    """Class-level regression: every agent-id column in the message-persistence
    fan-out family (messages.from_agent_id + the recipient/ack/completion
    junctions) must persist a full 64-char id. Pre-fix these were varchar(36) and
    a 64-char id raised StringDataRightTruncation on INSERT."""
    assert len(_BE9214_LONG_ID) == 64
    tenant_key = TenantManager.generate_tenant_key()

    message = Message(tenant_key=tenant_key, content="fan-out width check", from_agent_id=_BE9214_LONG_ID)
    db_session.add(message)
    await db_session.flush()
    db_session.add(MessageRecipient(message_id=message.id, agent_id=_BE9214_LONG_ID, tenant_key=tenant_key))
    db_session.add(MessageAcknowledgment(message_id=message.id, agent_id=_BE9214_LONG_ID, tenant_key=tenant_key))
    db_session.add(MessageCompletion(message_id=message.id, agent_id=_BE9214_LONG_ID, tenant_key=tenant_key))
    await db_session.flush()

    reloaded = await db_session.get(Message, message.id)
    assert reloaded.from_agent_id == _BE9214_LONG_ID
    for model in (MessageRecipient, MessageAcknowledgment, MessageCompletion):
        rows = (await db_session.execute(select(model).where(model.message_id == message.id))).scalars().all()
        assert len(rows) == 1
        assert rows[0].agent_id == _BE9214_LONG_ID


async def test_be9214_sequence_run_conductor_agent_id_holds_64(db_session):
    """Same class at the chain-runtime boundary: a chain conductor self-registers a
    free-form agent id on ``sequence_runs.conductor_agent_id``, validated to 64 at
    the chain-start boundary. Pre-fix the column was varchar(36) and a >36-char
    conductor id raised StringDataRightTruncation. Folded into ce_0080 per the
    orchestrator ruling on BE-9214."""
    assert len(_BE9214_LONG_ID) == 64
    tenant_key = TenantManager.generate_tenant_key()

    run = SequenceRun(
        tenant_key=tenant_key,
        project_ids=[],
        resolved_order=[],
        execution_mode="multi_terminal",
        conductor_agent_id=_BE9214_LONG_ID,
    )
    db_session.add(run)
    await db_session.flush()

    reloaded = await db_session.get(SequenceRun, run.id)
    assert reloaded.conductor_agent_id == _BE9214_LONG_ID
