# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.platform_registry import HARNESSES
from giljo_mcp.prompts.launch_command_synth import posix_single_quote, pwsh_single_quote, synthesize_agent_launch


SEED = "You are a GiljoAI agent. Load your mission."

FLAGGED = [(h.cli_tool, h.launch_prompt_flag) for h in HARNESSES if h.launch_prompt_flag]
POSITIONAL = [h.cli_tool for h in HARNESSES if not h.launch_prompt_flag]


def _commands(cli_tool: str) -> dict:
    return synthesize_agent_launch(
        {"agent": "researcher", "cli_tool": cli_tool, "job_id": "job-1", "seed_prompt": SEED}
    )["commands"]


def test_registry_declares_a_prompt_flag_for_at_least_one_harness():
    assert FLAGGED, "no harness declares launch_prompt_flag -- the tests below prove nothing"


@pytest.mark.parametrize("cli_tool,flag", FLAGGED)
def test_prompt_flag_precedes_the_seed_on_every_posix_command(cli_tool, flag):
    cmds = _commands(cli_tool)
    quoted = posix_single_quote(SEED)
    for os_name in ("linux", "linux_fallback", "macos"):
        assert f"{flag} " in cmds[os_name], f"{cli_tool} {os_name} command omits {flag}"
    assert f"{flag} {quoted}" in cmds["linux"]
    assert f"{flag} {quoted}" in cmds["linux_fallback"]


@pytest.mark.parametrize("cli_tool,flag", FLAGGED)
def test_prompt_flag_is_its_own_windows_argument(cli_tool, flag):
    cmd = _commands(cli_tool)["windows"]
    assert f"{flag},{pwsh_single_quote(SEED)}" in cmd


@pytest.mark.parametrize("cli_tool", POSITIONAL)
def test_positional_harnesses_gain_no_flag(cli_tool):
    cmds = _commands(cli_tool)
    for os_name in ("linux", "linux_fallback", "macos", "windows"):
        assert "--prompt" not in cmds[os_name], f"{cli_tool} {os_name} gained a spurious --prompt"


def test_opencode_election_emits_the_verified_shape():
    cmds = _commands("opencode")
    assert f"-- opencode --auto --prompt {posix_single_quote(SEED)}" in cmds["linux"]
