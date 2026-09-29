# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def context_error_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: primary_tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def test_category_failure_reaches_the_wire_as_a_fixed_code(context_error_mcp_client, primary_tenant_key):
    new_client = context_error_mcp_client

    raw = RuntimeError(
        "(psycopg.errors.UndefinedColumn) column products.bogus does not exist\n"
        "[SQL: SELECT products.bogus FROM products WHERE products.tenant_key = %(tenant_key)s]\n"
        f"[parameters: {{'tenant_key': '{primary_tenant_key}'}}]"
    )

    import sys

    import giljo_mcp.tools.context_tools.fetch_context  # noqa: F401 -- force submodule import

    fetch_module = sys.modules["giljo_mcp.tools.context_tools.fetch_context"]

    async def _fake_get_products(**kwargs):
        raise raw

    with patch.dict(fetch_module.CATEGORY_TOOLS, {"products": AsyncMock(side_effect=_fake_get_products)}):
        sentinel_product_id = "33333333-3333-3333-3333-333333333333"

        async with new_client() as session:
            result = await session.call_tool(
                "get_context",
                {"product_id": sentinel_product_id, "categories": ["products"]},
            )
            assert result.is_error is False, _error_text(result)
            payload = _payload(result)

    errors = payload.get("errors", [])
    assert [e["category"] for e in errors] == ["products"]
    reported = errors[0]["error"]
    assert "[SQL:" not in reported, f"raw SQL text reached the wire: {reported!r}"
    assert primary_tenant_key not in reported, f"the tenant_key bind value reached the wire: {reported!r}"
    assert reported == "CATEGORY_FETCH_FAILED"
