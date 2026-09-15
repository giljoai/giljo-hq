# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp import platform_registry as reg
from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch3_spawning_rules




def test_generic_mcp_is_a_legacy_alias_not_a_registry_row():
    assert "generic_mcp" in reg.LEGACY_MODE_ALIASES
    assert "generic_mcp" in reg.ACCEPTED_EXECUTION_MODES
    assert reg.get_platform("generic_mcp") is None
    assert reg.get_mode("generic_mcp") is None
    assert reg.normalize_execution_mode("generic_mcp") == "subagent"
    assert reg.is_subagent_mode("generic_mcp") is True
    assert reg.is_subagent_render("generic_mcp") is True


def test_generic_mcp_maps_to_the_generic_floor_tool():
    assert reg.tool_for_mode("generic_mcp") == "generic"
    assert reg.EXECUTION_MODE_TO_TOOL["generic_mcp"] == "generic"
    assert reg.EXECUTION_MODE_TO_TOOL["subagent"] == "generic"
    assert "generic_mcp" not in reg.CLI_BINARIES.values()




def test_generic_mcp_ch3_renders_full_ladder_by_default():
    ch3 = _build_ch3_spawning_rules("generic_mcp")
    assert _build_ch3_spawning_rules("generic") == ch3
    assert "DELEGATE FIRST — you are an ORCHESTRATOR, not the implementer." in ch3
    assert "ANY MCP-CONNECTED AGENT (generic_mcp)" in ch3
    assert "OPTION A — ONE TERMINAL PER AGENT" in ch3
    assert "OPTION B — IN-PROCESS SUBAGENT" in ch3
    assert 'cmd /k opencode --prompt "<prompt>"' in ch3
    assert "the cmd /k wrapper (NOT pwsh -NoExit) so opencode.cmd resolves from PATH." in ch3
    assert "gnome-terminal --working-directory=" in ch3 and "osascript" in ch3
    assert "a Task tool" in ch3 and "an agent spawner" in ch3
    assert "[IF YOU CANNOT DO THE ABOVE]" in ch3
    assert "VERIFY FIRST: does your harness have ANY spawn / subagent / delegate mechanism" in ch3
    assert "SELF-ADOPT is the LAST resort" in ch3
    assert "SELF-ADOPT the queued jobs" in ch3
    assert "GRANTED by your choice" in ch3 and "subagent mode" in ch3
    assert "never applies in" in ch3 and "multi_terminal mode" in ch3
    assert "GRANTED by your choice of generic_mcp mode" not in ch3
    assert "get_job_mission" in ch3 and "complete_job" in ch3
    assert "[FLOOR]" in ch3
    assert "[YOUR PATH — Generic MCP]" in ch3
    assert "CANNOT self-adopt a CODE job" not in ch3


def test_generic_mcp_ch3_chat_preset_tunes_self_adopt_to_planning_only():
    chat = reg.get_preset("chat")
    ch3 = _build_ch3_spawning_rules("generic_mcp", preset=chat)
    assert "[YOUR PATH — Chat]" in ch3
    assert "CANNOT self-adopt a CODE job" in ch3
    assert "PLANNING / PM jobs" in ch3
    assert "SELF-ADOPT" in ch3 and "GRANTED by your choice of subagent mode" in ch3
    assert "GRANTED by your choice of generic_mcp mode" not in ch3
    assert "SELF-ADOPT the queued jobs" not in ch3


def test_generic_mcp_ch3_shell_bearing_preset_keeps_capable_self_adopt():
    desktop = reg.get_preset("desktop_app")
    assert desktop.has_shell is True
    ch3 = _build_ch3_spawning_rules("generic_mcp", preset=desktop)
    assert "[YOUR PATH — Desktop App]" in ch3
    assert "SELF-ADOPT the queued jobs" in ch3
    assert "CANNOT self-adopt a CODE job" not in ch3


def test_preset_kwarg_is_inert_for_non_generic_tools():
    chat = reg.get_preset("chat")
    for tool in ("multi_terminal", "claude-code", "codex"):
        assert _build_ch3_spawning_rules(tool) == _build_ch3_spawning_rules(tool, preset=chat)
