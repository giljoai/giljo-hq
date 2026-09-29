# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.prompts.launch_command_synth import render_harness_launch_block


_NO_BYPASS = "Do not add a permission-bypass or autonomy flag unless the user asked for one.\n"

_GOLDENS = {
    "codex": (
        "## HARNESS\n"
        "Harness: codex (the user chose it for this agent). Find it on this machine, work out its launch\n"
        "syntax (its --help usually says), and open it in a new terminal seeded with this prompt.\n"
        "If you cannot find it or are unsure how to launch it, ask the user.\n" + _NO_BYPASS
    ),
    None: (
        "## HARNESS\n"
        "Harness: default. Open a new terminal running the same harness you are running in,\n"
        "seeded with this prompt.\n" + _NO_BYPASS
    ),
}


@pytest.mark.parametrize("harness", ["codex", None])
def test_launch_block_golden(harness) -> None:
    assert render_harness_launch_block(harness, model="inherit", effort="inherit") == _GOLDENS[harness]


@pytest.mark.parametrize("harness", ["claude", "codex", "opencode", None])
def test_no_launch_syntax_or_bypass_flag_for_any_harness(harness) -> None:
    block = render_harness_launch_block(harness, model=None, effort=None)
    for flag in ("--dangerously", "--auto", "--prompt", '"<this prompt>"'):
        assert flag not in block, block


def test_inherit_emits_no_hint_lines() -> None:
    block = render_harness_launch_block("claude", model="inherit", effort="inherit")
    assert "Model hint" not in block
    assert "Effort hint" not in block


def test_none_and_blank_read_as_inherit() -> None:
    assert render_harness_launch_block("codex", model=None, effort="  ") == _GOLDENS["codex"]


def test_hints_render_when_set_and_are_forwarded_verbatim() -> None:
    block = render_harness_launch_block("codex", model="gpt-5 (or whatever is newest)", effort="think very hard")
    assert block.endswith(
        "Model hint: gpt-5 (or whatever is newest)\n"
        "Effort hint: think very hard\n"
        "(Hints are prose for the harness; 'inherit' means the same as the orchestrator. "
        "Ignore a hint your harness cannot honour.)\n"
    )
