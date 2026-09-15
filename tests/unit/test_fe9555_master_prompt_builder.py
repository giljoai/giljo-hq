# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest


PROJECTS = [
    {"project_id": "p-1", "taxonomy_alias": "FE-0001", "name": "First", "mission": "Ship the first thing."},
    {"project_id": "p-2", "taxonomy_alias": "BE-0002", "name": "Second", "mission": "Then the second."},
]


def _build(**overrides):
    from giljo_mcp.prompts.master_prompt_builder import build_master_prompt

    kwargs = {
        "projects": PROJECTS,
        "execution_mode": "subagent",
        "mcp_url": "https://example.test/mcp",
        "harness_is_claude": False,
    }
    kwargs.update(overrides)
    return build_master_prompt(**kwargs)




def test_every_selected_project_is_named_with_its_id() -> None:
    prompt = _build()
    for project in PROJECTS:
        assert project["project_id"] in prompt
        assert project["taxonomy_alias"] in prompt


def test_the_projects_appear_in_the_order_they_were_given() -> None:
    prompt = _build()
    assert prompt.index("FE-0001") < prompt.index("BE-0002")


def test_the_prompt_names_link_projects_as_the_tool_that_records_the_run() -> None:
    prompt = _build()
    assert "link_projects" in prompt
    assert "start_chain_run" not in prompt


def test_the_execution_mode_is_stated_and_not_left_to_the_agent() -> None:
    assert "subagent" in _build(execution_mode="subagent")
    assert "multi_terminal" in _build(execution_mode="multi_terminal")


def test_the_mcp_url_reaches_the_prompt() -> None:
    assert "https://example.test/mcp" in _build()


def test_the_staging_human_gate_is_not_quietly_dropped() -> None:
    prompt = _build().lower()
    assert "launch_implementation" in prompt or "implement" in prompt




def test_claude_code_gets_the_toolsearch_bootstrap_and_others_do_not() -> None:
    claude = _build(harness_is_claude=True)
    generic = _build(harness_is_claude=False)

    assert "ToolSearch" in claude
    assert "ToolSearch" not in generic




def test_an_empty_selection_is_refused_rather_than_rendered() -> None:
    from giljo_mcp.exceptions import ValidationError

    with pytest.raises(ValidationError):
        _build(projects=[])


def test_an_unknown_execution_mode_is_refused() -> None:
    from giljo_mcp.exceptions import ValidationError

    with pytest.raises(ValidationError):
        _build(execution_mode="terminals")


def test_a_project_with_no_mission_is_still_rendered_and_says_so() -> None:
    prompt = _build(projects=[{"project_id": "p-3", "taxonomy_alias": "IN-0003", "name": "Third", "mission": ""}])
    assert "p-3" in prompt
    assert "IN-0003" in prompt


def test_the_tool_prefix_is_derived_from_branding_not_written_out() -> None:
    from giljo_mcp.branding import MCP_ALIAS

    assert f"mcp__{MCP_ALIAS}__" in _build(harness_is_claude=True)
