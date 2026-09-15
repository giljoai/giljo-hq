# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest


def _gen_protocol(
    execution_mode: str = "multi_terminal",
    git_integration_enabled: bool = False,
    job_type: str = "agent",
) -> str:
    from giljo_mcp.services.protocol_builder import _generate_agent_protocol

    return _generate_agent_protocol(
        job_id="test-job-id",
        tenant_key="tk_test",
        agent_name="backend-engineer",
        agent_id="test-agent-id",
        execution_mode=execution_mode,
        git_integration_enabled=git_integration_enabled,
        job_type=job_type,
    )




class TestGitCommitInjection:

    def test_git_enabled_includes_commit_instruction(self):
        protocol = _gen_protocol(git_integration_enabled=True)
        assert "git add" in protocol.lower() or "Git Commit" in protocol
        assert "commit" in protocol.lower()

    def test_git_disabled_excludes_commit_instruction(self):
        protocol = _gen_protocol(git_integration_enabled=False)
        assert "Git Commit" not in protocol
        assert "git add" not in protocol

    def test_git_enabled_mentions_commits_in_result(self):
        protocol = _gen_protocol(git_integration_enabled=True)
        assert "commits" in protocol




class TestGiljoInjection:

    def test_multi_terminal_includes_giljo(self):
        protocol = _gen_protocol(execution_mode="multi_terminal")
        assert "/giljo" in protocol

    def test_cli_mode_excludes_giljo(self):
        protocol = _gen_protocol(execution_mode="claude_code_cli")
        assert "/giljo" not in protocol

    def test_multi_terminal_mentions_user_guidance(self):
        protocol = _gen_protocol(execution_mode="multi_terminal")
        assert "technical debt" in protocol.lower() or "follow-up" in protocol.lower()




class TestCombinedInjections:

    def test_both_enabled(self):
        protocol = _gen_protocol(execution_mode="multi_terminal", git_integration_enabled=True)
        assert "/giljo" in protocol
        assert "Git Commit" in protocol

    def test_both_disabled(self):
        protocol = _gen_protocol(execution_mode="claude_code_cli", git_integration_enabled=False)
        assert "/giljo" not in protocol
        assert "Git Commit" not in protocol

    def test_git_only(self):
        protocol = _gen_protocol(execution_mode="claude_code_cli", git_integration_enabled=True)
        assert "Git Commit" in protocol
        assert "/giljo" not in protocol

    def test_giljo_only(self):
        protocol = _gen_protocol(execution_mode="multi_terminal", git_integration_enabled=False)
        assert "/giljo" in protocol
        assert "Git Commit" not in protocol




class TestProtocolRegression:

    @pytest.mark.parametrize(
        ("execution_mode", "git_enabled"),
        [
            ("multi_terminal", True),
            ("multi_terminal", False),
            ("claude_code_cli", True),
            ("claude_code_cli", False),
        ],
    )
    def test_phase1_always_present(self, execution_mode, git_enabled):
        protocol = _gen_protocol(execution_mode=execution_mode, git_integration_enabled=git_enabled)
        assert "Phase 1: STARTUP" in protocol
        assert "get_job_mission" in protocol

    @pytest.mark.parametrize(
        ("execution_mode", "git_enabled"),
        [
            ("multi_terminal", True),
            ("multi_terminal", False),
            ("claude_code_cli", True),
            ("claude_code_cli", False),
        ],
    )
    def test_phase2_always_present(self, execution_mode, git_enabled):
        protocol = _gen_protocol(execution_mode=execution_mode, git_integration_enabled=git_enabled)
        assert "Phase 2: EXECUTION" in protocol

    @pytest.mark.parametrize(
        ("execution_mode", "git_enabled"),
        [
            ("multi_terminal", True),
            ("multi_terminal", False),
            ("claude_code_cli", True),
            ("claude_code_cli", False),
        ],
    )
    def test_phase3_always_present(self, execution_mode, git_enabled):
        protocol = _gen_protocol(execution_mode=execution_mode, git_integration_enabled=git_enabled)
        assert "Phase 3: PROGRESS REPORTING" in protocol
        assert "report_progress" in protocol

    @pytest.mark.parametrize(
        ("execution_mode", "git_enabled"),
        [
            ("multi_terminal", True),
            ("multi_terminal", False),
            ("claude_code_cli", True),
            ("claude_code_cli", False),
        ],
    )
    def test_phase4_core_always_present(self, execution_mode, git_enabled):
        protocol = _gen_protocol(execution_mode=execution_mode, git_integration_enabled=git_enabled)
        assert "Phase 4: COMPLETION" in protocol
        assert "complete_job" in protocol

    @pytest.mark.parametrize(
        ("execution_mode", "git_enabled"),
        [
            ("multi_terminal", True),
            ("multi_terminal", False),
            ("claude_code_cli", True),
            ("claude_code_cli", False),
        ],
    )
    def test_phase5_always_present(self, execution_mode, git_enabled):
        protocol = _gen_protocol(execution_mode=execution_mode, git_integration_enabled=git_enabled)
        assert "Phase 5: ERROR HANDLING" in protocol
        assert "set_agent_status" in protocol


class TestSpawnJobBeforeLaunchMandate:

    @pytest.mark.parametrize("execution_mode", ["claude_code_cli", "multi_terminal"])
    def test_spawn_job_before_launch_mandate_present(self, execution_mode):
        protocol = _gen_protocol(execution_mode=execution_mode, job_type="orchestrator")
        assert "without a preceding spawn_job" in protocol
        assert "spawn_job" in protocol and "FIRST" in protocol

    @pytest.mark.parametrize("execution_mode", ["claude_code_cli", "multi_terminal"])
    def test_launch_directly_phrasing_removed(self, execution_mode):
        protocol = _gen_protocol(execution_mode=execution_mode, job_type="orchestrator")
        assert "In subagent mode: launch directly." not in protocol




class TestOrchestratorTodoWriteScoping:

    def test_orchestrator_todowrite_scoped_to_coordination(self):
        protocol = _gen_protocol(job_type="orchestrator")
        assert "Orchestrator Coordination Protocol (3 Phases)" in protocol
        assert "ORCHESTRATOR CONSTRAINTS" in protocol

    def test_agent_todowrite_unchanged(self):
        protocol = _gen_protocol(job_type="agent")
        assert "Break mission into 3-7" in protocol

    def test_job_type_default_backward_compat(self):
        protocol_default = _gen_protocol()
        protocol_agent = _gen_protocol(job_type="agent")
        assert protocol_default == protocol_agent
