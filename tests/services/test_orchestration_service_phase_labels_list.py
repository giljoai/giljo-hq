# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from sqlalchemy import select

from giljo_mcp.models import AgentJob, AgentTemplate




@pytest.mark.asyncio
class TestSpawnPopulatesTemplateId:

    async def test_template_id_set_in_multi_terminal_mode(
        self, db_session, db_manager, test_project_multi_terminal, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Analyze the codebase",
            project_id=test_project_multi_terminal.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.template_id is not None

        template_stmt = select(AgentTemplate).where(
            AgentTemplate.name == "analyzer-1",
            AgentTemplate.tenant_key == test_tenant_key,
        )
        template_result = await db_session.execute(template_stmt)
        template = template_result.scalar_one()
        assert job.template_id == template.id

    async def test_template_id_none_when_no_template_found(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate project",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.template_id is None




@pytest.mark.asyncio
class TestListJobsIncludesPhase:

    async def test_list_jobs_returns_phase_value(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Analyze the codebase",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        result = await service.list_jobs(
            tenant_key=test_tenant_key,
            project_id=test_project.id,
        )

        assert len(result.jobs) >= 1
        job_dict = result.jobs[0]
        assert "phase" in job_dict
        assert job_dict["phase"] == 1

    async def test_list_jobs_returns_none_phase_when_not_set(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        await service.spawn_job(
            agent_display_name="impl",
            agent_name="impl-1",
            mission="Implement feature",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        result = await service.list_jobs(
            tenant_key=test_tenant_key,
            project_id=test_project.id,
        )

        assert len(result.jobs) >= 1
        impl_jobs = [j for j in result.jobs if j["agent_display_name"] == "impl"]
        assert len(impl_jobs) >= 1
        assert "phase" in impl_jobs[0]
        assert impl_jobs[0]["phase"] is None

    async def test_list_jobs_returns_multiple_phases(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        analyzer_result = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Analyze first",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )
        impl_result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement second",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=2,
            predecessor_job_id=analyzer_result.job_id,
        )
        await service.spawn_job(
            agent_display_name="tester",
            agent_name="tester-1",
            mission="Test third",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=3,
            predecessor_job_id=impl_result.job_id,
        )

        result = await service.list_jobs(
            tenant_key=test_tenant_key,
            project_id=test_project.id,
        )

        assert len(result.jobs) >= 3
        phases = {j["agent_display_name"]: j["phase"] for j in result.jobs}
        assert phases.get("analyzer") == 1
        assert phases.get("implementer") == 2
        assert phases.get("tester") == 3
