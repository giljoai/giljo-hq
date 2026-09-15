# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from api.endpoints.mcp_sdk_server import mcp


@pytest.fixture(scope="module")
def registered_tools():
    import asyncio

    return asyncio.run(mcp.list_tools())


def test_registry_is_non_empty(registered_tools):
    assert len(registered_tools) > 0, "FastMCP tool registry is empty"


def test_every_tool_has_output_schema(registered_tools):
    missing = [t.name for t in registered_tools if t.output_schema is None]
    assert not missing, (
        f"Tools missing outputSchema: {missing}. "
        "Attach by adding a typed return annotation to the @mcp.tool function "
        "(e.g. `-> dict[str, Any]` for free-form dicts, or a Pydantic model)."
    )


def test_every_output_schema_is_object_typed(registered_tools):
    bad: list[tuple[str, object]] = []
    for tool in registered_tools:
        schema = tool.output_schema
        if schema is None:
            continue
        if schema.get("type") != "object":
            bad.append((tool.name, schema.get("type")))
    assert not bad, f"Tools whose outputSchema.type is not 'object': {bad}"


def test_output_schema_is_serializable(registered_tools):
    import json

    for tool in registered_tools:
        if tool.output_schema is None:
            continue
        json.dumps(tool.output_schema)
