# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary tests for BE-9012a — server-persistent read cursor (D6)
+ per-recipient acted-on state (D4) on ``get_thread_history``.

CLAUDE.md / BE-5042 mandate a regression at the layer the behavior lives. The
cursor read lives at the FastMCP ``@mcp.tool`` wrapper
(``api/endpoints/mcp_tools/_comm_tools.py`` -> ``_call_tool`` dispatch ->
``CommThreadService.get_thread_history``). These tests exercise the ACTUAL
transport (``create_connected_server_and_client_session``) so the new params,
the required-param 422, and the structured NOT_A_PARTICIPANT rejection are all
covered end-to-end, not just at the service.

Behaviors under test (over the wire):
- unread_only + mark_read is an O(N) drain: N posts are delivered exactly once,
  the cursor advances exactly once, and a re-read returns nothing new.
- mark_read writes ``message_acknowledgments`` (D4) idempotently.
- the four cursor params REQUIRE as_participant (clean 422 without it).
- mark_read on a thread the reader never joined => structured NOT_A_PARTICIPANT
  (a domain rejection delivered as normal content, NOT isError).
- unread_only for a never-joined reader is honest: it returns the whole timeline.
- directed_only excludes posts aimed at OTHER participants.
- action_required_only returns only requires_action posts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy import update as sa_update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.tasks import Message, MessageAcknowledgment
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

# created_at is server_default=func.now() = Postgres transaction time, so posts in
# this test's single (rolled-back) transaction share a timestamp. Where the cursor
# advance is asserted, stamp DISTINCT increasing created_at via the shared db_session
# (the same transaction the MCP path reads through test_session) so the filter bites
# deterministically. In prod each post is its own transaction, so times differ.
_T1 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
_T2 = datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)
_T3 = datetime(2026, 1, 1, 0, 0, 3, tzinfo=UTC)


async def _stamp(db_session, tenant_key, ids_ts):
    with tenant_session_context(db_session, tenant_key):
        for mid, ts in ids_ts:
            await db_session.execute(sa_update(Message).where(Message.id == mid).values(created_at=ts))
        await db_session.flush()


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
    """Yield ``(new_client, tenant_key, db_session)`` for FastMCP transport tests.

    CommThreadService receives ``test_session`` from ToolAccessor, so its writes
    land in the rolled-back transaction (visible to db_session queries, no commit).
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
        yield _new_client, tenant_key, db_session
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
    assert res.is_error is False, _error_text(res)
    return _payload(res)


async def _setup_thread_with_beta(new_client):
    """A thread whose creator is alpha, with beta joined. Returns thread_id."""
    thread = await _create_thread(new_client, subject="cursor", creator_id="alpha")
    tid = thread["thread_id"]
    async with new_client() as s:
        join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "beta"})
        assert join.is_error is False, _error_text(join)
    return tid


async def _post(new_client, tid, content, **kwargs):
    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread", {"thread_id": tid, "content": content, "from_agent": "alpha", **kwargs}
        )
    assert res.is_error is False, _error_text(res)
    return _payload(res)


async def test_unread_drain_is_on_delivered_once_and_cursor_advances_once(comm_mcp_client):
    """The O(N) guarantee: N posts delivered exactly once across a drain sequence,
    cursor advances exactly once, re-read returns nothing new."""
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _setup_thread_with_beta(new_client)
    ids = [(await _post(new_client, tid, f"post {i}"))["message_id"] for i in range(3)]
    await _stamp(db_session, tenant_key, list(zip(ids, (_T1, _T2, _T3), strict=True)))

    # First drain: all 3 unread returned + marked read.
    async with new_client() as s:
        first = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "unread_only": True, "mark_read": True},
        )
        assert first.is_error is False, _error_text(first)
    first_p = _payload(first)
    assert first_p["count"] == 3
    assert first_p["marked_read"] == 3

    # Second drain: cursor advanced => nothing new. Delivered-once, not O(N^2).
    async with new_client() as s:
        second = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "unread_only": True, "mark_read": True},
        )
        assert second.is_error is False, _error_text(second)
    second_p = _payload(second)
    assert second_p["count"] == 0
    assert second_p["marked_read"] == 0

    # Total volume delivered across the whole sequence == N (3), not N + N.
    total_delivered = first_p["count"] + second_p["count"]
    assert total_delivered == 3


async def test_mark_read_writes_acknowledgments_idempotently(comm_mcp_client):
    """D4: mark_read records message_acknowledgments for the reader; a repeat is a
    no-op (idempotent via uq_msg_ack), never a duplicate."""
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _setup_thread_with_beta(new_client)
    await _post(new_client, tid, "one")
    await _post(new_client, tid, "two")

    async def _ack_count() -> int:
        with tenant_session_context(db_session, tenant_key):
            res = await db_session.execute(
                select(func.count())
                .select_from(MessageAcknowledgment)
                .where(
                    MessageAcknowledgment.tenant_key == tenant_key,
                    MessageAcknowledgment.agent_id == "beta",
                )
            )
        return res.scalar_one()

    assert await _ack_count() == 0
    async with new_client() as s:
        await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "mark_read": True},
        )
    assert await _ack_count() == 2
    # Re-mark the same posts: idempotent — still exactly 2 ack rows.
    async with new_client() as s:
        await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "mark_read": True},
        )
    assert await _ack_count() == 2


async def test_cursor_params_require_as_participant(comm_mcp_client):
    """Each of the four cursor params without as_participant => clean 422 (isError)."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _setup_thread_with_beta(new_client)
    for param in ("unread_only", "mark_read", "directed_only", "action_required_only"):
        async with new_client() as s:
            res = await s.call_tool("get_thread_history", {"thread_id": tid, param: True})
        assert res.is_error is True, f"{param} without as_participant should 422"
        assert "as_participant" in _error_text(res)


async def test_mark_read_on_non_participant_is_structured_rejection(comm_mcp_client):
    """mark_read by a reader that never join_thread'd => NOT_A_PARTICIPANT, delivered
    as normal content (NOT isError) per the BE-6081 domain-rejection carve-out."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _setup_thread_with_beta(new_client)
    await _post(new_client, tid, "hello")

    async with new_client() as s:
        res = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "ghost", "mark_read": True},
        )
    assert res.is_error is False, _error_text(res)  # domain rejection, not an error
    p = _payload(res)
    assert p["success"] is False
    assert p["error"] == "NOT_A_PARTICIPANT"
    assert "join_thread" in p["hint"]


async def test_unread_only_for_never_joined_reader_is_honest_full_timeline(comm_mcp_client):
    """as_participant given but no cursor row (never joined) => unread returns the
    whole timeline (honest 'nothing read yet'), NOT an error and NOT empty."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _setup_thread_with_beta(new_client)
    await _post(new_client, tid, "a")
    await _post(new_client, tid, "b")

    async with new_client() as s:
        res = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "ghost", "unread_only": True},
        )
    assert res.is_error is False, _error_text(res)
    assert _payload(res)["count"] == 2


async def test_directed_only_returns_posts_delivered_to_reader(comm_mcp_client):
    """directed_only = posts the reader is a recipient of — the inbox semantic that
    replaces receive_messages. That INCLUDES a broadcast delivered to the reader and a
    DM addressed to them; it EXCLUDES a DM aimed only at another participant and the
    reader's OWN posts (a broadcast excludes its sender from the fan-out)."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _setup_thread_with_beta(new_client)
    async with new_client() as s:
        join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "gamma"})
        assert join.is_error is False, _error_text(join)
    await _post(new_client, tid, "broadcast to all")  # alpha broadcast -> beta is a recipient
    await _post(new_client, tid, "dm to beta", to_participant="beta")
    await _post(new_client, tid, "dm to gamma", to_participant="gamma")

    async with new_client() as s:
        res = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "directed_only": True},
        )
    assert res.is_error is False, _error_text(res)
    contents = [m["content"] for m in _payload(res)["messages"]]
    assert "broadcast to all" in contents  # delivered to beta -> included
    assert "dm to beta" in contents
    assert "dm to gamma" not in contents  # aimed only at gamma -> excluded


async def test_action_required_only_filters_to_action_posts(comm_mcp_client):
    """action_required_only returns only requires_action posts."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _setup_thread_with_beta(new_client)
    await _post(new_client, tid, "just informational")
    await _post(new_client, tid, "please act", requires_action=True)

    async with new_client() as s:
        res = await s.call_tool(
            "get_thread_history",
            {"thread_id": tid, "as_participant": "beta", "action_required_only": True},
        )
    assert res.is_error is False, _error_text(res)
    contents = [m["content"] for m in _payload(res)["messages"]]
    assert contents == ["please act"]
