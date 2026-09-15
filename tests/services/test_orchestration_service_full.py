# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC

import pytest

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import AgentExecution, AgentJob, AgentTemplate, Product, Project
from giljo_mcp.schemas.service_responses import (
    MissionResponse,
    SpawnResult,
)
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager
from tests.helpers.product_crew_helper import adopt_all_templates
from tests.helpers.test_db_helper import purge_tenant_rows


@pytest.fixture
async def orchestration_service(db_manager: DatabaseManager):
    tenant_manager = TenantManager()
    return OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager)


@pytest.fixture
async def test_product(db_manager: DatabaseManager):
    tenant_key = f"test_tenant_{uuid.uuid4().hex[:8]}"

    async with db_manager.get_session_async() as session:
        product = Product(
            tenant_key=tenant_key,
            name="Test Product",
            description="Test product for orchestration tests",
            is_active=True,
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)

        yield {"product_id": str(product.id), "tenant_key": tenant_key}

    await purge_tenant_rows(db_manager, tenant_key)


@pytest.fixture
async def test_project(db_manager: DatabaseManager, test_product: dict):
    from datetime import datetime

    async with db_manager.get_session_async() as session:
        project = Project(
            tenant_key=test_product["tenant_key"],
            product_id=test_product["product_id"],
            name="Test Project",
            description="Build a todo app",
            mission="Build a RESTful API for a todo application",
            status="active",
            execution_mode="multi_terminal",
            implementation_launched_at=datetime.now(UTC),
            series_number=random.randint(1, 9000),
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)

        yield {
            **test_product,
            "project_id": str(project.id),
        }


@pytest.fixture
async def test_project_not_launched(db_manager: DatabaseManager, test_product: dict):
    async with db_manager.get_session_async() as session:
        project = Project(
            tenant_key=test_product["tenant_key"],
            product_id=test_product["product_id"],
            name="Unlaunched Project",
            description="Build a todo app",
            mission="Build a RESTful API for a todo application",
            status="active",
            execution_mode="multi_terminal",
            implementation_launched_at=None,
            series_number=random.randint(1, 9000),
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)

        yield {
            **test_product,
            "project_id": str(project.id),
        }


@pytest.fixture
async def test_agent_templates(db_manager: DatabaseManager, test_product: dict):
    async with db_manager.get_session_async() as session:
        templates = []
        for name, role in [("implementer", "implementer"), ("tester", "tester")]:
            template = AgentTemplate(
                tenant_key=test_product["tenant_key"],
                name=name,
                role=role,
                description=f"{role.title()} specialist",
                system_instructions=f"# {role.title()}\nSpecialist agent.",
                is_active=True,
            )
            session.add(template)
            templates.append(template)
        await session.commit()
        for t in templates:
            await session.refresh(t)

        await adopt_all_templates(session, test_product["tenant_key"], test_product["product_id"])

        yield {
            **test_product,
            "template_ids": [str(t.id) for t in templates],
        }


class TestSpawnAgentJob:

    @pytest.mark.asyncio
    async def test_spawn_creates_both_job_and_execution(
        self,
        orchestration_service: OrchestrationService,
        test_project: dict,
        test_agent_templates: dict,
        db_manager: DatabaseManager,
    ):
        result = await orchestration_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement user authentication module",
            project_id=test_project["project_id"],
            tenant_key=test_project["tenant_key"],
        )

        assert isinstance(result, SpawnResult)
        assert result.job_id
        assert result.agent_id
        assert result.thin_client is True
        assert result.mission_stored is True

        async with db_manager.get_session_async(tenant_key=test_project["tenant_key"]) as session:
            from sqlalchemy import select

            with tenant_session_context(session, test_project["tenant_key"]):
                job_query = select(AgentJob).where(
                    AgentJob.job_id == result.job_id,
                    AgentJob.tenant_key == test_project["tenant_key"],
                )
                job_result = await session.execute(job_query)
                job = job_result.scalar_one_or_none()

            assert job is not None
            assert "Implement user authentication module" in job.mission
            assert job.job_type == "implementer"
            assert job.status == "active"

            with tenant_session_context(session, test_project["tenant_key"]):
                exec_query = select(AgentExecution).where(
                    AgentExecution.job_id == result.job_id,
                    AgentExecution.tenant_key == test_project["tenant_key"],
                )
                exec_result = await session.execute(exec_query)
                execution = exec_result.scalar_one_or_none()

            assert execution is not None
            assert execution.agent_display_name == "implementer"
            assert execution.status == "waiting"

    @pytest.mark.asyncio
    async def test_spawn_routes_correctly(
        self,
        orchestration_service: OrchestrationService,
        test_project: dict,
        test_agent_templates: dict,
        db_manager: DatabaseManager,
    ):
        result = await orchestration_service.spawn_job(
            agent_display_name="tester",
            agent_name="tester",
            mission="Test authentication module",
            project_id=test_project["project_id"],
            tenant_key=test_project["tenant_key"],
        )

        assert isinstance(result, SpawnResult)
        assert result.job_id

        async with db_manager.get_session_async(tenant_key=test_project["tenant_key"]) as session:
            from sqlalchemy import select

            with tenant_session_context(session, test_project["tenant_key"]):
                job_query = select(AgentJob).where(
                    AgentJob.job_id == result.job_id,
                    AgentJob.tenant_key == test_project["tenant_key"],
                )
                job_result = await session.execute(job_query)
                job = job_result.scalar_one_or_none()

            assert job.job_type == "tester"




class TestMultiTenantIsolation:

    @pytest.mark.asyncio
    async def test_spawn_agent_tenant_isolated(
        self,
        orchestration_service: OrchestrationService,
        test_project: dict,
        db_manager: DatabaseManager,
    ):
        wrong_tenant = "wrong_tenant_key"

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await orchestration_service.spawn_job(
                agent_display_name="implementer",
                agent_name="Implementer-1",
                mission="Implement feature",
                project_id=test_project["project_id"],
                tenant_key=wrong_tenant,
            )

        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_agent_mission_tenant_isolated(
        self,
        orchestration_service: OrchestrationService,
        test_project: dict,
        test_agent_templates: dict,
        db_manager: DatabaseManager,
    ):
        result = await orchestration_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement feature",
            project_id=test_project["project_id"],
            tenant_key=test_project["tenant_key"],
        )

        job_id = result.job_id
        wrong_tenant = "wrong_tenant_key"

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await orchestration_service.get_agent_mission(
                job_id=job_id,
                tenant_key=wrong_tenant,
            )

        assert "not found" in str(exc_info.value).lower()


class TestErrorHandling:

    @pytest.mark.asyncio
    async def test_spawn_agent_invalid_project(
        self,
        orchestration_service: OrchestrationService,
        test_product: dict,
        db_manager: DatabaseManager,
    ):
        fake_project_id = str(uuid.uuid4())

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await orchestration_service.spawn_job(
                agent_display_name="implementer",
                agent_name="Implementer-1",
                mission="Implement feature",
                project_id=fake_project_id,
                tenant_key=test_product["tenant_key"],
            )

        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_agent_mission_invalid_job(
        self,
        orchestration_service: OrchestrationService,
        test_product: dict,
        db_manager: DatabaseManager,
    ):
        fake_job_id = str(uuid.uuid4())

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await orchestration_service.get_agent_mission(
                job_id=fake_job_id,
                tenant_key=test_product["tenant_key"],
            )

        assert "not found" in str(exc_info.value).lower()


class TestAgentMission:

    @pytest.mark.asyncio
    async def test_get_agent_mission_returns_full_protocol(
        self,
        orchestration_service: OrchestrationService,
        test_project: dict,
        test_agent_templates: dict,
        db_manager: DatabaseManager,
    ):
        result = await orchestration_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement user authentication",
            project_id=test_project["project_id"],
            tenant_key=test_project["tenant_key"],
        )

        job_id = result.job_id

        mission_result = await orchestration_service.get_agent_mission(
            job_id=job_id,
            tenant_key=test_project["tenant_key"],
        )

        assert isinstance(mission_result, MissionResponse)
        if mission_result.full_protocol is not None:
            assert isinstance(mission_result.full_protocol, str)
            assert len(mission_result.full_protocol) > 0

    @pytest.mark.asyncio
    async def test_get_agent_mission_blocked_when_not_launched(
        self,
        orchestration_service: OrchestrationService,
        test_project_not_launched: dict,
        test_agent_templates: dict,
        db_manager: DatabaseManager,
    ):
        result = await orchestration_service.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Implement user authentication",
            project_id=test_project_not_launched["project_id"],
            tenant_key=test_project_not_launched["tenant_key"],
        )

        mission_result = await orchestration_service.get_agent_mission(
            job_id=result.job_id,
            tenant_key=test_project_not_launched["tenant_key"],
        )

        assert isinstance(mission_result, MissionResponse)
        assert mission_result.blocked is True, "Mission should be blocked when implementation not launched"
        assert mission_result.mission is None, "Mission should be None when blocked"
        assert mission_result.full_protocol is None, "Protocol should be None when blocked"
        assert "BLOCKED" in (mission_result.error or ""), "Error message should indicate blocked status"
        assert mission_result.user_instruction is not None, "Response should include user instruction"
        assert "Implement" in (mission_result.user_instruction or ""), (
            "User instruction should mention Implement button"
        )
