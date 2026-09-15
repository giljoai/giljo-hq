# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
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
    block = res.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


@pytest_asyncio.fixture
async def mcp_env(db_manager, db_session, monkeypatch):
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
    user = User(id=str(uuid4()), tenant_key=tenant_key, username=f"operator_{suffix}")
    db_session.add(user)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: user.id)

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
    assert res.is_error is False, _error_text(res)
    return _payload(res)


async def _message_count(db_session, thread_id: str) -> int:
    return (
        await db_session.execute(select(func.count()).select_from(Message).where(Message.thread_id == thread_id))
    ).scalar_one()


async def test_omitted_from_agent_is_refused_and_writes_nothing(mcp_env, db_session):
    new_client, _tk, _user_id, _base, _mp = mcp_env
    thread = await _create_thread(new_client, subject="fail closed", creator_id="agent-alpha")
    tid = thread["thread_id"]

    async with new_client() as s:
        res = await s.call_tool("post_to_thread", {"thread_id": tid, "content": "who am I?"})
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)
    assert payload["success"] is False
    assert payload["error"] == "FROM_AGENT_REQUIRED"
    assert "as_user" in payload["message"]
    assert await _message_count(db_session, tid) == 0


async def test_as_user_attributes_to_the_authenticated_principal(mcp_env, db_session):
    new_client, _tk, user_id, _base, _mp = mcp_env
    thread = await _create_thread(new_client, subject="operator voice", creator_id="agent-alpha")
    tid = thread["thread_id"]

    async with new_client() as s:
        res = await s.call_tool("post_to_thread", {"thread_id": tid, "content": "operator here", "as_user": True})
        assert res.is_error is False, _error_text(res)
        payload = _payload(res)
        hist = await s.call_tool("get_thread_history", {"thread_id": tid})
    assert payload["from_kind"] == "user"
    assert payload["from_agent_id"] == user_id
    assert payload["attribution_warning"] is None
    msg = _payload(hist)["messages"][0]
    assert msg["from_kind"] == "user"
    assert msg["from_agent_id"] == user_id


async def test_from_agent_attributes_to_that_agent(mcp_env):
    new_client, _tk, user_id, _base, _mp = mcp_env
    thread = await _create_thread(new_client, subject="agent voice", creator_id="agent-alpha")
    tid = thread["thread_id"]

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread", {"thread_id": tid, "content": "lane report", "from_agent": "lane2-be9379"}
        )
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)
    assert payload["from_kind"] == "agent"
    assert payload["from_agent_id"] == "lane2-be9379"
    assert payload["from_agent_id"] != user_id
    assert payload["attribution_warning"] is None


async def test_from_agent_and_as_user_together_are_refused(mcp_env, db_session):
    new_client, _tk, _uid, _base, _mp = mcp_env
    thread = await _create_thread(new_client, subject="both claims", creator_id="agent-alpha")
    tid = thread["thread_id"]

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "confused", "from_agent": "implementer", "as_user": True},
        )
    assert res.is_error is False, _error_text(res)
    payload = _payload(res)
    assert payload["success"] is False
    assert payload["error"] == "FROM_AGENT_AS_USER_EXCLUSIVE"
    assert await _message_count(db_session, tid) == 0
