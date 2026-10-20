# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import MCPServerError, ToolError
from pydantic import BaseModel

from api.endpoints.mcp_tools import mcp as shared_mcp
from api.endpoints.mcp_tools._tool_error_surface import (
    _WRAPPED_MARKER,
    is_anticipated_rejection,
    preserve_tool_rejections,
)
from giljo_mcp.exceptions import BaseGiljoError, ResourceNotFoundError, ValidationError


def test_every_registered_tool_is_wrapped():
    tools = shared_mcp._tool_manager.list_tools()
    assert tools, "no tools registered on the shared MCP server"
    unwrapped = [t.name for t in tools if not getattr(t.fn, _WRAPPED_MARKER, False)]
    assert unwrapped == []


def test_wrapping_is_idempotent():
    before = {t.name: t.fn for t in shared_mcp._tool_manager.list_tools()}
    preserve_tool_rejections(shared_mcp._tool_manager.list_tools())
    after = {t.name: t.fn for t in shared_mcp._tool_manager.list_tools()}
    assert before == after


class _Model(BaseModel):
    n: int


def _pydantic_error() -> Exception:
    try:
        _Model(n="not-an-int")
    except Exception as exc:  # noqa: BLE001 - capture the real pydantic error type
        return exc
    raise AssertionError("expected a validation error")


@pytest.mark.parametrize(
    "exc",
    [
        MCPServerError("sanitized"),
        ValidationError("bad field"),
        ResourceNotFoundError("missing"),
        ValueError("clean value error"),
        TypeError("clean type error"),
        _pydantic_error(),
    ],
    ids=lambda e: type(e).__name__,
)
def test_anticipated_rejections_keep_their_text(exc):
    assert is_anticipated_rejection(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ToolError("already a ToolError"),
        RuntimeError("internal detail"),
        KeyError("x"),
        BaseGiljoError("server-side"),
        ValueError("boom [SQL: SELECT 1] [parameters: (1,)]"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_other_exceptions_are_left_to_the_sdk(exc):
    assert is_anticipated_rejection(exc) is False


@pytest.mark.asyncio
async def test_wire_text_matches_pre_2_1_contract():
    server = MCPServer("probe")

    @server.tool()
    async def rejects() -> dict:
        raise ValidationError("status must be one of: a, b")

    @server.tool()
    async def sanitized() -> dict:
        raise MCPServerError("The server hit an unexpected internal error handling this request.")

    @server.tool()
    async def crashes() -> dict:
        raise RuntimeError("secret internals")

    preserve_tool_rejections(server._tool_manager.list_tools())

    async with Client(server) as client:
        r = await client.call_tool("rejects", {})
        assert r.is_error
        assert r.content[0].text == "Error executing tool rejects: status must be one of: a, b"

        r = await client.call_tool("sanitized", {})
        assert r.is_error
        assert r.content[0].text == (
            "Error executing tool sanitized: The server hit an unexpected internal error handling this request."
        )

        r = await client.call_tool("crashes", {})
        assert r.is_error
        assert r.content[0].text == "Error executing tool crashes"
