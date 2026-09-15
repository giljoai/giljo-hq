# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from unittest.mock import AsyncMock

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


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def todos_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
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

    tenant_switch = _TenantSwitch(primary_tenant_key)
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_switch
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def test_todos_category_forwards_job_id_through_mcp_boundary(todos_mcp_client, primary_tenant_key, monkeypatch):
    new_client, _switch = todos_mcp_client

    captured_kwargs: dict = {}

    async def fake_get_todos(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "source": "todos",
            "data": {
                "todos": [
                    {"sequence": 0, "content": "Wait for orchestrator", "status": "pending"},
                    {"sequence": 1, "content": "Run pytest suite", "status": "completed"},
                ],
                "total": 2,
            },
            "metadata": {"job_id": kwargs.get("job_id"), "tenant_key": kwargs.get("tenant_key")},
        }

    import sys

    import giljo_mcp.tools.context_tools.fetch_context  # noqa: F401 — force submodule import

    fetch_module = sys.modules["giljo_mcp.tools.context_tools.fetch_context"]

    monkeypatch.setitem(fetch_module.CATEGORY_TOOLS, "todos", AsyncMock(side_effect=fake_get_todos))

    sentinel_job_id = "11111111-1111-1111-1111-111111111111"
    sentinel_product_id = "22222222-2222-2222-2222-222222222222"

    async with new_client() as session:
        result = await session.call_tool(
            "get_context",
            {
                "product_id": sentinel_product_id,
                "categories": ["todos"],
                "job_id": sentinel_job_id,
            },
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert captured_kwargs.get("job_id") == sentinel_job_id, (
        f"INF-5077 wrapper regression: job_id not forwarded. captured={captured_kwargs!r}"
    )
    assert captured_kwargs.get("tenant_key") == primary_tenant_key, (
        f"tenant_key must be injected from session, not forwarded raw. captured={captured_kwargs!r}"
    )
    assert captured_kwargs.get("db_manager") is not None, (
        f"db_manager must be propagated for the read query. captured keys={list(captured_kwargs)!r}"
    )

    assert "todos" in payload.get("categories_returned", []), (
        f"'todos' missing from categories_returned: {payload.get('categories_returned')!r}"
    )
    todos_data = payload.get("data", {}).get("todos", {})
    rows = todos_data.get("todos", [])
    assert len(rows) == 2
    assert rows[0]["content"] == "Wait for orchestrator"
    assert rows[0]["status"] == "pending"
    assert rows[1]["content"] == "Run pytest suite"
    assert rows[1]["status"] == "completed"


async def test_todos_category_without_job_id_returns_empty_marker(todos_mcp_client, primary_tenant_key):
    new_client, _switch = todos_mcp_client

    sentinel_product_id = "22222222-2222-2222-2222-222222222222"

    async with new_client() as session:
        result = await session.call_tool(
            "get_context",
            {
                "product_id": sentinel_product_id,
                "categories": ["todos"],
            },
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert "todos" in payload.get("categories_returned", [])
    todos_data = payload.get("data", {}).get("todos", {})
    assert todos_data == {} or todos_data.get("total", 0) == 0
