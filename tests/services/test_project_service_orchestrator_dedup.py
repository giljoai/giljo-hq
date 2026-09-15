# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from contextlib import asynccontextmanager
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Product, Project, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.schemas.service_responses import ProjectLaunchResult
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    unique_suffix = uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()

    org = Organization(
        name=f"Test User Org {unique_suffix}",
        slug=f"test-user-org-{unique_suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        username=f"testuser_{unique_suffix}",
        email=f"test_{uuid4().hex[:8]}@example.com",
        tenant_key=tenant_key,
        role="developer",
        password_hash="hashed_password",
        org_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def create_project_service(db_session: AsyncSession, tenant_key: str) -> ProjectService:

    @asynccontextmanager
    async def mock_get_session():
        yield db_session

    db_manager = MagicMock()
    db_manager.get_session_async = mock_get_session

    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)

    return ProjectService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


class TestOrchestratorDeduplication:

    @pytest.mark.asyncio
    async def test_ensure_fixture_finds_completed_orchestrator(self, db_session, test_user):
        product = Product(
            name=f"Test Product {uuid4().hex[:8]}",
            tenant_key=test_user.tenant_key,
            is_active=True,
        )
        db_session.add(product)
        await db_session.flush()

        project = Project(
            name=f"Test Project {uuid4().hex[:8]}",
            description="Test project for orchestrator dedup",
            mission="Test mission for orchestrator dedup",
            product_id=product.id,
            tenant_key=test_user.tenant_key,
            status="inactive",
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)
        await db_session.flush()

        job_id = str(uuid4())
        agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=job_id,
            tenant_key=test_user.tenant_key,
            project_id=project.id,
            mission=f"Orchestrator for project: {project.name}",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=test_user.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="complete",
            progress=100,
        )
        db_session.add(agent_execution)
        await db_session.commit()

        project_service = create_project_service(db_session, test_user.tenant_key)

        result = await project_service.lifecycle._ensure_orchestrator_fixture(
            session=db_session,
            project=project,
            websocket_manager=None,
        )

        assert result is None

        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project.id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == test_user.tenant_key,
            )
        )
        exec_result = await db_session.execute(stmt)
        executions = exec_result.scalars().all()

        assert len(executions) == 1
        assert executions[0].status == "complete"
        assert executions[0].job_id == job_id

    @pytest.mark.asyncio
    async def test_ensure_fixture_finds_blocked_orchestrator(self, db_session, test_user):
        product = Product(
            name=f"Test Product {uuid4().hex[:8]}",
            tenant_key=test_user.tenant_key,
            is_active=True,
        )
        db_session.add(product)
        await db_session.flush()

        project = Project(
            name=f"Test Project {uuid4().hex[:8]}",
            description="Test project for blocked orchestrator",
            mission="Test mission for blocked orchestrator",
            product_id=product.id,
            tenant_key=test_user.tenant_key,
            status="inactive",
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)
        await db_session.flush()

        job_id = str(uuid4())
        agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=job_id,
            tenant_key=test_user.tenant_key,
            project_id=project.id,
            mission=f"Orchestrator for project: {project.name}",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=test_user.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="blocked",
            progress=50,
        )
        db_session.add(agent_execution)
        await db_session.commit()

        project_service = create_project_service(db_session, test_user.tenant_key)

        result = await project_service.lifecycle._ensure_orchestrator_fixture(
            session=db_session,
            project=project,
            websocket_manager=None,
        )

        assert result is None

        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project.id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == test_user.tenant_key,
            )
        )
        exec_result = await db_session.execute(stmt)
        executions = exec_result.scalars().all()

        assert len(executions) == 1
        assert executions[0].status == "blocked"

    @pytest.mark.asyncio
    async def test_ensure_fixture_creates_when_decommissioned(self, db_session, test_user):
        product = Product(
            name=f"Test Product {uuid4().hex[:8]}",
            tenant_key=test_user.tenant_key,
            is_active=True,
        )
        db_session.add(product)
        await db_session.flush()

        project = Project(
            name=f"Test Project {uuid4().hex[:8]}",
            description="Test project for decommissioned orchestrator",
            mission="Test mission for decommissioned orchestrator",
            product_id=product.id,
            tenant_key=test_user.tenant_key,
            status="inactive",
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)
        await db_session.flush()

        decommissioned_job_id = str(uuid4())
        decommissioned_agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=decommissioned_job_id,
            tenant_key=test_user.tenant_key,
            project_id=project.id,
            mission=f"Orchestrator for project: {project.name}",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=decommissioned_agent_id,
            job_id=decommissioned_job_id,
            tenant_key=test_user.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="decommissioned",
            progress=25,
        )
        db_session.add(agent_execution)
        await db_session.commit()

        project_service = create_project_service(db_session, test_user.tenant_key)

        result = await project_service.lifecycle._ensure_orchestrator_fixture(
            session=db_session,
            project=project,
            websocket_manager=None,
        )

        assert result is not None
        assert "job_id" in result
        assert "agent_id" in result
        assert result["job_id"] != decommissioned_job_id

        await db_session.commit()

        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project.id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == test_user.tenant_key,
            )
        )
        exec_result = await db_session.execute(stmt)
        executions = exec_result.scalars().all()

        assert len(executions) == 2

        statuses = {ex.status for ex in executions}
        assert "decommissioned" in statuses
        assert "waiting" in statuses

    @pytest.mark.asyncio
    async def test_launch_project_skips_existing_orchestrator(self, db_session, test_user):
        product = Product(
            name=f"Test Product {uuid4().hex[:8]}",
            tenant_key=test_user.tenant_key,
            is_active=True,
        )
        db_session.add(product)
        await db_session.flush()

        project = Project(
            name=f"Test Project {uuid4().hex[:8]}",
            description="Test project for launch dedup",
            mission="Test mission for launch dedup",
            product_id=product.id,
            tenant_key=test_user.tenant_key,
            status="active",
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)
        await db_session.flush()

        existing_job_id = str(uuid4())
        existing_agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=existing_job_id,
            tenant_key=test_user.tenant_key,
            project_id=project.id,
            mission=f"Orchestrator for project: {project.name}",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=existing_agent_id,
            job_id=existing_job_id,
            tenant_key=test_user.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="working",
            progress=75,
        )
        db_session.add(agent_execution)
        await db_session.commit()

        project_service = create_project_service(db_session, test_user.tenant_key)

        result = await project_service.launch_project(
            project_id=project.id,
            user_id=str(test_user.id),
            launch_config=None,
            websocket_manager=None,
        )

        assert isinstance(result, ProjectLaunchResult)
        assert result.orchestrator_job_id == existing_job_id

        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project.id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == test_user.tenant_key,
            )
        )
        exec_result = await db_session.execute(stmt)
        executions = exec_result.scalars().all()

        assert len(executions) == 1
        assert executions[0].status == "working"
        assert executions[0].job_id == existing_job_id
