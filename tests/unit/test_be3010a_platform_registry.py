# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp import platform_registry as reg


def test_valid_execution_modes_exact_set():
    assert frozenset({"multi_terminal", "subagent"}) == reg.VALID_EXECUTION_MODES


def test_subagent_modes_are_subagent_plus_the_five_legacy_aliases():
    assert (
        frozenset({"subagent", "claude_code_cli", "codex_cli", "gemini_cli", "antigravity_cli", "generic_mcp"})
        == reg.SUBAGENT_EXECUTION_MODES
    )
    assert "multi_terminal" not in reg.SUBAGENT_EXECUTION_MODES


def test_execution_mode_to_tool_exact_map():
    assert reg.EXECUTION_MODE_TO_TOOL == {
        "multi_terminal": "multi_terminal",
        "subagent": "generic",
        "claude_code_cli": "claude-code",
        "codex_cli": "codex",
        "gemini_cli": "generic",
        "antigravity_cli": "generic",
        "generic_mcp": "generic",
    }


def test_cli_binaries_exact_map():
    assert reg.CLI_BINARIES == {
        "claude": "claude",
        "codex": "codex",
        "opencode": "opencode",
    }


def test_tool_for_mode_ho1020_failsafe():
    assert reg.tool_for_mode("antigravity_cli") == "generic"
    assert reg.tool_for_mode("multi_terminal") == "multi_terminal"
    assert reg.tool_for_mode("totally_unknown_cli") == "multi_terminal"
    assert reg.tool_for_mode("") == "multi_terminal"
    assert reg.tool_for_mode(None) == "multi_terminal"


def test_is_subagent_mode():
    assert reg.is_subagent_mode("codex_cli") is True
    assert reg.is_subagent_mode("multi_terminal") is False
    assert reg.is_subagent_mode(None) is False


def test_patterns_append_generic_mcp_after_the_pre_registry_literals():
    assert reg.execution_mode_pattern() == (
        "^(multi_terminal|subagent|claude_code_cli|codex_cli|gemini_cli|antigravity_cli|generic_mcp)$"
    )
    assert reg.tool_type_pattern() == "^(claude-code|codex|opencode|generic_mcp)$"


def test_mode_csv_is_canonical_ordered_list():
    assert reg.mode_csv() == "multi_terminal, subagent"




def test_mode_not_selected_message_lists_the_canonical_modes():
    from giljo_mcp.services.execution_mode_gate import EXECUTION_MODE_NOT_SELECTED_MESSAGE

    for label in ("Multi-Terminal", "Subagent"):
        assert label in EXECUTION_MODE_NOT_SELECTED_MESSAGE, f"mode-not-selected guidance dropped mode label {label!r}"


def test_label_list_helper_is_the_two_canonical_mode_labels():
    assert reg.mode_label_list() == "Multi-Terminal / Subagent"
    assert "generic_mcp" in reg.ACCEPTED_EXECUTION_MODES
    assert "antigravity_cli" in reg.ACCEPTED_EXECUTION_MODES




def test_execution_mode_gate_reexports_registry_valid_modes():
    from giljo_mcp.services import execution_mode_gate

    assert execution_mode_gate.VALID_EXECUTION_MODES is reg.VALID_EXECUTION_MODES


def test_predecessor_context_reexports_registry_subagent_modes():
    from giljo_mcp.services import _predecessor_context

    assert _predecessor_context.SUBAGENT_EXECUTION_MODES is reg.SUBAGENT_EXECUTION_MODES


def test_launch_command_synth_reexports_registry_cli_binaries():
    from giljo_mcp.prompts import launch_command_synth

    assert launch_command_synth.CLI_BINARIES is reg.CLI_BINARIES




def test_skill_slash_tool_types_match_skill_slash_platforms():
    expected = {h.tool_type for h in reg.HARNESSES if h.export_platform in reg.SKILL_SLASH_PLATFORMS}
    assert frozenset(expected) == reg.SKILL_SLASH_TOOL_TYPES
    assert frozenset({"codex"}) == reg.SKILL_SLASH_TOOL_TYPES


def test_giljo_invocation_token_per_tool():
    assert reg.giljo_invocation("codex") == "$giljo"
    assert reg.giljo_invocation("antigravity") == "/giljo"
    assert reg.giljo_invocation("claude") == "/giljo"
    assert reg.giljo_invocation("gemini") == "/giljo"
    assert reg.giljo_invocation("multi_terminal") == "/giljo"
    assert reg.giljo_invocation(None) == "/giljo"
    assert reg.giljo_invocation("") == "/giljo"




def test_task_list_phrase_todowrite_only_for_claude_code():
    assert reg.task_list_phrase("claude-code") == "TodoWrite list"
    assert reg.task_list_phrase("codex") == "task list"
    assert reg.task_list_phrase("gemini") == "task list"
    assert reg.task_list_phrase("antigravity") == "task list"
    assert reg.task_list_phrase("multi_terminal") == "task list"
    assert reg.task_list_phrase(None) == "task list"
    assert reg.task_list_phrase("") == "task list"
