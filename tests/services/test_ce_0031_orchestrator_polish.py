# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.template_seeder import compose_orchestrator_identity
from tests.helpers.product_crew_helper import adopt_all_templates


async def _seed_templates(db_session: AsyncSession, tenant_key: str, product_id: str) -> None:
    for name, role in (
        ("implementer", "implementer"),
        ("tester", "tester"),
        ("reviewer", "reviewer"),
    ):
        db_session.add(
            AgentTemplate(
                tenant_key=tenant_key,
                product_id=product_id,
                name=name,
                role=role,
                description=f"{name} template",
                is_active=True,
            )
        )
    await db_session.commit()
    await adopt_all_templates(db_session, tenant_key, product_id)




async def _seed_staging_orchestrator(
    db_session: AsyncSession,
    test_product,
    test_project,
    project_phase: str = "staging",
):
    test_product.tenant_key = test_project.tenant_key
    await db_session.commit()
    await db_session.refresh(test_product)

    test_project.product_id = test_product.id
    await db_session.commit()
    await db_session.refresh(test_project)

    job = AgentJob(
        job_id=str(uuid4()),
        job_type="orchestrator",
        tenant_key=test_project.tenant_key,
        project_id=test_project.id,
        mission="Orchestrate the project",
        status="active",
        job_metadata={"user_id": str(uuid4())},
    )
    db_session.add(job)
    await db_session.commit()

    execution = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=test_project.tenant_key,
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        status="waiting",
        project_phase=project_phase,
    )
    db_session.add(execution)
    await db_session.commit()
    return job, execution


def _build_service(db_session: AsyncSession) -> OrchestrationService:
    service = OrchestrationService(db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock())
    service._test_session = db_session
    service._mission._test_session = db_session
    service._mission._orchestration._test_session = db_session
    return service




class TestTask1PhaseAwareTemplates:

    @pytest.mark.asyncio
    async def test_staging_phase_hides_verification_templates(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        await _seed_templates(db_session, test_project.tenant_key, test_product.id)
        job, _ = await _seed_staging_orchestrator(db_session, test_product, test_project, project_phase="staging")
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        roles_returned = {t["role"] for t in result["agent_templates"]}
        assert "tester" not in roles_returned, (
            "Staging exec must not see tester template — CE-0031 phase filter regression"
        )
        assert "reviewer" not in roles_returned, (
            "Staging exec must not see reviewer template — CE-0031 phase filter regression"
        )
        assert "implementer" in roles_returned
        assert result["phase_filter_note"], "Staging response must include phase_filter_note explaining the omission"
        assert "staging" in result["phase_filter_note"].lower()

    @pytest.mark.asyncio
    async def test_implementation_phase_shows_all_templates(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        await _seed_templates(db_session, test_project.tenant_key, test_product.id)
        job, _ = await _seed_staging_orchestrator(
            db_session, test_product, test_project, project_phase="implementation"
        )
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        assert result["phase_filter_note"] is None
        roles_returned = {t["role"] for t in result["agent_templates"]}
        assert "tester" in roles_returned
        assert "reviewer" in roles_returned
        assert "implementer" in roles_returned




class TestTask2ProtocolContradictions:

    @pytest.mark.asyncio
    async def test_identity_no_longer_forbids_complete_job(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        job, _ = await _seed_staging_orchestrator(db_session, test_product, test_project)
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        ch1 = result["orchestrator_protocol"]["ch1_your_mission"]
        assert "You do NOT call complete_job" not in ch1, (
            "CE-0026 sweep miss: CH1 still forbids complete_job. The post-CE-0026 "
            "canonical instruction is that staging DOES call complete_job."
        )
        assert "complete_job() at end of staging" in ch1 or "DO call complete_job" in ch1, (
            "CH1 must affirm complete_job at end of staging (CE-0026 transition)"
        )

    @pytest.mark.asyncio
    async def test_step_1b_does_not_reference_after_step_4(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        job, _ = await _seed_staging_orchestrator(db_session, test_product, test_project)
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        ch2 = result["orchestrator_protocol"]["ch2_startup_sequence"]
        assert "After Step 4" not in ch2, (
            "Step ordering contradiction: 1b prose still references Step 4 despite Step 1c being canonical."
        )

    @pytest.mark.asyncio
    async def test_get_staging_instructions_tool_description_drops_step_number(self):
        import inspect

        from api.endpoints import mcp_sdk_server

        src = inspect.getsource(mcp_sdk_server)
        assert "Step 1 of staging workflow" not in src, "Tool description still pins to a step number — drift risk."

    def test_blockers_are_urgent_appears_exactly_once(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        count = identity.count("Blockers are urgent")
        assert count == 1, (
            f"Identity must contain exactly one 'Blockers are urgent' block "
            f"(found {count}). Duplication is a regression — see CE-0031 Task 2."
        )

    def test_right_sizing_guidance_inlined_in_identity(self):
        identity = compose_orchestrator_identity(None, tool="multi_terminal")
        assert "Right-Sizing Your Work" in identity
        assert "create_task" in identity and "create_project" in identity
        assert "get_context" in identity or "fetch context" in identity.lower() or "get_job_mission" in identity




class TestTask3HarnessReminderOverride:

    def test_claude_code_identity_includes_harness_override(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "HARNESS REMINDER OVERRIDE" in identity
        assert "TaskCreate" in identity
        assert "report_progress" in identity

    def test_claude_code_override_forecloses_mirroring(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "do not mirror" in identity.lower()
        assert "recency-keyed" in identity

    def test_non_claude_code_identity_skips_harness_override(self):
        identity_mt = compose_orchestrator_identity(None, tool="multi_terminal")
        assert "HARNESS REMINDER OVERRIDE" not in identity_mt

        identity_codex = compose_orchestrator_identity(None, tool="codex")
        assert "HARNESS REMINDER OVERRIDE" not in identity_codex




class TestTask5PayloadSize:

    PAYLOAD_BUDGET_BYTES = 41_500

    @pytest.mark.asyncio
    async def test_get_staging_instructions_under_budget(
        self,
        db_session: AsyncSession,
        test_product,
        test_project,
    ):
        job, _ = await _seed_staging_orchestrator(db_session, test_product, test_project)
        service = _build_service(db_session)

        result = await service._mission.get_staging_instructions(
            job_id=job.job_id,
            tenant_key=test_project.tenant_key,
        )

        payload_size = len(json.dumps(result))
        assert payload_size < self.PAYLOAD_BUDGET_BYTES, (
            f"get_staging_instructions payload is {payload_size} bytes — "
            f"exceeds {self.PAYLOAD_BUDGET_BYTES} budget. CE-0031 trimmed this from "
            f"~41KB; future bloat must be balanced by trim or a structural split "
            f"(Option A: sub-resource tools)."
        )




class TestTask6ToolSearchBootstrap:

    def test_claude_code_identity_lists_bootstrap_tools(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "TOOLSEARCH BOOTSTRAP" in identity
        assert "ToolSearch(query=" in identity
        from giljo_mcp.branding import MCP_ALIAS

        for tool_name in (
            f"mcp__{MCP_ALIAS}__health_check",
            f"mcp__{MCP_ALIAS}__spawn_job",
            f"mcp__{MCP_ALIAS}__report_progress",
            f"mcp__{MCP_ALIAS}__complete_job",
        ):
            assert tool_name in identity, f"Bootstrap hint missing {tool_name}"

    def test_other_tools_omit_bootstrap_hint(self):
        for tool in ("codex", "gemini", "multi_terminal"):
            identity = compose_orchestrator_identity(None, tool=tool)
            assert "TOOLSEARCH BOOTSTRAP" not in identity, (
                f"{tool} identity must not include Claude-Code-specific ToolSearch hint"
            )
