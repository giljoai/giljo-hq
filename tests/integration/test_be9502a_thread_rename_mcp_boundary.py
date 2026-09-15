# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.comm import CommThread
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
async def rename_mcp_client(db_manager, db_session, monkeypatch):
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


async def _create_thread(new_client, subject: str) -> str:
    async with new_client() as s:
        res = await s.call_tool("create_thread", {"subject": subject, "creator_id": "alpha"})
    assert res.is_error is False, _error_text(res)
    return _payload(res)["thread_id"]


async def test_rename_to_lands_with_the_post(rename_mcp_client):
    new_client, _tenant_key, session = rename_mcp_client
    tid = await _create_thread(new_client, "original subject")

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "renaming this thread", "from_agent": "alpha", "rename_to": "new subject"},
        )
    assert res.is_error is False, _error_text(res)

    row = (await session.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
    assert row.subject == "new subject"

    posted = (
        await session.execute(
            select(Message).where(Message.thread_id == tid, Message.content == "renaming this thread")
        )
    ).scalar_one_or_none()
    assert posted is not None, "the message must still post alongside a successful rename"


async def test_rename_omitted_leaves_the_subject_untouched(rename_mcp_client):
    new_client, _tenant_key, session = rename_mcp_client
    tid = await _create_thread(new_client, "untouched subject")

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "just a message", "from_agent": "alpha"},
        )
    assert res.is_error is False, _error_text(res)

    row = (await session.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
    assert row.subject == "untouched subject"


async def test_rename_on_a_project_bound_thread_is_refused_and_posts_nothing(rename_mcp_client):
    from giljo_mcp.models.products import Product
    from giljo_mcp.models.projects import Project

    new_client, tenant_key, session = rename_mcp_client

    product = Product(id=str(uuid4()), name="BE-9502a rename product", tenant_key=tenant_key, is_active=False)
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9502a rename project",
        description="rename refusal fixture",
        mission="rename refusal fixture",
        status="active",
    )
    session.add(project)
    await session.flush()
    await session.commit()

    from api import app_state

    bound = await app_state.state.tool_accessor._comm_thread_service.resolve_or_create_bound_thread(
        project_id=project.id, tenant_key=tenant_key
    )
    tid = bound["thread_id"]
    original_subject = bound["subject"]

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {
                "thread_id": tid,
                "content": "should not post",
                "from_agent": "alpha",
                "rename_to": "hijacked subject",
            },
        )
    assert res.is_error is True
    assert "project" in _error_text(res).lower()

    row = (await session.execute(select(CommThread).where(CommThread.id == tid))).scalar_one()
    assert row.subject == original_subject

    posted = (await session.execute(select(Message).where(Message.thread_id == tid))).scalar_one_or_none()
    assert posted is None, "a refused rename must not leave the message posted"
