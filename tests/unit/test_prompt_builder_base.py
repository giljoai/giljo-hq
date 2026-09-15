# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from types import SimpleNamespace

import pytest


def _make_project(name="Test Project", project_id="proj-123", product_id="prod-456", taxonomy_alias="BE-0042"):
    return SimpleNamespace(
        name=name,
        id=project_id,
        product_id=product_id,
        taxonomy_alias=taxonomy_alias,
    )


def _make_agent_job(agent_name="tdd-implementor", display_name="implementer", job_id="job-abc", status="waiting"):
    job = SimpleNamespace(mission="Implement the feature following TDD methodology")
    return SimpleNamespace(
        agent_name=agent_name,
        agent_display_name=display_name,
        job_id=job_id,
        status=status,
        job=job,
    )


class TestBaseClassExists:

    def test_base_class_importable(self):
        from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase

        assert ExecutionPromptBuilderBase is not None

    def test_claude_inherits_from_base(self):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
        from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase

        assert issubclass(ClaudePromptBuilder, ExecutionPromptBuilderBase)

    def test_codex_inherits_from_base(self):
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder
        from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase

        assert issubclass(CodexPromptBuilder, ExecutionPromptBuilderBase)

    def test_multi_terminal_unchanged(self):
        from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase
        from giljo_mcp.prompts.multi_terminal_prompt_builder import MultiTerminalPromptBuilder

        assert not issubclass(MultiTerminalPromptBuilder, ExecutionPromptBuilderBase)


class TestPublicInterfacePreserved:

    @pytest.fixture
    def project(self):
        return _make_project()

    @pytest.fixture
    def agent_jobs(self):
        return [_make_agent_job()]

    def test_claude_builds_prompt(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder

        builder = ClaudePromptBuilder()
        result = builder.build_execution_prompt("orch-1", project, agent_jobs, git_enabled=True)
        assert isinstance(result, str)
        assert len(result) > 100
        assert "Claude Code" in result

    def test_codex_builds_prompt(self, project, agent_jobs):
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder

        builder = CodexPromptBuilder()
        result = builder.build_execution_prompt("orch-1", project, agent_jobs, git_enabled=True)
        assert isinstance(result, str)
        assert len(result) > 100
        assert "Codex" in result

    def test_multi_terminal_builds_prompt(self, project, agent_jobs):
        from giljo_mcp.prompts.multi_terminal_prompt_builder import MultiTerminalPromptBuilder

        builder = MultiTerminalPromptBuilder()
        result = builder.build_execution_prompt("orch-1", project, agent_jobs, git_enabled=True)
        assert isinstance(result, str)
        assert "Orchestrator" in result


class TestSharedSections:

    @pytest.fixture
    def project(self):
        return _make_project()

    @pytest.fixture
    def agent_jobs(self):
        return [_make_agent_job()]

    def test_all_builders_contain_health_check(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder

        for builder_cls in [ClaudePromptBuilder, CodexPromptBuilder]:
            result = builder_cls().build_execution_prompt("orch-1", project, agent_jobs)
            assert "health_check()" in result, f"{builder_cls.__name__} missing health_check"
            assert "mcp__giljo_mcp__health_check()" not in result, (
                f"{builder_cls.__name__} still prefixes health_check (should be bare for all platforms)"
            )

    def test_all_builders_contain_identity(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder

        for builder_cls in [ClaudePromptBuilder, CodexPromptBuilder]:
            result = builder_cls().build_execution_prompt("orch-1", project, agent_jobs)
            assert "## Who You Are" in result
            assert "orch-1" in result
            assert "Test Project" in result

    def test_all_builders_contain_monitoring(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder

        for builder_cls in [ClaudePromptBuilder, CodexPromptBuilder]:
            result = builder_cls().build_execution_prompt("orch-1", project, agent_jobs)
            assert "## Monitoring Agent Progress" in result
            assert "get_workflow_status" in result

    def test_all_builders_contain_context_refresh(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder

        for builder_cls in [ClaudePromptBuilder, CodexPromptBuilder]:
            result = builder_cls().build_execution_prompt("orch-1", project, agent_jobs)
            assert "## Refreshing Your Context" in result

    def test_all_builders_contain_completion(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder

        for builder_cls in [ClaudePromptBuilder, CodexPromptBuilder]:
            result = builder_cls().build_execution_prompt("orch-1", project, agent_jobs)
            assert "## When You're Done" in result
            assert "complete_job" in result

    def test_git_closeout_present_when_enabled(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder

        for builder_cls in [ClaudePromptBuilder, CodexPromptBuilder]:
            result = builder_cls().build_execution_prompt("orch-1", project, agent_jobs, git_enabled=True)
            assert "Git Closeout" in result, f"{builder_cls.__name__} missing git closeout"

    def test_git_closeout_absent_when_disabled(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder

        result = ClaudePromptBuilder().build_execution_prompt("orch-1", project, agent_jobs, git_enabled=False)
        assert "Git Closeout" not in result


class TestPlatformSpecificSections:

    @pytest.fixture
    def project(self):
        return _make_project()

    @pytest.fixture
    def agent_jobs(self):
        return [_make_agent_job()]

    def test_claude_uses_task_tool(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder

        result = ClaudePromptBuilder().build_execution_prompt("orch-1", project, agent_jobs)
        assert "Task(" in result
        assert "subagent_type" in result

    def test_codex_uses_spawn_agent(self, project, agent_jobs):
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder

        result = CodexPromptBuilder().build_execution_prompt("orch-1", project, agent_jobs)
        assert "spawn_agent(" in result
        assert "gil-" in result

    def test_claude_has_cli_constraints(self, project, agent_jobs):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder

        result = ClaudePromptBuilder().build_execution_prompt("orch-1", project, agent_jobs)
        assert "CLI Mode Constraints" in result

    def test_codex_has_no_cli_constraints(self, project, agent_jobs):
        from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder

        result = CodexPromptBuilder().build_execution_prompt("orch-1", project, agent_jobs)
        assert "CLI Mode Constraints" not in result


class TestEdgeCases:

    def test_empty_agent_jobs(self):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder

        project = _make_project()
        result = ClaudePromptBuilder().build_execution_prompt("orch-1", project, [], git_enabled=False)
        assert "No agents spawned" in result

    def test_none_agent_jobs(self):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder

        project = _make_project()
        result = ClaudePromptBuilder().build_execution_prompt("orch-1", project, None, git_enabled=False)
        assert "No agents spawned" in result

    def test_long_mission_truncated(self):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder

        project = _make_project()
        long_mission = "A" * 200
        job = SimpleNamespace(mission=long_mission)
        agent = SimpleNamespace(agent_name="test", agent_display_name="tester", job_id="j1", status="waiting", job=job)
        result = ClaudePromptBuilder().build_execution_prompt("orch-1", project, [agent])
        assert "..." in result

    def test_no_taxonomy_alias_fallback(self):
        from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder

        project = SimpleNamespace(name="My Project", id="p1", product_id="pr1", taxonomy_alias=None)
        result = ClaudePromptBuilder().build_execution_prompt("orch-1", project, [], git_enabled=True)
        assert "closeout(My Project)" in result


class TestPackageExports:

    def test_all_builders_exported(self):
        from giljo_mcp.prompts import (
            ClaudePromptBuilder,
            CodexPromptBuilder,
            MultiTerminalPromptBuilder,
            StagingPromptBuilder,
        )

        assert ClaudePromptBuilder is not None
        assert CodexPromptBuilder is not None
        assert MultiTerminalPromptBuilder is not None
        assert StagingPromptBuilder is not None

    def test_base_class_exported(self):
        from giljo_mcp.prompts import ExecutionPromptBuilderBase

        assert ExecutionPromptBuilderBase is not None
