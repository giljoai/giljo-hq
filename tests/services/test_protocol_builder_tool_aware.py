# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for tool-aware orchestrator protocol (Handover 0847).

Verifies:
1. Each platform gets only its own native spawning language
2. No cross-platform leakage (Codex never sees Task(), Claude never sees spawn_agent())
3. CH1 uses platform-specific "do not" warnings
4. CH3 execution mode block is platform-primary (appears before parameter requirements)
5. Multi-terminal mode uses generic MCP language
"""

from giljo_mcp.services.protocol_builder import (
    _build_ch1_mission,
    _build_ch3_spawning_rules,
    _build_orchestrator_protocol,
)


# --- CH1: Platform-specific "do not spawn" warning ---


class TestCh1ToolAware:
    """CH1 adapts the 'do not spawn during staging' warning per platform."""

    def test_claude_warns_about_task_tool(self):
        ch1 = _build_ch1_mission(tool="claude-code")
        assert "Task()" in ch1
        assert "spawn_agent()" not in ch1

    def test_codex_warns_about_spawn_agent(self):
        ch1 = _build_ch1_mission(tool="codex")
        assert "spawn_agent()" in ch1
        assert "Task()" not in ch1

    def test_gemini_warns_about_at_agent(self):
        ch1 = _build_ch1_mission(tool="gemini")
        assert "@agent" in ch1
        assert "Task()" not in ch1
        assert "spawn_agent()" not in ch1

    def test_multi_terminal_generic_warning(self):
        ch1 = _build_ch1_mission(tool="multi_terminal")
        assert "implementation work directly" in ch1
        assert "Task()" not in ch1
        assert "spawn_agent()" not in ch1

    def test_default_is_claude(self):
        ch1_default = _build_ch1_mission()
        ch1_claude = _build_ch1_mission(tool="claude-code")
        assert ch1_default == ch1_claude


# --- CH3: Platform-specific spawning rules ---


class TestCh3ToolAware:
    """CH3 shows only the current platform's spawning rules."""

    def test_codex_has_gil_prefix_instructions(self):
        ch3 = _build_ch3_spawning_rules(tool="codex")
        assert "gil-" in ch3
        assert "spawn_agent(" in ch3
        assert "CODEX CLI" in ch3

    def test_codex_explains_agent_param_mechanically(self):
        """Codex block must explain what agent= actually does (loads .toml template)."""
        ch3 = _build_ch3_spawning_rules(tool="codex")
        assert ".toml" in ch3
        assert "developer_instructions" in ch3
        assert "ALREADY KNOWS its role" in ch3

    def test_codex_has_generic_worker_guardrail(self):
        """Codex block must warn against spawning a generic worker IN PLACE OF an
        installed template.

        BE-9402 narrowed this guardrail on purpose. It used to read "NEVER spawn a
        generic/default worker" unconditionally, paired with a STOP when no template
        was installed -- which halted a run over a missing FILE. The rule is now a
        ladder: while the gil-* template EXISTS it must be used, and only when it is
        absent does the harness's own default agent take over (with a notice). So the
        surviving guardrail is about SUBSTITUTION, not about default agents as such.
        Pinned end-to-end in tests/services/test_be9402_default_agent_ladder_prose.py.
        """
        # Collapse whitespace first: the prose is hard-wrapped, so the sentence
        # under test spans a newline in the rendered block.
        ch3 = " ".join(_build_ch3_spawning_rules(tool="codex").split())
        assert "never instruct a generic worker" in ch3
        assert "unprefixed built-in name" in ch3

    def test_codex_no_claude_references(self):
        """Codex protocol must not mention Claude-specific spawn syntax.
        HO1025: bare `Task()` / `spawn_agent()` / `@-syntax` may appear in the
        cross-platform `phase` educational block; only platform-specific
        invocation forms (Task(subagent_type=...), .claude/ paths) are gated.
        """
        ch3 = _build_ch3_spawning_rules(tool="codex")
        assert "Task(subagent_type=" not in ch3
        assert ".claude/agents/" not in ch3
        assert "subagent_type=" not in ch3

    def test_claude_has_task_syntax(self):
        ch3 = _build_ch3_spawning_rules(tool="claude-code")
        assert "Task(" in ch3
        assert "subagent_type" in ch3
        assert ".claude/agents/" in ch3

    def test_claude_no_codex_references(self):
        """HO1025: `spawn_agent()` may appear in the cross-platform `phase`
        educational block; gate the codex-specific invocation form instead."""
        ch3 = _build_ch3_spawning_rules(tool="claude-code")
        assert "gil-" not in ch3
        assert "spawn_agent(agent=" not in ch3
        assert ".codex/" not in ch3

    def test_gemini_has_at_agent_syntax(self):
        ch3 = _build_ch3_spawning_rules(tool="gemini")
        assert "@" in ch3
        assert "/agent" in ch3
        assert ".gemini/agents/" in ch3

    def test_gemini_no_codex_or_claude_references(self):
        """HO1025: bare `Task()` / `spawn_agent()` may appear in the
        cross-platform `phase` educational block; gate the platform-specific
        invocation forms instead."""
        ch3 = _build_ch3_spawning_rules(tool="gemini")
        assert "Task(subagent_type=" not in ch3
        assert "spawn_agent(agent=" not in ch3
        assert ".claude/" not in ch3
        assert ".codex/" not in ch3
        assert "gil-" not in ch3

    def test_multi_terminal_generic_mcp(self):
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "MCP server" in ch3
        assert "get_job_mission()" in ch3
        assert "post_to_thread" in ch3  # BE-9012d: bus (send_message) retired, Hub replaces it

    def test_multi_terminal_no_cli_references(self):
        """HO1025: bare `Task()` / `spawn_agent()` may appear in the
        cross-platform `phase` educational block; gate the platform-specific
        invocation forms instead."""
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "Task(subagent_type=" not in ch3
        assert "spawn_agent(agent=" not in ch3
        assert "@agent" not in ch3

    def test_execution_mode_block_before_parameter_requirements(self):
        """Platform block should appear BEFORE parameter requirements (not buried)."""
        ch3 = _build_ch3_spawning_rules(tool="codex")
        platform_pos = ch3.find("YOUR PLATFORM")
        params_pos = ch3.find("PARAMETER REQUIREMENTS")
        assert platform_pos < params_pos, "Platform block must appear before parameter requirements"

    def test_codex_file_mapping_is_codex_path(self):
        ch3 = _build_ch3_spawning_rules(tool="codex")
        assert "~/.codex/agents/gil-" in ch3

    def test_gemini_file_mapping_is_gemini_path(self):
        ch3 = _build_ch3_spawning_rules(tool="gemini")
        assert "~/.gemini/agents/" in ch3

    def test_claude_file_mapping_is_claude_path(self):
        ch3 = _build_ch3_spawning_rules(tool="claude-code")
        assert ".claude/agents/" in ch3


# --- Full protocol assembly ---


class TestFullProtocolAssembly:
    """Integration test: _build_orchestrator_protocol passes tool correctly."""

    COMMON_KWARGS = {
        "project_id": "test-proj-id",
        "orchestrator_id": "test-orch-id",
        "tenant_key": "tk_test",
        "include_implementation_reference": True,
    }

    def test_codex_protocol_no_task_tool_anywhere(self):
        result = _build_orchestrator_protocol(cli_mode=True, tool="codex", **self.COMMON_KWARGS)
        combined = "\n".join(result.values())
        assert "Task(subagent_type" not in combined
        assert ".claude/agents/" not in combined

    def test_claude_protocol_no_spawn_agent_anywhere(self):
        result = _build_orchestrator_protocol(cli_mode=True, tool="claude-code", **self.COMMON_KWARGS)
        combined = "\n".join(result.values())
        assert "spawn_agent(agent=" not in combined
        assert "gil-" not in combined
        assert ".codex/" not in combined

    def test_gemini_protocol_no_claude_or_codex(self):
        result = _build_orchestrator_protocol(cli_mode=True, tool="gemini", **self.COMMON_KWARGS)
        combined = "\n".join(result.values())
        assert "Task(subagent_type" not in combined
        assert "spawn_agent(agent=" not in combined
        assert ".claude/agents/" not in combined
        assert ".codex/" not in combined

    def test_multi_terminal_uses_generic_language(self):
        result = _build_orchestrator_protocol(cli_mode=False, tool="claude-code", **self.COMMON_KWARGS)
        ch3 = result["ch3_agent_spawning_rules"]
        assert "MCP server" in ch3
        assert "ANY MCP-CONNECTED AGENT" in ch3
