# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_SYNTHETIC_TOOL_NAME = "sec9423_synthetic_unmapped_tool"
_MAPPED_BUT_UNREGISTERED = "sec9423_mapped_but_never_registered"

_REFUSAL_FRAGMENT = "no authorization scope mapping"

_GATE_NAME = "_scope_gate"

_SHAPE_MOVED = (
    "SEC-9423: the MCP SDK no longer exposes the authorization gate at its known "
    "installation point, so SEC-9126's fail-closed gate can no longer be located. "
    "RE-POINT the resolver below at the new installation point -- do NOT delete or skip "
    "these tests, and do NOT assume the gate is still installed. The invariant they pin "
    "(a registered tool with no TOOL_SCOPES entry is never advertised and never "
    "dispatched) is unchanged by any SDK shape change. Detail: "
)


async def _synthetic_noop() -> dict:
    return {"sec9423_synthetic": True}


class _Ctx:

    def __init__(self, method: str, params: dict | None = None):
        self.method = method
        self.params = params
        self.request = None


def _installed_gate():
    from api.endpoints.mcp_sdk_server import mcp

    chain = getattr(mcp, "middleware", None)
    if chain is None:
        pytest.fail(f"{_SHAPE_MOVED}MCPServer exposes no `middleware` chain.")
    for entry in chain:
        if getattr(entry, "__name__", "") == _GATE_NAME:
            return entry
    installed = [getattr(e, "__name__", type(e).__name__) for e in chain]
    pytest.fail(f"{_SHAPE_MOVED}no `{_GATE_NAME}` in the installed middleware chain: {installed}.")


async def _unfiltered_list_result() -> dict:
    from api.endpoints.mcp_sdk_server import mcp

    tools = await mcp.list_tools()
    return {"tools": [t.model_dump(by_alias=True, exclude_none=True) for t in tools]}


def _advertised(result) -> set[str]:
    return {tool["name"] for tool in result["tools"]}


def _error_text(result) -> str:
    return "\n".join(getattr(block, "text", "") for block in result.content)


@pytest_asyncio.fixture
async def unmapped_tool():
    from api.endpoints.mcp_sdk_server import mcp

    mcp._tool_manager.add_tool(_synthetic_noop, name=_SYNTHETIC_TOOL_NAME)
    try:
        yield _SYNTHETIC_TOOL_NAME
    finally:
        mcp._tool_manager.remove_tool(_SYNTHETIC_TOOL_NAME)




class TestOverwriteTookEffectAtTheDispatchTable:
    @pytest.mark.asyncio
    async def test_installed_list_handler_applies_the_fail_closed_filter(self, unmapped_tool):
        result = await _installed_gate()(_Ctx("tools/list"), lambda _ctx: _unfiltered_list_result())

        advertised = _advertised(result)
        assert advertised, "the installed gate advertised nothing at all; the roster is empty"
        assert unmapped_tool not in advertised, (
            "the gate INSTALLED on the SDK server advertised a registered tool with no "
            "TOOL_SCOPES entry. SEC-9126's authorization gate is not in effect and "
            "tools/list has reverted to unfiltered."
        )

    @pytest.mark.asyncio
    async def test_installed_call_handler_applies_the_fail_closed_gate(self, unmapped_tool):
        reached = False

        async def call_next(_ctx):
            nonlocal reached
            reached = True
            return {}

        result = await _installed_gate()(_Ctx("tools/call", {"name": unmapped_tool, "arguments": {}}), call_next)

        assert not reached, (
            "the gate INSTALLED on the SDK server passed a registered tool with no "
            "TOOL_SCOPES entry through to the handler. SEC-9126's authorization gate is "
            "not in effect and tools/call has reverted to ungated."
        )
        assert result.is_error, "the refusal must carry is_error, i.e. the 1.28.1 wire shape"
        assert _REFUSAL_FRAGMENT in _error_text(result)

    @pytest.mark.asyncio
    async def test_unregistered_name_still_gets_the_sdk_error(self, unmapped_tool):
        reached = False

        async def call_next(_ctx):
            nonlocal reached
            reached = True
            return {}

        await _installed_gate()(
            _Ctx("tools/call", {"name": "sec9423_never_registered_zzz", "arguments": {}}), call_next
        )

        assert reached, "an unregistered name must fall through to the SDK, not be claimed by the gate"




class TestTheseAssertionsCanFail:

    @staticmethod
    def _remove_gate():
        from api.endpoints.mcp_sdk_server import mcp

        gate = _installed_gate()
        index = mcp.middleware.index(gate)
        mcp.middleware.remove(gate)
        return lambda: mcp.middleware.insert(index, gate)

    @pytest.mark.asyncio
    async def test_sdk_default_list_handler_would_advertise_the_unmapped_tool(self, unmapped_tool):
        from api.endpoints import mcp_sdk_server

        restore = self._remove_gate()
        try:
            async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
                result = await session.list_tools()
            assert unmapped_tool in {tool.name for tool in result.tools}, (
                "negative control did not reproduce the fail-open posture: the ungated "
                "server filtered the unmapped tool anyway. Suspect this control, not the "
                "production gate -- until it is explained, the layer-1 pass above proves nothing."
            )
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_sdk_default_call_handler_would_execute_the_unmapped_tool(self, unmapped_tool):
        from api.endpoints import mcp_sdk_server

        restore = self._remove_gate()
        try:
            async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
                result = await session.call_tool(unmapped_tool, {})
            assert not result.is_error, (
                "negative control did not reproduce the fail-open posture: the ungated "
                "server refused the unmapped tool anyway. Suspect this control, not the "
                "production gate -- until it is explained, the layer-1 pass above proves nothing."
            )
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_the_gate_is_restored_after_the_controls(self, unmapped_tool):
        result = await _installed_gate()(_Ctx("tools/list"), lambda _ctx: _unfiltered_list_result())
        assert unmapped_tool not in _advertised(result), (
            "a negative control leaked an ungated server back into the middleware chain"
        )




class TestInvariantThroughTheRealDispatchPath:

    @pytest.mark.asyncio
    async def test_unmapped_tool_is_not_advertised(self, unmapped_tool):
        from api.endpoints import mcp_sdk_server

        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
            result = await session.list_tools()

        assert unmapped_tool not in {tool.name for tool in result.tools}

    @pytest.mark.asyncio
    async def test_unmapped_tool_is_refused_at_dispatch(self, unmapped_tool):
        from api.endpoints import mcp_sdk_server

        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
            result = await session.call_tool(unmapped_tool, {})

        assert result.is_error
        assert _REFUSAL_FRAGMENT in "\n".join(getattr(block, "text", "") for block in result.content)




class TestBootAssertRejectsBothDirections:
    def test_mapped_but_unregistered_tool_aborts_boot(self, monkeypatch):
        from api.endpoints import mcp_sdk_server
        from api.endpoints.mcp_tools import _base

        monkeypatch.setitem(_base.TOOL_SCOPES, _MAPPED_BUT_UNREGISTERED, _base.SCOPE_READ)

        with pytest.raises(RuntimeError, match=_MAPPED_BUT_UNREGISTERED):
            mcp_sdk_server._assert_tool_scope_completeness()

    def test_registered_but_unmapped_tool_aborts_boot(self, monkeypatch):
        from api.endpoints import mcp_sdk_server
        from api.endpoints.mcp_tools import _base

        monkeypatch.delitem(_base.TOOL_SCOPES, "health_check")

        with pytest.raises(RuntimeError, match="health_check"):
            mcp_sdk_server._assert_tool_scope_completeness()

    def test_clean_registry_is_silent(self):
        from api.endpoints import mcp_sdk_server

        mcp_sdk_server._assert_tool_scope_completeness()
