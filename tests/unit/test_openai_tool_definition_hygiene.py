# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

import jsonschema
import pytest

from api.endpoints.mcp_sdk_server import mcp


_SHOUTED = re.compile(r"\b(?:ASK|MUST|NEVER|STOP|ALWAYS|CRITICAL|IMPORTANT|WARNING|MANDATORY|REQUIRED|DO NOT|DON'T)\b")


def _tools():
    return list(mcp._tool_manager.list_tools())


def _properties():
    for tool in _tools():
        for name, schema in (tool.parameters.get("properties") or {}).items():
            yield tool, name, schema


def _default_is_valid(tool, schema) -> bool:
    probe = {"type": "object", "properties": {"v": schema}, "$defs": tool.parameters.get("$defs", {})}
    try:
        jsonschema.validate({"v": schema["default"]}, probe)
    except jsonschema.ValidationError:
        return False
    return True


def test_registry_is_populated():
    assert _tools()


def test_every_schema_default_validates_against_its_own_schema():
    bad = sorted(
        f"{tool.name}.{name}: default={schema['default']!r}"
        for tool, name, schema in _properties()
        if "default" in schema and not _default_is_valid(tool, schema)
    )
    assert not bad, f"defaults outside their own schema: {bad}"


def test_no_enum_advertises_a_default_that_is_not_a_choice():
    bad = sorted(
        f"{tool.name}.{name}"
        for tool, name, schema in _properties()
        if "enum" in schema and "default" in schema and schema["default"] not in schema["enum"]
    )
    assert not bad, f"enum default not in enum: {bad}"


def test_no_shouted_directives_in_descriptions():
    hits = []
    for tool in _tools():
        for m in _SHOUTED.finditer(tool.description or ""):
            hits.append(f"{tool.name} description: {m.group(0)}")
    for tool, name, schema in _properties():
        for m in _SHOUTED.finditer(schema.get("description", "")):
            hits.append(f"{tool.name}.{name}: {m.group(0)}")
    assert not hits, f"shouted directives: {sorted(hits)}"


def test_every_input_property_has_a_description():
    missing = sorted(f"{tool.name}.{name}" for tool, name, schema in _properties() if not schema.get("description"))
    assert not missing, f"properties without a description: {missing}"


@pytest.mark.parametrize("tool_name", ["stage_project", "link_projects"])
def test_mode_enums_advertise_only_the_two_real_choices(tool_name):
    tool = next(t for t in _tools() if t.name == tool_name)
    prop = "mode" if tool_name == "stage_project" else "execution_mode"
    schema = tool.parameters["properties"][prop]
    enums = schema.get("enum") or next(s["enum"] for s in schema["anyOf"] if "enum" in s)
    assert sorted(enums) == ["multi_terminal", "subagent"]
