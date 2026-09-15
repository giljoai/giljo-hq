# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp import platform_registry as reg




def test_workspace_model_vocabulary_is_the_three_values():
    assert frozenset({"shared_working_tree", "isolated_pr", "none"}) == reg.VALID_WORKSPACE_MODELS
    assert reg.WORKSPACE_SHARED_WORKING_TREE == "shared_working_tree"
    assert reg.WORKSPACE_ISOLATED_PR == "isolated_pr"
    assert reg.WORKSPACE_NONE == "none"


def test_platform_default_workspace_model_is_shared_working_tree():
    assert len(reg.MODES) == 2
    assert len(reg.HARNESSES) == 3
    p = reg.Platform(
        execution_mode="probe",
        tool_type="probe",
        cli_tool=None,
        cli_binary=None,
        display_label="Probe",
        is_subagent=True,
    )
    assert p.workspace_model == reg.WORKSPACE_SHARED_WORKING_TREE
    assert p.has_shell is True




def test_preset_names_exact_set_and_order():
    assert reg.PRESET_NAMES == ("web_sandbox", "desktop_app", "chat")
    assert frozenset({"web_sandbox", "desktop_app", "chat"}) == reg.VALID_PRESETS


def test_get_preset_resolves_each_preset_row():
    for name in reg.PRESET_NAMES:
        p = reg.get_preset(name)
        assert p is not None, f"preset {name!r} must resolve"
        assert p.execution_mode == name


def test_web_sandbox_preset_vectors():
    p = reg.get_preset("web_sandbox")
    assert p.can_spawn_terminals is False
    assert p.workspace_model == reg.WORKSPACE_ISOLATED_PR
    assert p.is_subagent is True


def test_desktop_app_preset_vectors():
    p = reg.get_preset("desktop_app")
    assert p.can_spawn_terminals is False
    assert p.workspace_model == reg.WORKSPACE_SHARED_WORKING_TREE
    assert p.is_subagent is True


def test_chat_preset_vectors():
    p = reg.get_preset("chat")
    assert p.can_spawn_terminals is False
    assert p.workspace_model == reg.WORKSPACE_NONE
    assert p.is_subagent is True


def test_derived_preset_sets():
    assert frozenset({"web_sandbox", "desktop_app", "chat"}) == reg.NON_TERMINAL_PRESETS
    assert reg.PRESET_WORKSPACE_MODELS == {
        "web_sandbox": "isolated_pr",
        "desktop_app": "shared_working_tree",
        "chat": "none",
    }




def test_presets_absent_from_execution_mode_axis():
    assert frozenset({"multi_terminal", "subagent"}) == reg.VALID_EXECUTION_MODES
    for preset in reg.PRESET_NAMES:
        assert preset not in reg.VALID_EXECUTION_MODES
        assert preset not in reg.ACCEPTED_EXECUTION_MODES
        assert preset not in reg.EXECUTION_MODES
        assert preset not in reg.SUBAGENT_EXECUTION_MODES
        assert preset not in reg.mode_csv()
        assert preset not in reg.mode_label_list()
        assert preset not in reg.execution_mode_pattern()


def test_terminal_capable_modes_is_multi_terminal_only():
    assert frozenset({"multi_terminal"}) == reg.TERMINAL_CAPABLE_MODES
    assert len(reg.TERMINAL_CAPABLE_MODES) == 1
    assert "subagent" in reg.VALID_EXECUTION_MODES
    assert "subagent" not in reg.TERMINAL_CAPABLE_MODES


def test_get_platform_and_get_preset_never_cross_resolve():
    for preset in reg.PRESET_NAMES:
        assert reg.get_platform(preset) is None
    for mode in reg.EXECUTION_MODES:
        assert reg.get_preset(mode) is None




def test_tool_for_mode_failsafes_presets_to_multi_terminal():
    for preset in reg.PRESET_NAMES:
        assert reg.tool_for_mode(preset) == "multi_terminal"


def test_is_subagent_render_routes_presets_authoritatively_true():
    for preset in reg.PRESET_NAMES:
        assert reg.is_subagent_render(preset) is True
    assert reg.is_subagent_render("multi_terminal") is False
    assert reg.is_subagent_render("totally_unknown_harness") is True




def test_declared_preset_wins():
    assert reg.select_effective_preset(declared="chat").execution_mode == "chat"


def test_detected_preset_from_capability_vector():
    p = reg.select_effective_preset(capabilities={"preset": "web_sandbox"})
    assert p is not None and p.execution_mode == "web_sandbox"


def test_declared_beats_detected_on_conflict():
    p = reg.select_effective_preset(declared="web_sandbox", capabilities={"preset": "chat"})
    assert p.execution_mode == "web_sandbox", "declared must outrank the detected signal"


def test_no_signal_returns_none():
    assert reg.select_effective_preset() is None
    assert reg.select_effective_preset(declared=None, capabilities={}) is None
    assert reg.select_effective_preset(capabilities={"elicitation": True, "tasks": False}) is None


def test_garbage_declared_degrades_to_detected_then_none():
    p = reg.select_effective_preset(declared="not_a_preset", capabilities={"preset": "desktop_app"})
    assert p.execution_mode == "desktop_app"
    assert reg.select_effective_preset(declared="nope", capabilities={"preset": "also_nope"}) is None




def test_terminal_available_defaults_true_when_no_signal():
    assert reg.terminal_available() is True
    assert reg.terminal_available(None) is True
    assert reg.terminal_available({}) is True
    assert reg.terminal_available({"elicitation": True, "tasks": True}) is True


def test_terminal_available_honors_explicit_boolean():
    assert reg.terminal_available({"can_spawn_terminals": False}) is False
    assert reg.terminal_available({"can_spawn_terminals": True}) is True


def test_terminal_available_ignores_non_boolean_signal():
    assert reg.terminal_available({"can_spawn_terminals": "yes"}) is True
