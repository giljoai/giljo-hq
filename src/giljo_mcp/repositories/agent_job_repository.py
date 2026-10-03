# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Message, ProductMemoryEntry, Project
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.tasks import MessageRecipient


async def latest_execution_for_job(
    session: AsyncSession, tenant_key: str, job_id: str, status_clause: ColumnElement[bool]
) -> AgentExecution | None:
    result = await session.execute(
        select(AgentExecution)
        .where(AgentExecution.job_id == job_id, AgentExecution.tenant_key == tenant_key, status_clause)
        .order_by(AgentExecution.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


class AgentJobRepository:

    def __init__(self, db_manager):
        self.db = db_manager


    async def get_execution_by_agent_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_id: str,
    ) -> AgentExecution | None:
        stmt = select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == agent_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_execution_by_job_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        stmt = select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.job_id == job_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_agent_job_by_job_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentJob | None:
        stmt = select(AgentJob).where(
            AgentJob.tenant_key == tenant_key,
            AgentJob.job_id == job_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_execution_for_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
            )
            .order_by(AgentExecution.started_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


    async def find_blocked_execution_for_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        return await latest_execution_for_job(session, tenant_key, job_id, AgentExecution.status == "blocked")

    async def find_complete_execution_for_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        return await latest_execution_for_job(session, tenant_key, job_id, AgentExecution.status == "complete")

    async def find_active_execution_for_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        return await latest_execution_for_job(
            session, tenant_key, job_id, AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES)
        )

    async def get_project_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        result = await session.execute(
            select(Project).where(
                Project.id == project_id,
                Project.tenant_key == tenant_key,
            )
        )
        return result.scalar_one_or_none()

    async def check_memory_entry_exists(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> bool:
        stmt = (
            select(ProductMemoryEntry)
            .where(
                ProductMemoryEntry.project_id == project_id,
                ProductMemoryEntry.tenant_key == tenant_key,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def find_orchestrator_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> AgentExecution | None:
        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_auto_completion_message(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        from_agent_id: str,
        from_display_name: str,
        content: str,
        recipient_agent_id: str,
    ) -> Message:
        auto_message = Message(
            tenant_key=tenant_key,
            project_id=project_id,
            from_agent_id=from_agent_id,
            from_display_name=from_display_name,
            auto_generated=True,
            content=content,
            message_type="completion_report",
            status="pending",
        )
        session.add(auto_message)
        await session.flush()
        session.add(
            MessageRecipient(
                message_id=auto_message.id,
                agent_id=recipient_agent_id,
                tenant_key=tenant_key,
            )
        )
        return auto_message

    async def find_other_active_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        exclude_execution_id: int,
    ) -> AgentExecution | None:
        stmt = select(AgentExecution).where(
            AgentExecution.job_id == job_id,
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.id != exclude_execution_id,
            AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def flush(self, session: AsyncSession) -> None:
        await session.flush()


    async def add_execution_for_existing_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        execution: AgentExecution,
    ) -> tuple[AgentJob, AgentExecution]:
        job_result = await session.execute(
            select(AgentJob).where(
                AgentJob.job_id == job_id,
                AgentJob.tenant_key == tenant_key,
            )
        )
        job = job_result.scalar_one_or_none()

        if not job:
            raise ValueError(f"AgentJob with job_id={job_id} not found for tenant {tenant_key}")

        session.add(execution)
        await session.flush()
        await session.refresh(execution)
        return job, execution

    async def complete_job_with_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> tuple[AgentJob | None, list[AgentExecution]]:
        job_result = await session.execute(
            select(AgentJob).where(and_(AgentJob.job_id == job_id, AgentJob.tenant_key == tenant_key))
        )
        job = job_result.scalar_one_or_none()

        if not job:
            return None, []

        job.status = "completed"
        job.completed_at = datetime.now(UTC)

        executions_result = await session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
            )
        )
        executions = executions_result.scalars().all()

        for execution in executions:
            execution.status = "complete"

        await session.flush()
        await session.refresh(job)
        for execution in executions:
            await session.refresh(execution)

        return job, list(executions)

    async def list_team_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        include_inactive: bool = False,
    ) -> list[AgentExecution]:
        query = select(AgentExecution).where(
            and_(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
            )
        )

        if not include_inactive:
            query = query.where(AgentExecution.status.in_(["waiting", "working", "blocked"]))

        result = await session.execute(query.order_by(AgentExecution.started_at))
        return list(result.scalars().all())
