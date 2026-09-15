# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.models import AgentExecution, AgentJob


class TestOrchestratorStatusFilterFix:

    @pytest.mark.asyncio
    async def test_complete_orchestrator_should_be_found(self, db_session, test_project):
        job_id = str(uuid4())
        agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=job_id,
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission=f"Orchestrator for project: {test_project.name}",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="complete",
            progress=100,
        )
        db_session.add(agent_execution)
        await db_session.commit()

        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == test_project.id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == test_project.tenant_key,
                ~AgentExecution.status.in_(["decommissioned"]),
            )
        )
        result = await db_session.execute(stmt)
        found = result.scalar_one_or_none()

        assert found is not None
        assert found.status == "complete"

    @pytest.mark.asyncio
    async def test_blocked_orchestrator_should_be_found(self, db_session, test_project):
        job_id = str(uuid4())
        agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=job_id,
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission=f"Orchestrator for project: {test_project.name}",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="blocked",
            progress=50,
        )
        db_session.add(agent_execution)
        await db_session.commit()

        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == test_project.id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == test_project.tenant_key,
                ~AgentExecution.status.in_(["decommissioned"]),
            )
        )
        result = await db_session.execute(stmt)
        found = result.scalar_one_or_none()

        assert found is not None
        assert found.status == "blocked"

    @pytest.mark.asyncio
    async def test_silent_orchestrator_should_be_found(self, db_session, test_project):
        job_id = str(uuid4())
        agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=job_id,
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission=f"Orchestrator for project: {test_project.name}",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="silent",
            progress=25,
        )
        db_session.add(agent_execution)
        await db_session.commit()

        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == test_project.id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == test_project.tenant_key,
                ~AgentExecution.status.in_(["decommissioned"]),
            )
        )
        result = await db_session.execute(stmt)
        found = result.scalar_one_or_none()

        assert found is not None
        assert found.status == "silent"

    @pytest.mark.asyncio
    async def test_decommissioned_orchestrator_should_not_be_found(self, db_session, test_project):
        job_id = str(uuid4())
        agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=job_id,
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission=f"Orchestrator for project: {test_project.name}",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="decommissioned",
            progress=10,
        )
        db_session.add(agent_execution)
        await db_session.commit()

        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == test_project.id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == test_project.tenant_key,
                ~AgentExecution.status.in_(["decommissioned"]),
            )
        )
        result = await db_session.execute(stmt)
        found = result.scalar_one_or_none()

        assert found is None

    @pytest.mark.asyncio
    async def test_waiting_and_working_still_found(self, db_session, test_project):
        waiting_job_id = str(uuid4())
        waiting_agent_id = str(uuid4())

        agent_job_waiting = AgentJob(
            job_id=waiting_job_id,
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Waiting Orchestrator",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job_waiting)

        agent_execution_waiting = AgentExecution(
            agent_id=waiting_agent_id,
            job_id=waiting_job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
            progress=0,
        )
        db_session.add(agent_execution_waiting)

        working_job_id = str(uuid4())
        working_agent_id = str(uuid4())

        agent_job_working = AgentJob(
            job_id=working_job_id,
            tenant_key=test_project.tenant_key,
            project_id=test_project.id,
            mission="Working Orchestrator",
            job_type="orchestrator",
            status="active",
        )
        db_session.add(agent_job_working)

        agent_execution_working = AgentExecution(
            agent_id=working_agent_id,
            job_id=working_job_id,
            tenant_key=test_project.tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="working",
            progress=75,
        )
        db_session.add(agent_execution_working)

        await db_session.commit()

        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == test_project.id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == test_project.tenant_key,
                ~AgentExecution.status.in_(["decommissioned"]),
            )
        )
        result = await db_session.execute(stmt)
        found = result.scalars().all()

        assert len(found) == 2
        statuses = {f.status for f in found}
        assert statuses == {"waiting", "working"}
