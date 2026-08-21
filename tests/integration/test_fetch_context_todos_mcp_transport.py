# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-boundary regression test for INF-5077.

Exercises the new `todos` category on `fetch_context` through the @mcp.tool
wrapper in api/endpoints/mcp_sdk_server.py — NOT the underlying service
directly. Per CLAUDE.md "Regression test at the failing layer" rule:
bug-fix projects whose fix lives at the transport boundary need a test that
travels through the boundary. BE-5042 shipped broken because service-only
coverage missed a FastMCP wrapper bug; this test guards against the
equivalent failure for INF-5077 — the wrapper must accept `job_id` as a tool
argument AND forward it through `_call_tool` → ToolAccessor.fetch_context →
the internal fetch_context dispatch → get_todos.

The transactional test-session pattern (single connection, rolled back at
the end) prevents a real-DB end-to-end test here: `get_todos` opens its own
session via db_manager which can't see seeded rows on the test connection.
We instead patch `get_todos` at the module boundary and assert on the
kwargs it was invoked with — that is exactly the transport-wrapper failure
mode from BE-5042 (wrapper accepts a parameter but never forwards it).

Two regressions are guarded:
1. The wrapper must accept `job_id` as a tool argument and forward it.
2. The internal fetch_context must dispatch to get_todos with the
   forwarded job_id + tenant_key.
"""

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
    """Yield (new_client, tenant_switch) for in-memory FastMCP transport.

    Same pattern as test_progress_workflow_status_mcp_transport.py.
    """
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
    # BE-6042d: _resolve_tenant/_resolve_user_id moved to mcp_tools._base (the
    # _call_tool call site reads them there). Patch _base, not mcp_sdk_server.
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
    """The @mcp.tool wrapper must accept `job_id` and forward it all the way
    through to `get_todos`. Patches `get_todos` at the module the dispatcher
    imports from, captures kwargs, and asserts on them.

    This is precisely the BE-5042 failure mode: wrapper accepts a parameter
    but loses it before the underlying service is invoked.
    """
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

    # Patch at the dispatcher's import site — that's the binding the
    # CATEGORY_TOOLS dict resolves through. `import as` resolves to the
    # function (package re-export shadows the submodule); pull the module
    # explicitly from sys.modules. Force-import first to guarantee presence.
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

    # Regression #1: wrapper forwarded job_id and tenant_key into get_todos
    assert captured_kwargs.get("job_id") == sentinel_job_id, (
        f"INF-5077 wrapper regression: job_id not forwarded. captured={captured_kwargs!r}"
    )
    assert captured_kwargs.get("tenant_key") == primary_tenant_key, (
        f"tenant_key must be injected from session, not forwarded raw. captured={captured_kwargs!r}"
    )
    assert captured_kwargs.get("db_manager") is not None, (
        f"db_manager must be propagated for the read query. captured keys={list(captured_kwargs)!r}"
    )

    # Regression #2: full content shape round-trips through the boundary
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
    """fetch_context(categories=['todos']) without job_id must surface a
    descriptive empty marker rather than silently crashing the batch.
    The dispatcher's job_id guard in _fetch_category should fire first,
    so get_todos is NEVER invoked when job_id is absent.
    """
    new_client, _switch = todos_mcp_client

    sentinel_product_id = "22222222-2222-2222-2222-222222222222"

    async with new_client() as session:
        result = await session.call_tool(
            "get_context",
            {
                "product_id": sentinel_product_id,
                "categories": ["todos"],
                # no job_id intentionally
            },
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    # 'todos' still appears (uniform contract — empty payload != silent drop)
    assert "todos" in payload.get("categories_returned", [])
    todos_data = payload.get("data", {}).get("todos", {})
    # _fetch_category short-circuits with an empty dict payload when job_id is missing
    assert todos_data == {} or todos_data.get("total", 0) == 0
