# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-3010a -- PlatformRegistry is the single source of CLI-platform identity.

Locks the registry's derived identity (sets, maps, regexes, labels) so a future
platform add/remove updates exactly one place, and pins the live regression: the
user-facing "no execution mode selected" guidance MUST list every platform
(Antigravity was silently omitted by the literal that this registry replaces).

Edition Scope: Both. Pure constants -- no DB, no module-level mutable state;
parallel-safe under pytest-xdist.
"""

from __future__ import annotations

from giljo_mcp import platform_registry as reg


def test_valid_execution_modes_exact_set():
    # BE-9035c: the NEW-write set collapses to exactly the 2 canonical modes.
    assert frozenset({"multi_terminal", "subagent"}) == reg.VALID_EXECUTION_MODES


def test_subagent_modes_are_subagent_plus_the_five_legacy_aliases():
    # multi_terminal is NOT a subagent mode (separate processes can't share a
    # Task() return value). BE-9035c: the subagent set is the canonical ``subagent``
    # mode PLUS all 5 legacy CLI tokens (every legacy CLI folds onto subagent).
    assert (
        frozenset({"subagent", "claude_code_cli", "codex_cli", "gemini_cli", "antigravity_cli", "generic_mcp"})
        == reg.SUBAGENT_EXECUTION_MODES
    )
    assert "multi_terminal" not in reg.SUBAGENT_EXECUTION_MODES


def test_execution_mode_to_tool_exact_map():
    # BE-9035c: canonical multi_terminal/subagent map onto multi_terminal/generic;
    # the 5 legacy tokens still resolve to the harness they historically implied.
    assert reg.EXECUTION_MODE_TO_TOOL == {
        "multi_terminal": "multi_terminal",
        "subagent": "generic",
        "claude_code_cli": "claude-code",
        "codex_cli": "codex",
        "gemini_cli": "gemini",
        "antigravity_cli": "antigravity",
        "generic_mcp": "generic",
    }


def test_cli_binaries_exact_map_including_agy():
    # BE-9035c: opencode is now a first-class harness row, so its binary joins the map.
    assert reg.CLI_BINARIES == {
        "claude": "claude",
        "codex": "codex",
        "gemini": "gemini",
        "antigravity": "agy",
        "opencode": "opencode",
    }


def test_tool_for_mode_ho1020_failsafe():
    # Known modes map straight through.
    assert reg.tool_for_mode("antigravity_cli") == "antigravity"
    assert reg.tool_for_mode("multi_terminal") == "multi_terminal"
    # Unknown / empty / None fall back to the platform-neutral tool, never the
    # Claude Code branch (HO1020).
    assert reg.tool_for_mode("totally_unknown_cli") == "multi_terminal"
    assert reg.tool_for_mode("") == "multi_terminal"
    assert reg.tool_for_mode(None) == "multi_terminal"


def test_is_subagent_mode():
    assert reg.is_subagent_mode("codex_cli") is True
    assert reg.is_subagent_mode("multi_terminal") is False
    assert reg.is_subagent_mode(None) is False


def test_patterns_append_generic_mcp_after_the_pre_registry_literals():
    # BE-9035c: the execution-mode pattern is the 2 canonical modes followed by the 5
    # legacy aliases (tolerance for stored rows); the tool_type pattern is the 5
    # harness tool_types (opencode now included) plus the legacy generic_mcp token.
    assert reg.execution_mode_pattern() == (
        "^(multi_terminal|subagent|claude_code_cli|codex_cli|gemini_cli|antigravity_cli|generic_mcp)$"
    )
    assert reg.tool_type_pattern() == "^(claude-code|codex|gemini|antigravity|opencode|generic_mcp)$"


def test_mode_csv_is_canonical_ordered_list():
    assert reg.mode_csv() == "multi_terminal, subagent"


# ---------------------------------------------------------------------------
# REGRESSION (the live miss) -- at the service layer where the bug shipped.
# ---------------------------------------------------------------------------


def test_mode_not_selected_message_lists_the_canonical_modes():
    """REGRESSION (BE-3010a -> BE-9035c): the mode-not-selected guidance is built from
    the registry, so it names every SELECTABLE mode label. Post-collapse the axis is
    the 2 canonical modes (Multi-Terminal / Subagent) -- the old per-CLI labels are
    gone from the selectable set."""
    from giljo_mcp.services.execution_mode_gate import EXECUTION_MODE_NOT_SELECTED_MESSAGE

    for label in ("Multi-Terminal", "Subagent"):
        assert label in EXECUTION_MODE_NOT_SELECTED_MESSAGE, f"mode-not-selected guidance dropped mode label {label!r}"


def test_label_list_helper_is_the_two_canonical_mode_labels():
    # BE-9035c: only the 2 canonical modes are selectable, so the label list is
    # exactly their display labels.
    assert reg.mode_label_list() == "Multi-Terminal / Subagent"
    # Legacy tokens are no longer selectable labels but remain tolerated at the
    # validation boundary.
    assert "generic_mcp" in reg.ACCEPTED_EXECUTION_MODES
    assert "antigravity_cli" in reg.ACCEPTED_EXECUTION_MODES


# ---------------------------------------------------------------------------
# Re-export identity -- the former owning modules now resolve to the registry's
# objects (same identity), so legacy importers see no change.
# ---------------------------------------------------------------------------


def test_execution_mode_gate_reexports_registry_valid_modes():
    from giljo_mcp.services import execution_mode_gate

    assert execution_mode_gate.VALID_EXECUTION_MODES is reg.VALID_EXECUTION_MODES


def test_predecessor_context_reexports_registry_subagent_modes():
    from giljo_mcp.services import _predecessor_context

    assert _predecessor_context.SUBAGENT_EXECUTION_MODES is reg.SUBAGENT_EXECUTION_MODES


def test_launch_command_synth_reexports_registry_cli_binaries():
    from giljo_mcp.prompts import launch_command_synth

    assert launch_command_synth.CLI_BINARIES is reg.CLI_BINARIES


# ---------------------------------------------------------------------------
# BE-6207: /giljo vs $giljo invocation token derived from SKILL_SLASH_PLATFORMS
# (a hardcoded ``tool == "codex"`` check previously dropped Antigravity).
# ---------------------------------------------------------------------------


def test_skill_slash_tool_types_match_skill_slash_platforms():
    """The $giljo tool_types are derived from SKILL_SLASH_PLATFORMS, not hardcoded."""
    expected = {h.tool_type for h in reg.HARNESSES if h.export_platform in reg.SKILL_SLASH_PLATFORMS}
    assert frozenset(expected) == reg.SKILL_SLASH_TOOL_TYPES
    # Codex AND Antigravity install as $-prefixed skills.
    assert frozenset({"codex", "antigravity"}) == reg.SKILL_SLASH_TOOL_TYPES


def test_giljo_invocation_token_per_tool():
    """$giljo for codex + antigravity; /giljo for claude, gemini, multi_terminal, unknown."""
    assert reg.giljo_invocation("codex") == "$giljo"
    assert reg.giljo_invocation("antigravity") == "$giljo", "Antigravity installs $giljo (BE-6207 regression)"
    assert reg.giljo_invocation("claude") == "/giljo"
    assert reg.giljo_invocation("gemini") == "/giljo"
    assert reg.giljo_invocation("multi_terminal") == "/giljo"
    assert reg.giljo_invocation(None) == "/giljo"
    assert reg.giljo_invocation("") == "/giljo"


# ---------------------------------------------------------------------------
# BE-9260: harness-neutral task-list phrasing. "TodoWrite list" only for the
# detected claude-code harness; every other/unknown tool gets "task list" so
# customer-reaching protocol prose never names a tool the harness lacks.
# ---------------------------------------------------------------------------


def test_task_list_phrase_todowrite_only_for_claude_code():
    assert reg.task_list_phrase("claude-code") == "TodoWrite list"
    assert reg.task_list_phrase("codex") == "task list"
    assert reg.task_list_phrase("gemini") == "task list"
    assert reg.task_list_phrase("antigravity") == "task list"
    assert reg.task_list_phrase("multi_terminal") == "task list"
    assert reg.task_list_phrase(None) == "task list"
    assert reg.task_list_phrase("") == "task list"
