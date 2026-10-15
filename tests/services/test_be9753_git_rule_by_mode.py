# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

import pytest

from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol
from giljo_mcp.services.protocol_survival import build_complete_job_footer


_PRECEDENCE = "If your mission gives a git instruction, the mission wins."
_HANDOFF = 'list every file you changed in `complete_job(result={"artifacts": [...]})`'


def _worker(execution_mode: str, tool: str, *, git: bool = True) -> str:
    return _generate_agent_protocol(
        job_id="J",
        tenant_key="T",
        agent_name="implementer",
        agent_id="A",
        execution_mode=execution_mode,
        git_integration_enabled=git,
        job_type="implementer",
        tool=tool,
        comm_thread_id="thread-1",
    )


def _orchestrator(execution_mode: str, tool: str) -> str:
    return _generate_agent_protocol(
        job_id="J",
        tenant_key="T",
        agent_name="orchestrator",
        agent_id="A",
        execution_mode=execution_mode,
        job_type="orchestrator",
        tool=tool,
    )


_SUBAGENT_CASES = [
    ("subagent", "generic"),
    ("generic", "generic"),
    ("claude-code", "claude-code"),
    ("codex", "codex"),
]


@pytest.mark.parametrize(("execution_mode", "tool"), _SUBAGENT_CASES)
def test_subagent_worker_hands_files_over_instead_of_committing(execution_mode: str, tool: str) -> None:
    proto = _worker(execution_mode, tool)
    assert "Git Commit (REQUIRED" not in proto
    assert "### Git (subagent mode): do NOT commit" in proto
    assert _HANDOFF in proto
    assert "the orchestrator stages them by name and commits once" in proto
    assert _PRECEDENCE in proto


def test_multi_terminal_worker_keeps_the_commit_block() -> None:
    proto = _worker("multi_terminal", "multi_terminal")
    assert "### Git Commit (REQUIRED - Git Integration Enabled)" in proto
    assert "do NOT commit" not in proto
    assert _PRECEDENCE in proto


@pytest.mark.parametrize(("execution_mode", "tool"), [*_SUBAGENT_CASES, ("multi_terminal", "multi_terminal")])
def test_git_off_renders_no_git_block_in_any_mode(execution_mode: str, tool: str) -> None:
    proto = _worker(execution_mode, tool, git=False)
    assert "Git Commit (REQUIRED" not in proto
    assert "### Git (subagent mode)" not in proto
    assert _PRECEDENCE not in proto


@pytest.mark.parametrize(("execution_mode", "tool"), _SUBAGENT_CASES)
def test_subagent_orchestrator_is_the_committer(execution_mode: str, tool: str) -> None:
    body = _orchestrator(execution_mode, tool)
    assert "IT commits its work" not in body
    assert "THEY committed" not in body
    assert "You are the committer (subagent mode)" in body
    assert "commit once" in body


def test_multi_terminal_orchestrator_keeps_workers_commit_their_own_work() -> None:
    body = _orchestrator("multi_terminal", "multi_terminal")
    assert "IT commits its work" in body
    assert "You are the committer (subagent mode)" not in body


class _MinimalBuilder(ExecutionPromptBuilderBase):
    @property
    def platform_name(self) -> str:
        return "Test Platform"

    def _build_spawning_section(self, agent_jobs: list) -> list[str]:
        return ["## Spawning", ""]


def test_subagent_implementation_prompt_names_the_orchestrator_the_committer() -> None:
    project = SimpleNamespace(id="P", name="Test Project", product_id="PR", taxonomy_alias="BE-9753")
    prompt = _MinimalBuilder().build_execution_prompt("orch-1", project, [], git_enabled=True)
    assert "Committer of last resort" not in prompt
    assert "You are the committer" in prompt
    assert "artifacts" in prompt
    assert "NEVER `git add -A`" in prompt


def test_closeout_replies_no_longer_claim_orchestrators_never_commit() -> None:
    _phase, _msg, next_action = JobCompletionService._phase_response(is_staging_end=False, is_closeout_phase=True)
    footer = build_complete_job_footer(phase="closeout")
    for text in (next_action["why"], footer):
        assert "do not commit code" not in text
        assert "pass the commits you or your workers made" in text
