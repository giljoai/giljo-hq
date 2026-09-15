# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json

import pytest

from giljo_mcp import branding


pytestmark = pytest.mark.asyncio


async def test_tools_list_includes_health_check(mcp_client):
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
    async with mcp_client as session:
        result = await session.call_tool("health_check", {})

    assert result.is_error is False, f"health_check returned an error result: {result}"
    assert result.content, "health_check returned empty content"

    payload = _extract_payload(result)
    assert payload.get("status") == "healthy", f"expected status=healthy, got payload={payload}"
    assert payload.get("server") == branding.MCP_ALIAS, f"expected server={branding.MCP_ALIAS}, got payload={payload}"


def _extract_payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content

    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block (no text field): {first_block!r}")
    return json.loads(text)
