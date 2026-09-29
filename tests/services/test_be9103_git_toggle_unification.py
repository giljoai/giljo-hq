# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

import pytest

from giljo_mcp import platform_registry as reg
from giljo_mcp.models.settings import Settings
from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase
from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol
from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch3_spawning_rules
from giljo_mcp.services.protocol_sections.worker_body import _build_conditional_blocks
from giljo_mcp.services.settings_service import SettingsService




class TestSelfAdoptCommitDuty:
    def test_capable_self_adopt_rung_contains_the_commit_step(self):
        ch3 = _build_ch3_spawning_rules("generic_mcp")
        assert "SELF-ADOPT the queued jobs" in ch3
        assert "SELF-ADOPT is the LAST resort" in ch3
        assert "commit the work" in ch3
        assert "NEVER git add -A" in ch3
        assert "commit duty" in ch3

    def test_chat_self_adopt_rung_has_no_git_commit_instruction(self):
        chat = reg.get_preset("chat")
        ch3 = _build_ch3_spawning_rules("generic_mcp", preset=chat)
        assert "CANNOT self-adopt a CODE job" in ch3
        assert "no commit step" in ch3
        assert "git add the specific files you changed" not in ch3

    def test_orchestrator_constraint_scopes_no_commit_to_delegation(self):
        body = _generate_agent_protocol(
            job_id="J",
            tenant_key="T",
            agent_name="orchestrator",
            agent_id="A",
            execution_mode="multi_terminal",
            job_type="orchestrator",
            tool="multi_terminal",
        )
        assert "You coordinate, you do not commit." not in body
        assert "while you are delegating" in body
        assert "carries that worker's commit duty" in body

    def test_git_warning_prose_flags_self_adopted_no_commits(self):
        body = _generate_agent_protocol(
            job_id="J",
            tenant_key="T",
            agent_name="orchestrator",
            agent_id="A",
            execution_mode="multi_terminal",
            job_type="orchestrator",
            tool="multi_terminal",
        )
        assert "if you SELF-ADOPTED any job" in body
        assert "RED FLAG" in body




class _MinimalBuilder(ExecutionPromptBuilderBase):
    @property
    def platform_name(self) -> str:
        return "Test Platform"

    def _build_spawning_section(self, agent_jobs: list) -> list[str]:
        return ["## Spawning", ""]


def _make_project() -> SimpleNamespace:
    return SimpleNamespace(id="proj-001", name="Test Project", product_id="prod-001", taxonomy_alias="BE-9103")


class TestRenderFromFlagAlone:
    def test_worker_commit_block_renders_when_flag_true(self):
        git_block, _ = _build_conditional_blocks(
            git_integration_enabled=True, execution_mode="subagent", tool="claude-code"
        )
        assert "Git Commit (REQUIRED" in git_block
        assert "never use `git add -A`" in git_block

    def test_worker_commit_block_absent_when_flag_false(self):
        git_block, _ = _build_conditional_blocks(
            git_integration_enabled=False, execution_mode="subagent", tool="claude-code"
        )
        assert git_block == ""

    def test_orchestrator_closeout_backstop_renders_when_flag_true(self):
        builder = _MinimalBuilder()
        prompt = builder.build_execution_prompt("orch-1", _make_project(), [], git_enabled=True)
        assert "Git Closeout Commit" in prompt
        assert "Committer of last resort" in prompt
        assert "git status --short" in prompt
        assert 'git commit -m "BE-9103: ' in prompt

    def test_orchestrator_closeout_never_asks_for_an_empty_commit(self):
        builder = _MinimalBuilder()
        orchestrator_prompt = builder.build_execution_prompt("orch-1", _make_project(), [], git_enabled=True)
        assert "--allow-empty" not in orchestrator_prompt
        assert "NEVER `git add -A`" in orchestrator_prompt
        assert "no_code_changes" in orchestrator_prompt

    def test_orchestrator_closeout_absent_when_flag_false(self):
        builder = _MinimalBuilder()
        prompt = builder.build_execution_prompt("orch-1", _make_project(), [], git_enabled=False)
        assert "Git Closeout Commit" not in prompt
        assert "Committer of last resort" not in prompt




class TestUnifiedToggleReadPath:
    @pytest.mark.asyncio
    async def test_enabled_true_from_settings_alone(self, db_session, test_tenant_key):
        db_session.add(
            Settings(
                tenant_key=test_tenant_key,
                category="integrations",
                settings_data={"git_integration": {"enabled": True}},
            )
        )
        await db_session.commit()

        svc = SettingsService(db_session, test_tenant_key)
        assert await svc.git_integration_enabled() is True

    @pytest.mark.asyncio
    async def test_enabled_false_when_no_settings_row(self, db_session, test_tenant_key):
        svc = SettingsService(db_session, test_tenant_key)
        assert await svc.git_integration_enabled() is False

    @pytest.mark.asyncio
    async def test_enabled_false_when_toggle_off(self, db_session, test_tenant_key):
        db_session.add(
            Settings(
                tenant_key=test_tenant_key,
                category="integrations",
                settings_data={"git_integration": {"enabled": False}},
            )
        )
        await db_session.commit()

        svc = SettingsService(db_session, test_tenant_key)
        assert await svc.git_integration_enabled() is False
