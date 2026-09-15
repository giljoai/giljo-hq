# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import AgentJob, AgentTemplate, Product, Project
from tests.helpers.product_crew_helper import adopt_all_templates




@pytest_asyncio.fixture
async def test_tenant_key() -> str:
    return f"tk_test_{uuid.uuid4().hex[:16]}"


@pytest_asyncio.fixture
async def test_agent_templates(db_session, test_tenant_key):
    template_names = ["analyzer", "implementer", "tester"]
    for name in template_names:
        template = AgentTemplate(
            tenant_key=test_tenant_key,
            name=name,
            role=name,
            description=f"Test template for {name}",
            system_instructions=f"# {name}\nTest agent.",
            is_active=True,
        )
        db_session.add(template)
    await db_session.commit()


@pytest_asyncio.fixture
async def test_project(db_session, test_tenant_key, test_agent_templates) -> Project:
    from datetime import datetime

    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name="Phase Label Test Project",
        description="Test project for 0411a phase labels",
        mission="Test mission for phase labels",
        status="active",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    await adopt_all_templates(db_session, test_tenant_key, _owning_product_project.id)
    return project




@pytest.mark.asyncio
class TestSpawnAgentJobPhase:

    async def test_spawn_job_stores_phase_when_provided(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        predecessor = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer",
            mission="Analyze first",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement feature X",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=2,
            predecessor_job_id=predecessor.job_id,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase == 2

    async def test_spawn_job_phase_defaults_to_none(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer",
            mission="Analyze codebase",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase is None

    async def test_spawn_job_populates_template_id(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        predecessor = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement before tests",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="tester",
            mission="Run test suite",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=3,
            predecessor_job_id=predecessor.job_id,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.template_id is not None

        tmpl_stmt = select(AgentTemplate).where(
            AgentTemplate.name == "tester",
            AgentTemplate.tenant_key == test_tenant_key,
        )
        tmpl_result = await db_session.execute(tmpl_stmt)
        template = tmpl_result.scalar_one()
        assert job.template_id == template.id




@pytest.mark.asyncio
class TestListJobsPhase:

    async def test_list_jobs_includes_phase_in_response(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer",
            mission="Analyze for phase test",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        result = await service.list_jobs(
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        assert len(result.jobs) >= 1
        job_dict = result.jobs[0]
        assert "phase" in job_dict
        assert job_dict["phase"] == 1




@pytest.mark.asyncio
class TestOrchestratorPhaseInstructions:

    async def test_phase_instructions_included_in_multi_terminal_mode(self, db_session, db_manager, test_tenant_key):
        from datetime import datetime

        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        _owning_product_project = Product(
            id=str(uuid.uuid4()),
            tenant_key=test_tenant_key,
            name=f"Owning Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_project)
        project = Project(
            id=str(uuid.uuid4()),
            name="Multi-Terminal Phase Test",
            description="Test project",
            mission="Test mission",
            status="active",
            tenant_key=test_tenant_key,
            product_id=_owning_product_project.id,
            execution_mode="multi_terminal",
            implementation_launched_at=datetime.now(UTC),
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)

        for name in ["analyzer", "implementer"]:
            template = AgentTemplate(
                tenant_key=test_tenant_key,
                name=name,
                role=name,
                description=f"Test {name}",
                system_instructions=f"# {name}",
                is_active=True,
            )
            db_session.add(template)
        await db_session.commit()

        result = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate project",
            project_id=project.id,
            tenant_key=test_tenant_key,
        )

        instructions = await service._mission.get_staging_instructions(
            job_id=result.job_id,
            tenant_key=test_tenant_key,
        )

        phase_instructions = instructions.get("phase_assignment_instructions", "")
        assert "Phase 1" in phase_instructions, (
            "Phase instructions missing from multi-terminal orchestrator instructions"
        )
        assert "phase" in phase_instructions.lower()
        await adopt_all_templates(db_session, test_tenant_key, _owning_product_project.id)

    async def test_phase_instructions_excluded_in_cli_mode(self, db_session, db_manager, test_tenant_key):
        from datetime import datetime

        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        _owning_product_project = Product(
            id=str(uuid.uuid4()),
            tenant_key=test_tenant_key,
            name=f"Owning Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_project)
        project = Project(
            id=str(uuid.uuid4()),
            name="CLI Mode Phase Test",
            description="Test project",
            mission="Test mission",
            status="active",
            tenant_key=test_tenant_key,
            product_id=_owning_product_project.id,
            execution_mode="claude_code_cli",
            implementation_launched_at=datetime.now(UTC),
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)

        for name in ["analyzer", "implementer"]:
            template = AgentTemplate(
                tenant_key=test_tenant_key,
                name=name,
                role=name,
                description=f"Test {name}",
                system_instructions=f"# {name}",
                is_active=True,
            )
            db_session.add(template)
        await db_session.commit()

        result = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate project",
            project_id=project.id,
            tenant_key=test_tenant_key,
        )

        instructions = await service._mission.get_staging_instructions(
            job_id=result.job_id,
            tenant_key=test_tenant_key,
        )

        assert "phase_assignment_instructions" not in instructions, (
            "Phase assignment instructions should NOT appear in CLI mode"
        )
        await adopt_all_templates(db_session, test_tenant_key, _owning_product_project.id)
