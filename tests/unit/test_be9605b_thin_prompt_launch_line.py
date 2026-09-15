# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.prompts.launch_command_synth import render_harness_launch_block


_GOLDENS = {
    "claude": (
        "## HARNESS\n"
        "Harness: Claude Code. Launch this agent in a fresh Claude Code session:\n"
        '  claude --dangerously-skip-permissions "<this prompt>"\n'
    ),
    "codex": (
        "## HARNESS\n"
        "Harness: Codex. Launch this agent in a fresh Codex session:\n"
        '  codex --dangerously-bypass-approvals-and-sandbox "<this prompt>"\n'
    ),
    "opencode": (
        "## HARNESS\n"
        "Harness: opencode. Launch this agent in a fresh opencode session:\n"
        '  opencode --auto --prompt "<this prompt>"\n'
    ),
    "generic": (
        "## HARNESS\n"
        "Harness: Generic. Launch this agent in any MCP-capable harness connected to this server\n"
        "and seed it with this prompt.\n"
    ),
}


@pytest.mark.parametrize("cli_tool", sorted(_GOLDENS))
def test_launch_block_golden_per_preset(cli_tool: str) -> None:
    assert render_harness_launch_block(cli_tool, model="inherit", effort="inherit") == _GOLDENS[cli_tool]


def test_inherit_emits_no_hint_lines() -> None:
    block = render_harness_launch_block("claude", model="inherit", effort="inherit")
    assert "Model hint" not in block
    assert "Effort hint" not in block


def test_none_and_blank_read_as_inherit() -> None:
    assert render_harness_launch_block("claude", model=None, effort="  ") == _GOLDENS["claude"]


def test_hints_render_when_set_and_are_forwarded_verbatim() -> None:
    block = render_harness_launch_block("codex", model="gpt-5 (or whatever is newest)", effort="think very hard")
    assert block.endswith(
        "Model hint: gpt-5 (or whatever is newest)\n"
        "Effort hint: think very hard\n"
        "(Hints are prose for the harness; 'inherit' means the same as the orchestrator. "
        "Ignore a hint your harness cannot honour.)\n"
    )


def test_unknown_and_retired_tokens_fold_to_generic() -> None:
    assert render_harness_launch_block("gemini", model=None, effort=None) == _GOLDENS["generic"]
    assert render_harness_launch_block(None, model=None, effort=None) == _GOLDENS["generic"]
