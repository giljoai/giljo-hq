# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.models.products import Product
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

_CALLS = [
    ("list_projects", {}),
    ("list_tasks", {}),
    ("get_context", {"categories": ["tech_stack"]}),
    ("get_roadmap", {}),
]


def _text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


@pytest_asyncio.fixture
async def call_as(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _call(tenant_key: str, tool: str, args: dict):
        monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as s:
            return await s.call_tool(tool, args)

    try:
        yield _call
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


@pytest.mark.parametrize(("tool", "args"), _CALLS)
async def test_zero_products_is_told_to_create_a_product(call_as, tool, args):
    tenant_key = TenantManager.generate_tenant_key()
    result = await call_as(tenant_key, tool, args)
    text = _text(result)
    assert result.is_error is True, text
    assert "create_product" in text, text
    assert "dashboard action" not in text, text
    assert "set a default product" not in text, text


@pytest.mark.parametrize(("tool", "args"), _CALLS)
async def test_products_exist_but_none_default_keeps_todays_text(call_as, db_manager, tool, args):
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(id=str(uuid.uuid4()), tenant_key=tenant_key, name="Parked", is_active=False, is_default=False)
        )
        await session.commit()
    try:
        result = await call_as(tenant_key, tool, args)
    finally:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
            await session.commit()
    text = _text(result)
    assert result.is_error is True, text
    assert "create_product" not in text, text
