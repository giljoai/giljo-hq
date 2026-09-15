# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from api.endpoints.mcp_sdk_server import mcp


def _live_tool(name: str):
    for tool in mcp._tool_manager.list_tools():
        if tool.name == name:
            return tool
    raise AssertionError(f"{name} not registered on the live FastMCP surface")


def _limit_schema(tool_name: str) -> dict:
    tool = _live_tool(tool_name)
    return tool.parameters["properties"]["limit"]


class TestListProjectsLimitDescriptionMatchesItsOwnSchema:
    def test_description_does_not_claim_clamping_when_the_schema_rejects(self):
        schema = _limit_schema("list_projects")

        assert "maximum" in schema, "expected list_projects.limit to carry a le= ceiling"

        description = schema["description"].lower()
        assert "are clamped" not in description, (
            "list_projects.limit description claims values above the max ARE clamped "
            "while the schema's own maximum= rejects them at the pydantic validation "
            "boundary -- the sentence is backwards"
        )
        assert "rejected" in description, (
            "list_projects.limit description should say values above the max are "
            "rejected, matching what the schema's maximum= actually does"
        )

    def test_both_sides_guard_an_over_max_limit_is_genuinely_refused(self):
        import pytest
        from pydantic import ValidationError

        tool = _live_tool("list_projects")
        schema_max = tool.parameters["properties"]["limit"]["maximum"]
        over_max = schema_max + 1

        with pytest.raises(ValidationError, match="limit"):
            tool.fn_metadata.validate_arguments({"limit": over_max})


class TestLimitConventionIsAlignedAcrossSiblingTools:
    def test_list_projects_and_list_tasks_agree_on_ge_zero_default_semantics(self):
        projects_limit = _limit_schema("list_projects")
        tasks_limit = _limit_schema("list_tasks")

        assert projects_limit["minimum"] == 0, "list_projects.limit must stay ge=0 (0 = use the default)"
        assert tasks_limit["minimum"] == 0, (
            f"list_tasks.limit is ge={tasks_limit['minimum']}, not ge=0 -- the two sibling "
            "list tools must use ONE convention for the same parameter"
        )
        assert tasks_limit["default"] == 0, (
            f"list_tasks.limit defaults to {tasks_limit['default']}, not 0 -- with ge=0 now "
            "accepted, 0 must mean 'use the default', matching list_projects"
        )
