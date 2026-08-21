# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9468 follow-ups -- the two defects that live in the @mcp.tool wrapper schema
itself, not in a service function, so they can only be pinned by reading the REAL
schema FastMCP hands to a connected client (``mcp._tool_manager.list_tools()``), not by
calling a Python function directly.

Fix 2 -- ``list_projects``'s ``limit`` Field carries ``le=LIST_PROJECTS_LIMIT_MAX``,
which makes pydantic REJECT (not clamp) a value above the max before the handler is ever
reached -- confirmed separately in ``tests/services/test_be9468_project_service_list_bounds.py``,
whose ``resolve_row_limit`` genuinely clamps but is unreachable from this boundary for an
over-max value. The advertised description nonetheless says "Values above the max are
clamped, not rejected" -- exactly backwards. An agent that trusts the sentence passes 1000
expecting 500 rows back and gets a bare tool error instead. This module asserts the live
schema's description does not make that claim, and separately (as a both-sides guard)
that the real transport does in fact refuse an over-max limit, so the validation itself
is never quietly changed as a side effect of correcting the sentence.

Fix 3 -- ``list_projects``'s ``limit`` is ``ge=0`` (0 = use the default); the sibling
``list_tasks``'s is ``ge=1`` with no "0 means default" story. RULED: align both on
``ge=0``, purely additive (widens what is accepted, never narrows it).

Edition Scope: Both.
"""

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

        # Sanity: the schema DOES reject above this value (le / "maximum") -- the
        # premise the description must not contradict.
        assert "maximum" in schema, "expected list_projects.limit to carry a le= ceiling"

        description = schema["description"].lower()
        # The false claim shipped as "...are clamped, not rejected" -- assert the
        # SPECIFIC backwards phrasing is gone, not the bare word "clamped" (an
        # honest "not clamped" is a legitimate way to phrase the correction).
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
        """Never change as a side effect of fixing the sentence (PRE-RULING: do not
        change the validation to match the sentence -- the rejection is correct).

        Drives ``fn_metadata.validate_arguments`` -- the SAME pydantic arg-model
        validation FastMCP runs against a real client call -- rather than
        re-implementing the bound, so this exercises the actual boundary.
        """
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
