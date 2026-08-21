# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
FastMCP HTTP/SSE integration harness (closes ACTION_REQUIRED_AUDIT seq 120).

Exercises the MCP-tool registration boundary end-to-end via the SDK's in-process
transport: real FastMCP server instance, real tool registry, real JSON-RPC over
in-memory streams. Auth middleware is bypassed because the harness connects
directly to the FastMCP server (the same fixture pattern the official MCP
Python SDK uses for its own protocol tests).

The mcp_client fixture yields an async context manager (not a session directly)
so the SDK's anyio task-group setup and teardown stay inside one coroutine
task. Yielding the live ClientSession across pytest-asyncio's fixture
finalization boundary triggers anyio's "exit cancel scope in a different task"
guard.
"""

import json

import pytest


pytestmark = pytest.mark.asyncio


async def test_tools_list_includes_health_check(mcp_client):
    """list_tools() must expose health_check with a well-formed input schema."""
    async with mcp_client as session:
        result = await session.list_tools()

    tool_names = {tool.name for tool in result.tools}
    assert "health_check" in tool_names, f"health_check missing from registered tools: {sorted(tool_names)}"

    health_check_tool = next(tool for tool in result.tools if tool.name == "health_check")
    schema = health_check_tool.input_schema
    assert isinstance(schema, dict), "inputSchema must be a dict"
    assert "properties" in schema, f"inputSchema missing 'properties' key: {schema}"
    assert isinstance(schema["properties"], dict), "inputSchema.properties must be a dict"

    required = schema.get("required", [])
    assert required == [] or required is None, f"health_check should have no required args, got: {required}"


async def test_health_check_round_trip(mcp_client):
    """call_tool('health_check', {}) must round-trip a non-error result with status=healthy."""
    async with mcp_client as session:
        result = await session.call_tool("health_check", {})

    assert result.is_error is False, f"health_check returned an error result: {result}"
    assert result.content, "health_check returned empty content"

    payload = _extract_payload(result)
    assert payload.get("status") == "healthy", f"expected status=healthy, got payload={payload}"
    assert payload.get("server") == "giljo_mcp", f"expected server=giljo_mcp, got payload={payload}"


def _extract_payload(call_tool_result) -> dict:
    """Decode the first text content block from a CallToolResult into a dict."""
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content

    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block (no text field): {first_block!r}")
    return json.loads(text)
