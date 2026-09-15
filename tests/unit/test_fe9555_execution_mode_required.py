# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio

import pytest


REAL_CHOICES = ("multi_terminal", "subagent")


def _stage_project_schema() -> dict:
    from api.endpoints.mcp_tools import mcp

    async def _read() -> dict:
        tools = await mcp.list_tools()
        tool = next(t for t in tools if t.name == "stage_project")
        return tool.input_schema or {}

    return asyncio.run(_read())


def _stage_project_description() -> str:
    from api.endpoints.mcp_tools import mcp

    async def _read() -> str:
        tools = await mcp.list_tools()
        return next(t for t in tools if t.name == "stage_project").description or ""

    return asyncio.run(_read())




def test_mode_does_not_default_to_a_real_execution_mode() -> None:
    mode = _stage_project_schema().get("properties", {}).get("mode", {})
    default = mode.get("default")
    assert default not in REAL_CHOICES, (
        f"stage_project.mode still defaults to {default!r}. A caller that never considered "
        "the question gets that mode chosen for its user silently -- which is the whole "
        "defect ruling 6 names. The sentinel default must mean 'not answered'."
    )


def test_mode_still_advertises_exactly_the_two_real_choices() -> None:
    enum = _stage_project_schema().get("properties", {}).get("mode", {}).get("enum")
    assert enum is not None and set(enum) == set(REAL_CHOICES), (
        f"mode must keep advertising exactly {sorted(REAL_CHOICES)}; got {enum!r}."
    )




@pytest.mark.parametrize(
    ("setting_value", "expected"),
    [
        ("ask", ""),
        ("", ""),
        (None, ""),
        ("multi_terminal", "multi_terminal"),
        ("subagent", "subagent"),
    ],
)
def test_default_stage_mode_maps_the_account_setting(setting_value, expected) -> None:
    from giljo_mcp.execution_mode_default import default_stage_mode

    assert default_stage_mode(setting_value) == expected


@pytest.mark.parametrize("junk", ["terminals", "SUBAGENT", "claude", "true", "1"])
def test_default_stage_mode_falls_back_to_asking(junk) -> None:
    from giljo_mcp.execution_mode_default import default_stage_mode

    assert default_stage_mode(junk) == ""


def test_the_three_account_choices_are_named_in_one_place() -> None:
    from giljo_mcp.execution_mode_default import (
        EXECUTION_MODE_DEFAULT_CHOICES,
        STAGE_MODE_ASK,
    )
    from giljo_mcp.platform_registry import MODE_MULTI_TERMINAL, MODE_SUBAGENT

    assert EXECUTION_MODE_DEFAULT_CHOICES == (STAGE_MODE_ASK, MODE_MULTI_TERMINAL, MODE_SUBAGENT)




def test_the_refusal_names_both_modes_with_an_explanation_each() -> None:
    from giljo_mcp.tools.tool_accessor._project_tools import _execution_mode_required_rejection

    rejection = _execution_mode_required_rejection()

    assert rejection["success"] is False
    assert rejection["error"] == "EXECUTION_MODE_REQUIRED"

    modes = rejection["modes"]
    assert {m["mode"] for m in modes} == set(REAL_CHOICES)
    for entry in modes:
        assert entry["description"].strip(), f"{entry['mode']} has no explanation to relay"

    hint = rejection["hint"]
    assert "ask" in hint.lower(), "the remedy is to ask the user -- say so"
    for mode in REAL_CHOICES:
        assert mode in hint, f"the hint must name {mode!r} so the retry is copy-pasteable"


def test_the_refusal_points_at_the_account_setting_that_silences_it() -> None:
    from giljo_mcp.tools.tool_accessor._project_tools import _execution_mode_required_rejection

    hint = _execution_mode_required_rejection()["hint"]
    assert "Tools" in hint and "Agents" in hint, (
        f"the hint must name Tools -> Agents, where the account default lives; got: {hint!r}"
    )




def test_stage_project_says_it_does_not_author_the_mission() -> None:
    description = _stage_project_description()
    assert "update_project_mission" in description, (
        "stage_project's description must name update_project_mission as the mission "
        "writer. Models route mission-authoring here regardless of what other tools' "
        "descriptions say, so this is the only surface that reliably reaches them."
    )




def test_stage_project_accepts_an_optional_mission() -> None:
    mode = _stage_project_schema().get("properties", {}).get("mission")
    assert mode is not None, "stage_project must accept an optional `mission`."


def test_the_mission_parameter_is_optional() -> None:
    schema = _stage_project_schema()
    assert "mission" not in (schema.get("required") or [])


def test_the_description_still_names_the_single_writer() -> None:
    assert "update_project_mission" in _stage_project_description()
