# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest




@pytest.mark.asyncio
class TestOrchestratorPhaseInstructions:

    async def test_phase_instructions_present_in_multi_terminal_mode(
        self, db_session, db_manager, test_project_multi_terminal, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        spawn_result = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate multi-terminal project",
            project_id=test_project_multi_terminal.id,
            tenant_key=test_tenant_key,
        )

        instructions = await service._mission.get_staging_instructions(
            job_id=spawn_result.job_id,
            tenant_key=test_tenant_key,
        )

        assert "phase_assignment_instructions" in instructions
        phase_text = instructions["phase_assignment_instructions"]
        assert "Phase 1" in phase_text
        assert "Phase 2" in phase_text
        assert "parallel" in phase_text.lower()

    async def test_phase_instructions_absent_in_cli_mode(
        self, db_session, db_manager, test_project_cli_mode, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        spawn_result = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate CLI project",
            project_id=test_project_cli_mode.id,
            tenant_key=test_tenant_key,
        )

        instructions = await service._mission.get_staging_instructions(
            job_id=spawn_result.job_id,
            tenant_key=test_tenant_key,
        )

        assert "phase_assignment_instructions" not in instructions

    async def test_phase_instructions_contain_expected_content(
        self, db_session, db_manager, test_project_multi_terminal, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        spawn_result = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate multi-terminal project",
            project_id=test_project_multi_terminal.id,
            tenant_key=test_tenant_key,
        )

        instructions = await service._mission.get_staging_instructions(
            job_id=spawn_result.job_id,
            tenant_key=test_tenant_key,
        )

        phase_text = instructions["phase_assignment_instructions"]
        assert "Execution Phase Assignment" in phase_text
        assert "Multi-Terminal Mode" in phase_text
        assert "spawn_job" in phase_text
        assert "Phase 1" in phase_text
        assert "Phase 2" in phase_text
        assert "Phase 3" in phase_text
        assert "Phase 4" in phase_text

    async def test_phase_instructions_present_for_default_mode(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        spawn_result = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate default project",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        instructions = await service._mission.get_staging_instructions(
            job_id=spawn_result.job_id,
            tenant_key=test_tenant_key,
        )

        assert "phase_assignment_instructions" in instructions
