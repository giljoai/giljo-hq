# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.services.protocol_builder import (
    _build_ch1_mission,
    _build_ch3_spawning_rules,
    _build_orchestrator_protocol,
)




class TestCh1ToolAware:

    def test_claude_warns_about_task_tool(self):
        ch1 = _build_ch1_mission(tool="claude-code")
        assert "Task()" in ch1
        assert "spawn_agent()" not in ch1

    def test_codex_warns_about_spawn_agent(self):
        ch1 = _build_ch1_mission(tool="codex")
        assert "spawn_agent()" in ch1
        assert "Task()" not in ch1

    def test_multi_terminal_generic_warning(self):
        ch1 = _build_ch1_mission(tool="multi_terminal")
        assert "implementation work directly" in ch1
        assert "Task()" not in ch1
        assert "spawn_agent()" not in ch1

    def test_default_is_claude(self):
        ch1_default = _build_ch1_mission()
        ch1_claude = _build_ch1_mission(tool="claude-code")
        assert ch1_default == ch1_claude




class TestCh3ToolAware:

    def test_codex_has_gil_prefix_instructions(self):
        ch3 = _build_ch3_spawning_rules(tool="codex")
        assert "gil-" in ch3
        assert "spawn_agent(" in ch3
        assert "CODEX CLI" in ch3

    def test_codex_explains_where_the_role_comes_from(self):
        ch3 = _build_ch3_spawning_rules(tool="codex")
        assert "agent_profile" in ch3
        assert "get_job_mission" in ch3
        assert "model/effort hints" in ch3
        assert ".toml" not in ch3, "No agent file is installed any more -- BE-9605c."

    def test_codex_has_generic_worker_guardrail(self):
        ch3 = " ".join(_build_ch3_spawning_rules(tool="codex").split())
        assert "never instruct a generic worker" in ch3
        assert "unprefixed built-in name" in ch3

    def test_codex_no_claude_references(self):
        ch3 = _build_ch3_spawning_rules(tool="codex")
        assert "Task(subagent_type=" not in ch3
        assert ".claude/agents/" not in ch3
        assert "subagent_type=" not in ch3

    def test_claude_has_task_syntax(self):
        ch3 = _build_ch3_spawning_rules(tool="claude-code")
        assert "Task(" in ch3
        assert "subagent_type" in ch3
        assert "agent_profile" in ch3

    def test_claude_no_codex_references(self):
        ch3 = _build_ch3_spawning_rules(tool="claude-code")
        assert "gil-" not in ch3
        assert "spawn_agent(agent=" not in ch3
        assert ".codex/" not in ch3

    def test_multi_terminal_generic_mcp(self):
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "MCP server" in ch3
        assert "get_job_mission()" in ch3
        assert "post_to_thread" in ch3

    def test_multi_terminal_no_cli_references(self):
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "Task(subagent_type=" not in ch3
        assert "spawn_agent(agent=" not in ch3
        assert "@agent" not in ch3

    def test_execution_mode_block_before_parameter_requirements(self):
        ch3 = _build_ch3_spawning_rules(tool="codex")
        platform_pos = ch3.find("YOUR PLATFORM")
        params_pos = ch3.find("PARAMETER REQUIREMENTS")
        assert platform_pos < params_pos, "Platform block must appear before parameter requirements"

    def test_role_source_is_the_server_for_every_platform(self):
        for tool in ("codex", "claude-code", "multi_terminal"):
            ch3 = _build_ch3_spawning_rules(tool=tool)
            assert "Role source:" in ch3, f"{tool} lost the Role source line"
            assert "get_job_mission" in ch3, f"{tool} does not name the role's origin"
            assert "File mapping:" not in ch3, f"{tool} still promises a file mapping"




class TestFullProtocolAssembly:

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

    def test_multi_terminal_uses_generic_language(self):
        result = _build_orchestrator_protocol(cli_mode=False, tool="claude-code", **self.COMMON_KWARGS)
        ch3 = result["ch3_agent_spawning_rules"]
        assert "MCP server" in ch3
        assert "ANY MCP-CONNECTED AGENT" in ch3
