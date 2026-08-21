# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Regression tests for API-0025 — every FastMCP tool descriptor MUST advertise
an ``outputSchema`` with ``type == "object"``.

Per MCP spec (2025-06-18) `outputSchema` is optional-but-recommended for tools
that return structured data. Without it, MCP clients (e.g. ChatGPT's connector)
emit the hint: "It is recommended you add an outputSchema for each tool so the
model can better understand the tool results."

Failing-layer discipline (per CLAUDE.md): the bug lives at the MCP transport /
tool-registry layer — service-layer return-shape tests are not sufficient.
This test enumerates the live FastMCP registry to catch new tools that ship
without an outputSchema. Hardcoding a tool list would defeat the regression
guard.
"""

from __future__ import annotations

import pytest

from api.endpoints.mcp_sdk_server import mcp


@pytest.fixture(scope="module")
def registered_tools():
    """Return every tool registered with the live FastMCP instance."""
    import asyncio

    return asyncio.run(mcp.list_tools())


def test_registry_is_non_empty(registered_tools):
    """Sanity guard: registry must not be empty (would falsely pass the loops)."""
    assert len(registered_tools) > 0, "FastMCP tool registry is empty"


def test_every_tool_has_output_schema(registered_tools):
    """Every advertised tool MUST carry an outputSchema (MCP spec recommendation)."""
    missing = [t.name for t in registered_tools if t.output_schema is None]
    assert not missing, (
        f"Tools missing outputSchema: {missing}. "
        "Attach by adding a typed return annotation to the @mcp.tool function "
        "(e.g. `-> dict[str, Any]` for free-form dicts, or a Pydantic model)."
    )


def test_every_output_schema_is_object_typed(registered_tools):
    """outputSchema.type MUST equal 'object' — MCP clients expect a JSON object."""
    bad: list[tuple[str, object]] = []
    for tool in registered_tools:
        schema = tool.output_schema
        if schema is None:
            continue
        if schema.get("type") != "object":
            bad.append((tool.name, schema.get("type")))
    assert not bad, f"Tools whose outputSchema.type is not 'object': {bad}"


def test_output_schema_is_serializable(registered_tools):
    """Schemas must be JSON-serializable so the SDK can ship them over the wire."""
    import json

    for tool in registered_tools:
        if tool.output_schema is None:
            continue
        json.dumps(tool.output_schema)
