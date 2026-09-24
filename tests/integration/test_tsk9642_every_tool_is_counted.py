# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
from datetime import date

import pytest
import pytest_asyncio

from api.endpoints.mcp_tools._call_metrics import record_untenanted_tool_call
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_COUNTING_CALLS = ("_call_tool(", "record_untenanted_tool_call(")


def _registered_tools():
    from api.endpoints.mcp_tools import mcp

    return mcp._tool_manager.list_tools()


def _uncounted(tools) -> list[str]:
    missing = []
    for tool in tools:
        source = inspect.getsource(tool.fn)
        if not any(call in source for call in _COUNTING_CALLS):
            missing.append(tool.name)
    return missing


def test_every_registered_tool_is_counted_somewhere() -> None:
    tools = _registered_tools()
    assert tools, "the tool registry came back empty -- the guard would pass vacuously"

    missing = _uncounted(tools)
    assert not missing, (
        f"{len(missing)} registered MCP tool(s) are never counted: {sorted(missing)}.\n"
        "A tool that neither dispatches through _call_tool nor calls "
        "record_untenanted_tool_call reads as zero calls forever, and zero calls is "
        "what a later pass deletes a tool on. If your handler answers without a "
        "tenant, call record_untenanted_tool_call(ctx, '<tool_name>')."
    )


def test_the_guard_can_actually_fire() -> None:

    class _FakeTool:
        name = "uncounted_tool"

        @staticmethod
        def fn():
            return {"status": "healthy"}

    assert _uncounted([_FakeTool()]) == ["uncounted_tool"]

    class _CountedTool:
        name = "counted_tool"

        @staticmethod
        def fn(ctx=None):
            record_untenanted_tool_call(ctx, "counted_tool")

    assert _uncounted([_CountedTool()]) == []




class _FakeAppState:
    def __init__(self) -> None:
        self.db_manager = None
        self.websocket_manager = None
        self.mcp_call_count: dict[str, int] = {}
        self.mcp_tool_call_count: dict[tuple[str, str, date], int] = {}
        self.tool_accessor = object()


@pytest_asyncio.fixture
async def counting_client(monkeypatch):
    from api import app_state as app_state_module
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base

    fake_state = _FakeAppState()
    monkeypatch.setattr(app_state_module, "state", fake_state)

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_set_tenant_context", lambda tk: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    yield _new_client, fake_state, tenant_key


@pytest.mark.parametrize("tool_name", ["health_check", "get_giljo_guide"])
async def test_tenant_independent_tools_are_counted_over_the_transport(counting_client, tool_name):
    new_client, state, tenant_key = counting_client

    async with new_client() as session:
        result = await session.call_tool(tool_name, {})

    assert result.is_error is False, "\n".join(b.text for b in result.content if getattr(b, "text", None))

    counted = {(tool, count) for (_tenant, tool, _day), count in state.mcp_tool_call_count.items()}
    assert counted == {(tool_name, 1)}, f"{tool_name} was not counted at TOOL grain, got {counted}"
    assert state.mcp_call_count == {tenant_key: 1}, (
        f"{tool_name} was not counted in the per-tenant total, got {state.mcp_call_count}"
    )


async def test_repeat_calls_accumulate_under_one_key(counting_client):
    new_client, state, _tenant_key = counting_client

    async with new_client() as session:
        await session.call_tool("health_check", {})
        await session.call_tool("health_check", {})

    counts = list(state.mcp_tool_call_count.values())
    assert counts == [2], f"expected one key holding 2, got {state.mcp_tool_call_count}"


async def test_a_call_with_no_resolvable_tenant_still_answers(monkeypatch):
    from api import app_state as app_state_module
    from api.endpoints.mcp_tools._setup_tools import health_check

    fake_state = _FakeAppState()
    monkeypatch.setattr(app_state_module, "state", fake_state)

    result = await health_check(ctx=None)

    assert result["status"] == "healthy", "the probe's own answer must not depend on the counter"
    assert fake_state.mcp_tool_call_count == {}
    assert fake_state.mcp_call_count == {}
