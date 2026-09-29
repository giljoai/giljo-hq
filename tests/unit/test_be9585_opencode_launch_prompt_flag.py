# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.platform_registry import HARNESSES, MODE_MULTI_TERMINAL
from giljo_mcp.prompts.launch_command_synth import prompt_flag, render_suborch_spawn_command


RUN_ID = "11111111-1111-1111-1111-111111111111"

FLAGGED = [(h.cli_tool, h.launch_prompt_flag) for h in HARNESSES if h.launch_prompt_flag]
POSITIONAL = [h.cli_tool for h in HARNESSES if not h.launch_prompt_flag]


def _multi_harness_render() -> str:
    return render_suborch_spawn_command(MODE_MULTI_TERMINAL, RUN_ID)


def _row(cli_tool: str):
    return next(h for h in HARNESSES if h.cli_tool == cli_tool)


def test_registry_declares_a_prompt_flag_for_at_least_one_harness():
    assert FLAGGED, "no harness declares launch_prompt_flag -- the tests below prove nothing"


@pytest.mark.parametrize("cli_tool,flag", FLAGGED)
def test_registry_records_the_verified_prompt_flag(cli_tool, flag):
    row = _row(cli_tool)
    assert row.launch_prompt_flag == flag
    assert prompt_flag(row.cli_binary) == flag
    assert row.autonomy_flag, f"{cli_tool} must declare an autonomy flag for an unattended spawn"


def test_conductor_matrix_excludes_the_flag_seeded_harness_by_design():
    from giljo_mcp.prompts.launch_command_synth import _ordered_spawn_binaries

    listed = _ordered_spawn_binaries()
    for cli_tool, _flag in FLAGGED:
        assert _row(cli_tool).cli_binary not in listed, (
            f"{cli_tool} is now in the conductor spawn matrix -- add a rendered assertion for "
            "its --prompt seeding shape instead of relying on the registry fact alone"
        )


@pytest.mark.parametrize("cli_tool", POSITIONAL)
def test_positional_harnesses_gain_no_prompt_flag(cli_tool):
    render = _multi_harness_render()
    row = _row(cli_tool)
    assert f"{row.cli_binary} {row.autonomy_flag} '" in render, f"{cli_tool} lost its positional seeding shape"
    assert f"{row.cli_binary} {row.autonomy_flag} --prompt" not in render, f"{cli_tool} gained a spurious --prompt"


def test_no_one_shot_form_reaches_a_spawn_command():
    render = _multi_harness_render()
    for one_shot in (" -p ", " --print ", "opencode run "):
        assert one_shot not in render, f"a one-shot invocation reached the spawn command: {one_shot!r}"
