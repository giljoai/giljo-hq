# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from api.endpoints.mcp_sdk_server import TOOL_SCOPES, mcp
from api.endpoints.mcp_tools._base import SCOPE_READ
from api.endpoints.mcp_tools._tool_annotations import _READ_SCOPED_BUT_MUTATING, _tool_hints


def _live_tools():
    return list(mcp._tool_manager.list_tools())


def test_every_registered_tool_has_a_title():
    tools = _live_tools()
    assert tools, "expected the FastMCP registry to have registered tools"
    missing = sorted(t.name for t in tools if not t.title)
    assert not missing, f"tools missing a title: {missing}"


def test_every_registered_tool_has_annotations():
    missing = sorted(t.name for t in _live_tools() if t.annotations is None)
    assert not missing, f"tools missing annotations entirely: {missing}"


def test_read_only_hint_agrees_with_tool_scopes():
    mismatches = []
    for tool in _live_tools():
        assert tool.name in TOOL_SCOPES, f"{tool.name} has no TOOL_SCOPES entry"
        if tool.name in _READ_SCOPED_BUT_MUTATING:
            expected_read_only = False
        else:
            expected_read_only = TOOL_SCOPES[tool.name] == SCOPE_READ
        actual = tool.annotations.read_only_hint if tool.annotations else None
        if actual != expected_read_only:
            mismatches.append((tool.name, actual, expected_read_only))
    assert not mismatches, (
        f"readOnlyHint disagrees with TOOL_SCOPES (or its documented _READ_SCOPED_BUT_MUTATING "
        f"override) for: {mismatches}"
    )


def test_read_scoped_but_mutating_override_set_membership_is_locked():
    assert frozenset({"get_thread_history"}) == _READ_SCOPED_BUT_MUTATING


def test_every_tool_carries_an_explicit_destructive_hint():
    missing = sorted(t.name for t in _live_tools() if t.annotations is None or t.annotations.destructive_hint is None)
    assert not missing, f"tools with no explicit destructiveHint: {missing}"


EXPECTED_DESTRUCTIVE_TOOLS = frozenset(
    {
        "complete_job",
        "finalize_job",
        "get_staging_instructions",
        "launch_implementation",
        "report_progress",
        "save_roadmap",
        "stage_project",
        "unlink_projects",
        "update_project",
        "update_task",
        "write_project_closeout",
    }
)


def test_destructive_tool_set_is_exactly():
    live = frozenset(
        t.name for t in _live_tools() if t.annotations is not None and t.annotations.destructive_hint is True
    )
    assert live == EXPECTED_DESTRUCTIVE_TOOLS, (
        f"missing: {sorted(EXPECTED_DESTRUCTIVE_TOOLS - live)}; unexpected: {sorted(live - EXPECTED_DESTRUCTIVE_TOOLS)}"
    )


def test_every_tool_declares_open_world_false():
    not_closed_world = sorted(
        t.name for t in _live_tools() if t.annotations is None or t.annotations.open_world_hint is not False
    )
    assert not not_closed_world, f"tools not declaring openWorldHint=False: {not_closed_world}"


def test_tool_hints_helper_derives_read_only_from_tool_scopes():
    read_name = next(name for name, scope in TOOL_SCOPES.items() if scope == SCOPE_READ)
    write_name = next(name for name, scope in TOOL_SCOPES.items() if scope != SCOPE_READ)

    read_hints = _tool_hints(read_name)
    assert read_hints.read_only_hint is True
    assert read_hints.destructive_hint is False
    assert read_hints.open_world_hint is False

    write_hints = _tool_hints(write_name, destructive=True)
    assert write_hints.read_only_hint is False
    assert write_hints.destructive_hint is True
    assert write_hints.open_world_hint is False


def test_tool_hints_helper_fails_loud_for_an_unmapped_tool_name():
    try:
        _tool_hints("this_tool_name_does_not_exist_be9251")
    except KeyError:
        pass
    else:
        raise AssertionError("expected _tool_hints() to raise KeyError for an unmapped tool name")
