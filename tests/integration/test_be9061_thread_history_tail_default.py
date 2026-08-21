# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9061 — get_thread_history default is a bounded tail (MCP-transport boundary).

The behavior changed at the FastMCP ``@mcp.tool`` wrapper layer
(``api/endpoints/mcp_tools/_comm_tools.py``), so per CLAUDE.md the regression runs
over the ACTUAL transport (``create_connected_server_and_client_session``), not
just the service. Proves:

  * a PLAIN poll now returns only the last ``DEFAULT_HISTORY_TAIL`` messages
    (the hot loop_directive read no longer re-reads the whole timeline);
  * ``tail=0`` still returns the ENTIRE timeline (explicit full-read preserved);
  * ``tail=N`` returns the last N;
  * an ``unread_only`` cursor read is NOT truncated by the default (its full
    delta comes back — critical so a mark_read drain cannot stall).

Parallel-safe: unique synthetic tenant, all writes on the rolled-back
``db_session`` the ToolAccessor shares (TransactionalTestContext equivalent).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from api.endpoints.mcp_tools._comm_tools import DEFAULT_HISTORY_TAIL
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.tasks import Message
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        return res.structured_content
    return json.loads(res.content[0].text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


@pytest_asyncio.fixture
async def hist_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_key)`` for get_thread_history boundary tests."""
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
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
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


async def _seed_thread_with_messages(new_client, db_session, tenant_key, count):
    async with new_client() as s:
        res = await s.call_tool("create_thread", {"subject": "growth", "creator_id": "agent-alpha"})
    assert res.is_error is False, _error_text(res)
    tid = _payload(res)["thread_id"]

    base = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add_all(
        [
            Message(
                id=str(uuid4()),
                tenant_key=tenant_key,
                thread_id=tid,
                content=f"m{i}",
                message_type="broadcast",
                from_agent_id="agent-alpha",
                created_at=base + timedelta(seconds=i),
            )
            for i in range(count)
        ]
    )
    await db_session.flush()
    return tid


async def test_plain_read_defaults_to_bounded_tail(hist_client, db_session):
    new_client, tenant_key = hist_client
    total = DEFAULT_HISTORY_TAIL + 5
    tid = await _seed_thread_with_messages(new_client, db_session, tenant_key, total)

    async with new_client() as s:
        res = await s.call_tool("get_thread_history", {"thread_id": tid})
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)

    # Only the most recent DEFAULT_HISTORY_TAIL come back, oldest-first.
    assert payload["count"] == DEFAULT_HISTORY_TAIL
    contents = [m["content"] for m in payload["messages"]]
    assert contents[0] == "m5"  # first 5 (m0..m4) trimmed by the tail
    assert contents[-1] == f"m{total - 1}"


async def test_tail_zero_returns_full_timeline(hist_client, db_session):
    new_client, tenant_key = hist_client
    total = DEFAULT_HISTORY_TAIL + 5
    tid = await _seed_thread_with_messages(new_client, db_session, tenant_key, total)

    async with new_client() as s:
        res = await s.call_tool("get_thread_history", {"thread_id": tid, "tail": 0})
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)

    assert payload["count"] == total  # explicit full read still available
    assert payload["messages"][0]["content"] == "m0"
    assert payload["messages"][-1]["content"] == f"m{total - 1}"


async def test_explicit_tail_n_honored(hist_client, db_session):
    new_client, tenant_key = hist_client
    total = DEFAULT_HISTORY_TAIL + 5
    tid = await _seed_thread_with_messages(new_client, db_session, tenant_key, total)

    async with new_client() as s:
        res = await s.call_tool("get_thread_history", {"thread_id": tid, "tail": 50})
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)

    assert payload["count"] == 50
    assert payload["messages"][0]["content"] == f"m{total - 50}"


async def test_mark_read_read_not_truncated_by_default(hist_client, db_session):
    new_client, tenant_key = hist_client
    total = DEFAULT_HISTORY_TAIL + 5
    tid = await _seed_thread_with_messages(new_client, db_session, tenant_key, total)

    async with new_client() as s:
        join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "agent-gamma"})
        assert join.is_error is False, _error_text(join)
        # A plain mark_read read (no unread_only) advances the participant's read
        # cursor over what it returns. The default tail must NOT cap it, or the
        # cursor would jump PAST unseen older posts on the next unread drain.
        res = await s.call_tool(
            "get_thread_history", {"thread_id": tid, "as_participant": "agent-gamma", "mark_read": True}
        )
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)
    assert payload["count"] == total


async def test_unread_only_read_not_truncated_by_default(hist_client, db_session):
    new_client, tenant_key = hist_client
    total = DEFAULT_HISTORY_TAIL + 5
    tid = await _seed_thread_with_messages(new_client, db_session, tenant_key, total)

    async with new_client() as s:
        join = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": "agent-beta"})
        assert join.is_error is False, _error_text(join)
        # A fresh participant has no read cursor -> unread is the whole timeline.
        # The default tail must NOT cap it (a truncated drain would stall mark_read).
        res = await s.call_tool(
            "get_thread_history", {"thread_id": tid, "as_participant": "agent-beta", "unread_only": True}
        )
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)
    assert payload["count"] == total
