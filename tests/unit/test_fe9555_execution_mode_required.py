# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9555 -- staging ASKS which execution mode, on both doors.

Ruling 6 of the FE-9555 design session: "Execution mode must be ASKED, both
doors." The dashboard door already asks (``ExecutionModeSelector`` at staging).
The harness door did not: ``stage_project``'s ``mode`` parameter carried a
default of ``"multi_terminal"``, so an agent that simply never thought about the
question got Multi-Terminal silently chosen for its user. The two modes are not
interchangeable -- one spawns a terminal per agent for a human to watch, the
other drives the workers inside a single session -- so picking for the user is
picking wrong half the time, quietly.

The fix is the PRODUCT_AMBIGUOUS pattern that BE-9523b established for an
omitted ``product_id``: a structured, agent-actionable Tier-2 rejection
(``{"success": False, "error": ...}``) that reaches the agent as normal tool
content with the remedy inline, rather than an ``isError`` it has to guess at.
Here the remedy is "ask your user", so the refusal carries BOTH modes with a
one-line explanation each -- the agent cannot relay a choice it was not given
the words for.

An account that does not want to be asked every time says so ONCE, in
Tools -> Agents: *ask every time* (the default) / *subagents* / *terminals*.
When it names a mode, staging uses it and never refuses.

Red-first, and each assertion below fails on the pre-FE-9555 tree:

* the schema still advertised ``default: "multi_terminal"``;
* an omitted mode raised ``ValidationError("Invalid mode '' ...")`` -- an
  ``isError`` with no remedy -- instead of the structured refusal;
* ``default_stage_mode`` did not exist.

The RIDE-ALONG clause is pinned here too (same design session, same tool). Five
blind routing tests -- Haiku plus the operator's qwen-coder and gemma-12B,
split and folded variants -- every model, every variant, sent "during staging,
the orchestrator writes the goal statement" to ``stage_project``, INCLUDING the
variant whose prompt explicitly said ``update_project`` owns the mission. The
models do not merely guess wrong; they override the instruction. So the tool
that they reach for has to say, in its own description, that it is not the one.
"""

from __future__ import annotations

import asyncio

import pytest


REAL_CHOICES = ("multi_terminal", "subagent")


def _stage_project_schema() -> dict:
    """``stage_project``'s input schema exactly as an MCP client receives it."""
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


# ---------------------------------------------------------------------------
# The schema no longer answers the question on the caller's behalf
# ---------------------------------------------------------------------------


def test_mode_does_not_default_to_a_real_execution_mode() -> None:
    """A default IS an answer. Publishing one means the question never gets asked."""
    mode = _stage_project_schema().get("properties", {}).get("mode", {})
    default = mode.get("default")
    assert default not in REAL_CHOICES, (
        f"stage_project.mode still defaults to {default!r}. A caller that never considered "
        "the question gets that mode chosen for its user silently -- which is the whole "
        "defect ruling 6 names. The sentinel default must mean 'not answered'."
    )


def test_mode_still_advertises_exactly_the_two_real_choices() -> None:
    """BE-9554's enum is load-bearing here: the refusal tells the agent to ask its
    user, and the schema is where the agent reads what the two options ARE."""
    enum = _stage_project_schema().get("properties", {}).get("mode", {}).get("enum")
    assert enum is not None and set(enum) == set(REAL_CHOICES), (
        f"mode must keep advertising exactly {sorted(REAL_CHOICES)}; got {enum!r}."
    )


# ---------------------------------------------------------------------------
# The account default -> stage mode mapping
# ---------------------------------------------------------------------------


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
    """Anything not exactly one of the two canonical modes means ASK.

    Failing safe matters more than being lenient here: a stored value nobody
    recognises must not become a silent pick, which is the behaviour being
    removed. Note ``claude`` -- a legacy alias the staging boundary still
    TOLERATES on an explicit call -- is deliberately not a valid account
    DEFAULT: tolerance is for old callers, not for new stored preferences.
    """
    from giljo_mcp.execution_mode_default import default_stage_mode

    assert default_stage_mode(junk) == ""


def test_the_three_account_choices_are_named_in_one_place() -> None:
    from giljo_mcp.execution_mode_default import (
        EXECUTION_MODE_DEFAULT_CHOICES,
        STAGE_MODE_ASK,
    )
    from giljo_mcp.platform_registry import MODE_MULTI_TERMINAL, MODE_SUBAGENT

    assert EXECUTION_MODE_DEFAULT_CHOICES == (STAGE_MODE_ASK, MODE_MULTI_TERMINAL, MODE_SUBAGENT)


# ---------------------------------------------------------------------------
# The refusal itself
# ---------------------------------------------------------------------------


def test_the_refusal_names_both_modes_with_an_explanation_each() -> None:
    """An agent cannot relay a choice it was not given the words for."""
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
    """A refusal that cannot be turned off is a nag. Ruling 6 pairs it with one
    account default, and the rejection is where the user learns that exists."""
    from giljo_mcp.tools.tool_accessor._project_tools import _execution_mode_required_rejection

    hint = _execution_mode_required_rejection()["hint"]
    assert "Tools" in hint and "Agents" in hint, (
        f"the hint must name Tools -> Agents, where the account default lives; got: {hint!r}"
    )


# ---------------------------------------------------------------------------
# The ride-along: stage_project does not write the mission
# ---------------------------------------------------------------------------


def test_stage_project_says_it_does_not_author_the_mission() -> None:
    """Five blind routing tests, three model families: every one of them routed
    "the orchestrator writes the goal statement" to stage_project. The tool they
    reach for has to disown the job and name the one that owns it."""
    description = _stage_project_description()
    assert "update_project_mission" in description, (
        "stage_project's description must name update_project_mission as the mission "
        "writer. Models route mission-authoring here regardless of what other tools' "
        "descriptions say, so this is the only surface that reliably reaches them."
    )


# ---------------------------------------------------------------------------
# The ride-along, RECOMMENDED half:
# stage_project accepts the mission instead of only disowning it
# ---------------------------------------------------------------------------


def test_stage_project_accepts_an_optional_mission() -> None:
    """Swim with the instinct the blind tests measured, instead of fighting it.

    All five routing tests sent mission-authoring to ``stage_project``, including
    the variant explicitly told that another tool owns it. Prose the models
    demonstrably override is not a fix; accepting the parameter is. This is not a
    new pattern either -- ``launch_implementation`` already takes exactly such an
    optional ``mission`` and routes it through ``update_project_mission``.
    """
    mode = _stage_project_schema().get("properties", {}).get("mission")
    assert mode is not None, "stage_project must accept an optional `mission`."


def test_the_mission_parameter_is_optional() -> None:
    """Staging a project whose mission was already authored must not now require
    the caller to re-send it."""
    schema = _stage_project_schema()
    assert "mission" not in (schema.get("required") or [])


def test_the_description_still_names_the_single_writer() -> None:
    """Accepting the parameter does NOT make stage_project a second writer. It
    routes through update_project_mission -- the same one tool the standalone path
    uses -- and the description keeps naming it, so an agent that wants to author
    a mission LATER still knows where to go."""
    assert "update_project_mission" in _stage_project_description()
