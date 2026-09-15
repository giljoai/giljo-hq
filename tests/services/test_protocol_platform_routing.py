# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol
from giljo_mcp.services.protocol_sections.chapters_reference import (
    _REACTIVATION_SPAWN_BLOCKS,
    _build_ch3_spawning_rules,
    _build_reactivation_spawn_block,
)




def _render_orchestrator_protocol(execution_mode: str) -> str:
    return _generate_agent_protocol(
        job_id="job-test",
        tenant_key="tk_test",
        agent_name="orchestrator",
        agent_id="exec-test",
        execution_mode=execution_mode,
        git_integration_enabled=False,
        job_type="orchestrator",
        tool=execution_mode if execution_mode in ("codex", "claude-code") else "multi_terminal",
    )




class TestExecutionModeRouting:

    def test_protocol_renders_task_syntax_for_claude_code_cli(self):
        ch3 = _build_ch3_spawning_rules(tool="claude-code")
        assert "Task(subagent_type=" in ch3
        assert "CLAUDE CODE CLI" in ch3

    def test_protocol_renders_no_task_syntax_for_multi_terminal(self):
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "Task(subagent_type=" not in ch3
        assert "spawn_agent(agent=" not in ch3
        assert "ANY MCP-CONNECTED AGENT" in ch3

    def test_protocol_falls_back_to_generic_for_unknown_mode(self):
        ch3 = _build_ch3_spawning_rules(tool="some_future_mode")
        assert "ANY MCP-CONNECTED AGENT" in ch3
        assert "Task(subagent_type=" not in ch3
        assert "CLAUDE CODE CLI" not in ch3

    def test_protocol_renders_codex_syntax_for_codex_cli(self):
        ch3 = _build_ch3_spawning_rules(tool="codex")
        assert "spawn_agent(" in ch3
        assert "gil-" in ch3
        assert "CODEX CLI" in ch3
        assert "Task(subagent_type=" not in ch3




class TestReactivationSpawnBlockFallback:

    def test_reactivation_spawn_block_generic_for_unknown_subagent_tool(self):
        from giljo_mcp.services.protocol_sections.chapters_reference import _REACTIVATION_GENERIC

        block = _build_reactivation_spawn_block(tool="unknown")
        assert block == _REACTIVATION_GENERIC
        assert "Task(subagent_type=" not in block
        assert "MANDATORY" in block

    def test_reactivation_spawn_block_multi_terminal_for_empty_tool(self):
        block = _build_reactivation_spawn_block(tool="")
        assert block == _REACTIVATION_SPAWN_BLOCKS["multi_terminal"]
        assert "Task(subagent_type=" not in block

    def test_reactivation_spawn_block_for_known_claude_code(self):
        block = _build_reactivation_spawn_block(tool="claude-code")
        assert block == _REACTIVATION_SPAWN_BLOCKS["claude-code"]
        assert "Task(subagent_type=" in block

    def test_reactivation_spawn_block_for_multi_terminal(self):
        block = _build_reactivation_spawn_block(tool="multi_terminal")
        assert "Task(subagent_type=" not in block
        assert "spawn_agent(" not in block
        assert "Open a new session" in block




class TestGenericBranchJobOrderFraming:

    def test_generic_branch_uses_job_order_framing(self):
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "job order" in ch3.lower()

    def test_generic_branch_is_explicit_about_mcp_only_coordination(self):
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "spawn_job" in ch3
        assert "post_to_thread" in ch3

    def test_generic_branch_includes_predecessor_handling_guidance(self):
        ch3 = _build_ch3_spawning_rules(tool="multi_terminal")
        assert "predecessor_job_id" in ch3
        assert "PHASE HANDOFF" in ch3

    def test_phase_parameter_block_renders_in_all_branches(self):
        for tool in ("multi_terminal", "claude-code", "codex"):
            ch3 = _build_ch3_spawning_rules(tool=tool)
            assert "── phase (optional" in ch3, f"phase block missing in {tool} branch"
            assert "Same phase number" in ch3
            assert "Higher phase number" in ch3

    def test_predecessor_guidance_is_multi_terminal_only(self):
        for tool in ("claude-code", "codex"):
            ch3 = _build_ch3_spawning_rules(tool=tool)
            assert "PHASE HANDOFF:" not in ch3, (
                f"{tool} branch must not contain the multi_terminal-specific "
                f"PHASE HANDOFF block -- server skips preamble injection in "
                f"subagent modes"
            )




class TestAgentProtocolDefaults:

    def test_generate_agent_protocol_default_is_multi_terminal(self):
        protocol = _generate_agent_protocol(
            job_id="job-test",
            tenant_key="tk_test",
            agent_name="implementer",
            agent_id="exec-test",
            git_integration_enabled=False,
            job_type="agent",
        )
        assert "Task(subagent_type=" not in protocol
        assert "spawn_agent(agent=" not in protocol

    def test_orchestrator_protocol_default_does_not_leak_task_syntax(self):
        protocol = _render_orchestrator_protocol(execution_mode="multi_terminal")
        assert "Task() processes" not in protocol
        assert "spawn_agent() processes" not in protocol




class TestServiceLayerExecModeMapping:

    def test_mission_service_routes_multi_terminal_to_itself(self):
        from giljo_mcp.platform_registry import EXECUTION_MODE_TO_TOOL, tool_for_mode

        assert EXECUTION_MODE_TO_TOOL["multi_terminal"] == "multi_terminal"
        assert tool_for_mode("multi_terminal") == "multi_terminal"

    def test_mission_service_fallback_default_is_multi_terminal(self):
        import re
        from pathlib import Path

        src = Path("src/giljo_mcp/services/mission_service.py").read_text(encoding="utf-8")
        assert '_EXECUTION_MODE_TO_TOOL.get(project_exec_mode, "claude-code")' not in src
        defaults = re.findall(r'_EXECUTION_MODE_TO_TOOL\.get\(.*?,\s*"([\w-]+)"\s*\)', src, re.DOTALL)
        assert defaults, "expected at least one _EXECUTION_MODE_TO_TOOL.get() lookup in mission_service"
        assert set(defaults) == {"multi_terminal"}, f"fail-safe default must be multi_terminal, found {set(defaults)}"

    def test_mission_orchestration_service_fallback_default_is_multi_terminal(self):
        from pathlib import Path

        from giljo_mcp.platform_registry import tool_for_mode

        assert tool_for_mode("totally_unknown_mode") == "multi_terminal"
        assert tool_for_mode("multi_terminal") == "multi_terminal"
        src = Path("src/giljo_mcp/services/mission_orchestration_service.py").read_text(encoding="utf-8")
        assert 'execution_mode_to_tool.get(execution_mode, "claude-code")' not in src




class TestSignatureDefaults:

    def test_chapters_reference_ch3_default_is_multi_terminal(self):
        import inspect

        sig = inspect.signature(_build_ch3_spawning_rules)
        assert sig.parameters["tool"].default == "multi_terminal"

    def test_generate_agent_protocol_default_tool_is_multi_terminal(self):
        import inspect

        sig = inspect.signature(_generate_agent_protocol)
        assert sig.parameters["tool"].default == "multi_terminal"




class TestGiljoSignoffToken:
    def _giljo_block(self, tool: str) -> str:
        from giljo_mcp.services.protocol_sections.agent_protocol import _build_conditional_blocks

        _git, giljo_block = _build_conditional_blocks(False, "multi_terminal", tool)
        return giljo_block

    def test_codex_signoff_uses_dollar_giljo(self):
        block = self._giljo_block("codex")
        assert "$giljo" in block and "/giljo" not in block

    def test_claude_and_retired_tokens_signoff_use_slash_giljo(self):
        for tool in ("claude", "gemini", "antigravity"):
            block = self._giljo_block(tool)
            assert "/giljo" in block and "$giljo" not in block




class TestOrchestratorClosingGiljoSignoffToken:
    def _orchestrator_protocol(self, tool: str) -> str:
        return _generate_agent_protocol(
            job_id="job-test",
            tenant_key="tk_test",
            agent_name="orchestrator",
            agent_id="exec-test",
            execution_mode="subagent",
            git_integration_enabled=False,
            job_type="orchestrator",
            tool=tool,
        )

    def test_codex_orchestrator_signoff_uses_dollar_giljo(self):
        for tool in ("codex",):
            protocol = self._orchestrator_protocol(tool)
            assert "$giljo" in protocol and "/giljo" not in protocol, f"tool={tool!r}"

    def test_claude_code_orchestrator_signoff_uses_slash_giljo(self):
        for tool in ("claude-code",):
            protocol = self._orchestrator_protocol(tool)
            assert "/giljo" in protocol and "$giljo" not in protocol, f"tool={tool!r}"




class TestBE9260ProtocolNeutralityByHarness:

    def _worker_protocol(self, tool: str) -> str:
        return _generate_agent_protocol(
            job_id="job-test",
            tenant_key="tk_test",
            agent_name="implementer",
            agent_id="exec-test",
            execution_mode="subagent",
            git_integration_enabled=True,
            job_type="agent",
            tool=tool,
        )

    def _orchestrator_protocol(self, tool: str) -> str:
        return _generate_agent_protocol(
            job_id="job-test",
            tenant_key="tk_test",
            agent_name="orchestrator",
            agent_id="exec-test",
            execution_mode="subagent",
            git_integration_enabled=True,
            job_type="orchestrator",
            tool=tool,
        )

    def _staging_prompt(self, tool: str) -> str:
        from unittest.mock import MagicMock

        from giljo_mcp.prompts.staging_prompt_builder import StagingPromptBuilder

        builder = StagingPromptBuilder()
        project = MagicMock()
        project.id = "proj-abc"
        project.name = "Test Project"
        project.description = "Test desc"
        project.mission = ""
        project.taxonomy_alias = None
        project.project_type_id = None
        project.series_number = None
        product = MagicMock()
        product.id = "prod-xyz"
        return builder.build_thin_prompt(
            orchestrator_id="orch-1",
            agent_id="agent-1",
            project_id="proj-abc",
            project=project,
            product=product,
            tool=tool,
            field_toggles={},
            depth_config={},
            user_id=None,
        )


    def test_worker_protocol_omits_todowrite_for_non_claude_tool(self):
        for tool in ("codex",):
            protocol = self._worker_protocol(tool)
            assert "TodoWrite" not in protocol, f"tool={tool!r} leaked Claude-Code TodoWrite wording"

    def test_orchestrator_protocol_omits_todowrite_for_non_claude_tool(self):
        for tool in ("codex",):
            protocol = self._orchestrator_protocol(tool)
            assert "TodoWrite" not in protocol, f"tool={tool!r} leaked Claude-Code TodoWrite wording"

    def test_staging_prompt_omits_todowrite_for_non_claude_tool(self):
        for tool in ("codex",):
            prompt = self._staging_prompt(tool)
            assert "TodoWrite" not in prompt, f"tool={tool!r} leaked Claude-Code TodoWrite wording"

    def test_orchestrator_protocol_does_not_mandate_pytest_or_ruff(self):
        for tool in ("codex",):
            protocol = self._orchestrator_protocol(tool)
            assert "pytest" not in protocol.lower(), f"tool={tool!r} leaked a pytest mandate"
            assert "ruff" not in protocol.lower(), f"tool={tool!r} leaked a ruff mandate"

    def test_orchestrator_protocol_does_not_hardcode_repo_protected_files(self):
        for tool in ("codex",):
            protocol = self._orchestrator_protocol(tool)
            assert "CLAUDE.md" not in protocol, f"tool={tool!r} leaked our repo's protected-file list"
            assert "pyproject.toml" not in protocol, f"tool={tool!r} leaked our repo's protected-file list"
            assert "alembic.ini" not in protocol, f"tool={tool!r} leaked our repo's protected-file list"

    def test_orchestrator_protocol_does_not_leak_this_repo_ticket_refs_or_branch(self):
        for tool in ("codex",):
            protocol = self._orchestrator_protocol(tool)
            assert "BE-9083c" not in protocol, f"tool={tool!r} leaked an internal ticket ref"
            assert "master bug" not in protocol, f"tool={tool!r} assumed 'master' as THE branch"


    def test_worker_protocol_keeps_todowrite_for_claude_code(self):
        protocol = self._worker_protocol("claude-code")
        assert "TodoWrite" in protocol

    def test_staging_prompt_keeps_todowrite_for_claude_code(self):
        prompt = self._staging_prompt("claude-code")
        assert "TodoWrite" in prompt
