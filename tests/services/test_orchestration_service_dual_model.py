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

from giljo_mcp.models import AgentExecution, AgentJob, AgentTemplate, Product, Project
from tests.helpers.product_crew_helper import adopt_all_templates




@pytest_asyncio.fixture
async def test_tenant_key() -> str:
    return f"tk_test_{uuid.uuid4().hex[:16]}"


@pytest_asyncio.fixture
async def test_agent_templates(db_session, test_tenant_key):
    template_names = ["impl-1", "auth-impl", "test-1", "impl-waiting", "test-working", "tester-1"]
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
        name="Dual Model Test Project",
        description="Test project for dual-model migration",
        mission="Test mission for dual-model migration",
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
class TestSpawnAgentJobDualModel:

    async def test_spawn_creates_both_job_and_execution(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement authentication system",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        from giljo_mcp.schemas.service_responses import SpawnResult

        assert isinstance(result, SpawnResult)
        assert result.job_id
        assert result.agent_id

        assert result.job_id != result.agent_id
        assert isinstance(uuid.UUID(result.job_id), uuid.UUID)
        assert isinstance(uuid.UUID(result.agent_id), uuid.UUID)

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one_or_none()
        assert job is not None
        assert "Implement authentication system" in job.mission
        assert job.job_type == "implementer"
        assert job.tenant_key == test_tenant_key
        assert job.project_id == test_project.id

        exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == result.agent_id)
        exec_result = await db_session.execute(exec_stmt)
        execution = exec_result.scalar_one_or_none()
        assert execution is not None
        assert execution.job_id == result.job_id
        assert execution.agent_display_name == "implementer"
        assert execution.tenant_key == test_tenant_key

    async def test_spawn_stores_mission_in_job_not_execution(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        mission = "Build OAuth2 authentication with JWT tokens"
        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="auth-impl",
            mission=mission,
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert mission in job.mission

        exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == result.agent_id)
        exec_result = await db_session.execute(exec_stmt)
        execution = exec_result.scalar_one()
        assert not hasattr(execution, "mission")

    async def test_spawn_returns_both_ids(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="test-1",
            mission="Write integration tests",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        from giljo_mcp.schemas.service_responses import SpawnResult

        assert isinstance(result, SpawnResult)
        assert result.job_id
        assert result.agent_id

        try:
            uuid.UUID(result.job_id)
            uuid.UUID(result.agent_id)
        except ValueError:
            pytest.fail("job_id or agent_id is not a valid UUID")






@pytest.mark.asyncio
class TestQueryMethodsDualModel:

    async def test_list_jobs_returns_both_ids(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement feature X",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        jobs_result = await service.list_jobs(tenant_key=test_tenant_key)
        jobs = jobs_result.jobs

        assert len(jobs) >= 1
        job_entry = next((j for j in jobs if j["job_id"] == result.job_id), None)
        assert job_entry is not None
        assert "job_id" in job_entry
        assert "agent_id" in job_entry
        assert job_entry["job_id"] == result.job_id
        assert job_entry["agent_id"] == result.agent_id

    async def test_get_pending_jobs_filters_by_execution_status(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        waiting_result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-waiting",
            mission="Waiting task",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        working_result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="test-working",
            mission="Working task",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        working_exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == working_result.agent_id)
        working_exec_result = await db_session.execute(working_exec_stmt)
        working_exec = working_exec_result.scalar_one()
        working_exec.status = "working"
        await db_session.commit()

        pending_result = await service.get_pending_jobs(agent_display_name="implementer", tenant_key=test_tenant_key)
        pending_jobs = pending_result.jobs

        pending_job_ids = [j["job_id"] for j in pending_jobs]
        assert waiting_result.job_id in pending_job_ids
        assert working_result.job_id not in pending_job_ids

    async def test_get_agent_mission_returns_mission_from_job(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        mission = "Build comprehensive test suite"
        result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="tester-1",
            mission=mission,
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        fetched_mission = await service.get_agent_mission(job_id=result.job_id, tenant_key=test_tenant_key)

        assert mission in fetched_mission.mission

    async def test_get_workflow_status_aggregates_across_executions(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Task 1",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )
        await service.spawn_job(
            agent_display_name="tester",
            agent_name="test-1",
            mission="Task 2",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        status = await service.get_workflow_status(project_id=test_project.id, tenant_key=test_tenant_key)

        from giljo_mcp.schemas.service_responses import WorkflowStatus

        assert isinstance(status, WorkflowStatus)
        assert status.total_agents >= 2




@pytest.mark.asyncio
class TestUpdateMethodsDualModel:

    async def test_complete_job_updates_execution_status(self, db_session, db_manager, test_project, test_tenant_key):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement feature",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )
        agent_id = result.agent_id
        job_id = result.job_id

        complete_result = await service.complete_job(
            job_id=job_id, result={"output": "Task done"}, tenant_key=test_tenant_key
        )

        assert complete_result.status == "success"

        exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == agent_id)
        exec_result = await db_session.execute(exec_stmt)
        execution = exec_result.scalar_one()
        assert execution.status == "complete"

        job_stmt = select(AgentJob).where(AgentJob.job_id == job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.status == "completed"

    async def test_report_progress_updates_execution_fields(
        self, db_session, db_manager, test_project, test_tenant_key
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement feature",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )
        agent_id = result.agent_id
        job_id = result.job_id

        await service.report_progress(
            job_id=job_id,
            progress={"percent": 50, "message": "Implementing database schema"},
            tenant_key=test_tenant_key,
        )

        await db_session.commit()
        exec_stmt = select(AgentExecution).where(AgentExecution.agent_id == agent_id)
        exec_result = await db_session.execute(exec_stmt)
        execution = exec_result.scalar_one()
        assert execution.progress == 50
        assert execution.current_task == "Implementing database schema"
        assert execution.last_progress_at is not None
