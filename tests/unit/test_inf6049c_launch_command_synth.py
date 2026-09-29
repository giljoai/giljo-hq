# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.platform_registry import HARNESSES
from giljo_mcp.prompts import launch_command_synth
from giljo_mcp.prompts.launch_command_synth import (
    AUTONOMY_FLAGS,
    CLI_BINARIES,
    PROMPT_FLAGS,
    autonomy_flag,
    prompt_flag,
    resolve_binary,
)


@pytest.mark.parametrize(
    "cli_tool,expected_binary",
    [
        ("claude", "claude"),
        ("codex", "codex"),
    ],
)
def test_binary_mapping_per_tool(cli_tool, expected_binary):
    assert resolve_binary(cli_tool) == expected_binary
    assert CLI_BINARIES[cli_tool] == expected_binary


def test_unknown_and_empty_cli_tool_default_to_claude():
    assert resolve_binary(None) == "claude"
    assert resolve_binary("") == "claude"
    assert resolve_binary("totally-unknown") == "claude"


def test_flag_lookups_are_registry_derived_with_no_holes():
    for harness in HARNESSES:
        assert harness.autonomy_flag, f"{harness.cli_binary} declares no autonomy flag"
        assert AUTONOMY_FLAGS[harness.cli_binary] == harness.autonomy_flag
        assert PROMPT_FLAGS.get(harness.cli_binary, "") == (harness.launch_prompt_flag or "")


def test_unknown_binary_gets_no_invented_flags():
    assert autonomy_flag("definitely-not-a-cli") == ""
    assert prompt_flag("definitely-not-a-cli") == ""


def test_per_worker_shell_command_synthesis_stays_deleted():
    retired = (
        "build_loaded_prompt",
        "synthesize_agent_launch",
        "synthesize_launch_commands",
        "windows_command",
        "linux_command",
        "linux_command_fallback",
        "macos_command",
        "posix_single_quote",
        "pwsh_single_quote",
        "applescript_quote",
    )
    present = [name for name in retired if hasattr(launch_command_synth, name)]
    assert not present, (
        f"per-worker launch-command synthesis is back: {present}. The server must not author "
        "worker launch syntax or add a permission-bypass flag the user did not ask for."
    )
