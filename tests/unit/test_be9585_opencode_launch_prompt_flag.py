# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9585 — the per-template harness election must reach the launch command in the
SHAPE the elected harness actually accepts.

``agent_templates.cli_tool`` elects which CLI a multi_terminal agent's terminal runs
(documenter -> codex, researcher -> opencode, ...). The election reached the BINARY
correctly for all five harnesses, but ``Harness.launch_prompt_flag`` -- the registry
fact that opencode seeds a fresh session with ``--prompt <text>`` rather than
positionally -- had NO consumer anywhere in the tree, so an opencode election emitted
a claude-shaped positional command. The classic CLIs take the prompt positionally and
MUST stay byte-identical.

Pure string asserts; no subprocess, no DB, no env state.
"""

from __future__ import annotations

import pytest

from giljo_mcp.platform_registry import HARNESSES
from giljo_mcp.prompts.launch_command_synth import posix_single_quote, pwsh_single_quote, synthesize_agent_launch


SEED = "You are a GiljoAI agent. Load your mission."

# cli_tool tokens whose harness row declares a prompt flag, and those that do not.
FLAGGED = [(h.cli_tool, h.launch_prompt_flag) for h in HARNESSES if h.launch_prompt_flag]
POSITIONAL = [h.cli_tool for h in HARNESSES if not h.launch_prompt_flag]


def _commands(cli_tool: str) -> dict:
    return synthesize_agent_launch(
        {"agent": "researcher", "cli_tool": cli_tool, "job_id": "job-1", "seed_prompt": SEED}
    )["commands"]


def test_registry_declares_a_prompt_flag_for_at_least_one_harness():
    """Guard the guard: if no row declares a flag the assertions below are vacuous."""
    assert FLAGGED, "no harness declares launch_prompt_flag -- the tests below prove nothing"


@pytest.mark.parametrize("cli_tool,flag", FLAGGED)
def test_prompt_flag_precedes_the_seed_on_every_posix_command(cli_tool, flag):
    cmds = _commands(cli_tool)
    quoted = posix_single_quote(SEED)
    for os_name in ("linux", "linux_fallback", "macos"):
        assert f"{flag} " in cmds[os_name], f"{cli_tool} {os_name} command omits {flag}"
    # The flag sits immediately before the quoted seed, not somewhere incidental.
    assert f"{flag} {quoted}" in cmds["linux"]
    assert f"{flag} {quoted}" in cmds["linux_fallback"]


@pytest.mark.parametrize("cli_tool,flag", FLAGGED)
def test_prompt_flag_is_its_own_windows_argument(cli_tool, flag):
    cmd = _commands(cli_tool)["windows"]
    # -ArgumentList elements are comma-separated; the flag is a static token and the
    # seed stays inside ONE PowerShell single-quoted literal.
    assert f"{flag},{pwsh_single_quote(SEED)}" in cmd


@pytest.mark.parametrize("cli_tool", POSITIONAL)
def test_positional_harnesses_gain_no_flag(cli_tool):
    """The 4 classic CLIs take the prompt positionally -- byte-identical to before."""
    cmds = _commands(cli_tool)
    for os_name in ("linux", "linux_fallback", "macos", "windows"):
        assert "--prompt" not in cmds[os_name], f"{cli_tool} {os_name} gained a spurious --prompt"


def test_opencode_election_emits_the_verified_shape():
    """The concrete case the operator asked about: researcher elected to opencode.

    Flags verified against the installed binary's own ``opencode --help`` on
    2026-09-04: ``--prompt <string>`` ("prompt to use") seeds the interactive TUI,
    and ``--auto`` ("auto-approve permissions that are not explicitly denied")
    is its unattended-autonomy flag. ``opencode run`` is the one-shot form and is
    deliberately NOT used -- it would exit and kill the spawned terminal.
    """
    cmds = _commands("opencode")
    assert f"-- opencode --auto --prompt {posix_single_quote(SEED)}" in cmds["linux"]


def test_antigravity_seeds_interactively_not_via_the_one_shot_alias():
    """agy's ``--prompt`` is an ALIAS FOR ``--print`` -- it runs once and EXITS.

    Verified against the installed binary (``agy --help``, 2026-09-04):
      --prompt              Alias for --print
      --print               Run a single prompt non-interactively and print the response
      --prompt-interactive  Run an initial prompt interactively and continue the session
    A launched per-agent terminal must survive its first turn, so agy MUST seed with
    ``--prompt-interactive``. This test exists to stop a future edit from "tidying"
    the registry row to the shorter-looking ``--prompt`` and silently killing every
    antigravity terminal.
    """
    cmds = _commands("antigravity")
    assert "--prompt-interactive " in cmds["linux"]
    assert f"--prompt {posix_single_quote(SEED)}" not in cmds["linux"]
    assert "--print" not in cmds["linux"]
