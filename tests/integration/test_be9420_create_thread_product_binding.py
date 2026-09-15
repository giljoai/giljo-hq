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
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, TaxonomyType
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
async def thread_product_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    foreign_tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]

    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    db_session.add(User(id=str(uuid4()), tenant_key=tenant_key, username=f"be9420_{suffix}"))
    own_product = Product(id=str(uuid4()), tenant_key=tenant_key, name=f"BE9420 Own {suffix}")
    foreign_product = Product(id=str(uuid4()), tenant_key=foreign_tenant_key, name=f"BE9420 Foreign {suffix}")
    db_session.add(own_product)
    db_session.add(foreign_product)
    await db_session.flush()
    foreign_project = Project(
        id=str(uuid4()),
        tenant_key=foreign_tenant_key,
        product_id=foreign_product.id,
        name=f"BE9420 Foreign Project {suffix}",
        description="BE-9420 cross-tenant guard fixture",
        mission="Exists only so a real foreign project id can be offered.",
    )
    db_session.add(foreign_project)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, own_product.id, foreign_product.id, foreign_project.id
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _thread_row(db_session, tenant_key: str, thread_id: str) -> CommThread:
    with tenant_session_context(db_session, tenant_key):
        return (await db_session.execute(select(CommThread).where(CommThread.id == thread_id))).scalar_one()


async def test_product_id_is_on_the_agent_facing_tool_surface(thread_product_client):
    new_client, _tk, _own, _foreign, _fproj = thread_product_client

    async with new_client() as session:
        listed = await session.list_tools()

    create_thread = next(t for t in listed.tools if t.name == "create_thread")
    assert "product_id" in create_thread.input_schema.get("properties", {}), (
        "create_thread no longer advertises product_id, so an agent cannot bind a "
        "thread to a product at all (BE-9420 item 2)."
    )


async def test_a_supplied_product_id_binds_the_thread(thread_product_client, db_session):
    new_client, tenant_key, own_product_id, _foreign, _fproj = thread_product_client

    async with new_client() as session:
        result = await session.call_tool(
            "create_thread",
            {"subject": "bound thread", "creator_id": "agent-alpha", "product_id": own_product_id},
        )
    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert payload["product_id"] == own_product_id
    row = await _thread_row(db_session, tenant_key, payload["thread_id"])
    assert row.product_id == own_product_id, (
        "create_thread accepted product_id and dropped it before the write -- the "
        "declared-but-absorbed shape BE-9415 found on update_task."
    )


async def test_omitting_product_id_resolves_to_the_tenants_own_product(thread_product_client, db_session):
    new_client, tenant_key, own_product_id, _foreign, _fproj = thread_product_client

    async with new_client() as session:
        result = await session.call_tool("create_thread", {"subject": "standalone", "creator_id": "agent-alpha"})
    assert result.is_error is False, _error_text(result)

    row = await _thread_row(db_session, tenant_key, _payload(result)["thread_id"])
    assert row.product_id == own_product_id, (
        "a thread created without product_id must resolve to the tenant's own "
        "product (FE-9530 ruling 1), never stay unbound and never bind to another "
        "tenant's product"
    )


async def test_omitting_product_id_on_a_zero_product_tenant_stays_unbound(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    db_session.add(User(id=str(uuid4()), tenant_key=tenant_key, username=f"be9420_zero_{suffix}"))
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    try:
        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
            result = await session.call_tool(
                "create_thread", {"subject": "first ever thread", "creator_id": "agent-alpha"}
            )
        assert result.is_error is False, _error_text(result)
        row = await _thread_row(db_session, tenant_key, _payload(result)["thread_id"])
        assert row.product_id is None
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def test_another_tenants_product_id_cannot_bind(thread_product_client, db_session):
    new_client, tenant_key, _own, foreign_product_id, _fproj = thread_product_client

    async with new_client() as session:
        result = await session.call_tool(
            "create_thread",
            {"subject": "cross tenant", "creator_id": "agent-alpha", "product_id": foreign_product_id},
        )

    if result.is_error:
        return

    row = await _thread_row(db_session, tenant_key, _payload(result)["thread_id"])
    assert row.tenant_key == tenant_key
    assert row.product_id != foreign_product_id, (
        f"create_thread stored a link from tenant {tenant_key}'s thread to a product "
        f"owned by another tenant ({foreign_product_id}). The FK is satisfied, which "
        "is why nothing raised -- but the row is a cross-tenant reference."
    )


async def test_another_tenants_project_id_cannot_bind(thread_product_client, db_session):
    new_client, tenant_key, _own, _fprod, foreign_project_id = thread_product_client

    async with new_client() as session:
        result = await session.call_tool(
            "create_thread",
            {"subject": "cross tenant project", "creator_id": "agent-alpha", "project_id": foreign_project_id},
        )

    if result.is_error:
        return

    row = await _thread_row(db_session, tenant_key, _payload(result)["thread_id"])
    assert row.project_id != foreign_project_id, (
        f"create_thread anchored tenant {tenant_key}'s thread to a project owned by "
        f"another tenant ({foreign_project_id})."
    )
