# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentTodoItem, Message
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.tasks import MessageAcknowledgment, MessageRecipient
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_agent_selection import template_ids_for_product


class AgentCompletionRepository:

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


    async def find_active_execution_for_completion(
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
                AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_unread_messages_for_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_id: str,
    ) -> list[Message]:
        already_acked = (
            select(MessageAcknowledgment.id)
            .where(
                MessageAcknowledgment.message_id == Message.id,
                MessageAcknowledgment.agent_id == agent_id,
                MessageAcknowledgment.tenant_key == tenant_key,
            )
            .exists()
        )
        stmt = (
            select(Message)
            .join(MessageRecipient)
            .where(
                and_(
                    Message.tenant_key == tenant_key,
                    Message.project_id == project_id,
                    Message.requires_action.is_(True),
                    Message.auto_generated.is_(False),
                    MessageRecipient.agent_id == agent_id,
                    ~already_acked,
                )
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_undrained_messages_for_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_id: str,
    ) -> list[Message]:
        already_acked = (
            select(MessageAcknowledgment.id)
            .where(
                MessageAcknowledgment.message_id == Message.id,
                MessageAcknowledgment.agent_id == agent_id,
                MessageAcknowledgment.tenant_key == tenant_key,
            )
            .exists()
        )
        stmt = (
            select(Message)
            .join(MessageRecipient)
            .where(
                and_(
                    Message.tenant_key == tenant_key,
                    Message.project_id == project_id,
                    MessageRecipient.agent_id == agent_id,
                    ~already_acked,
                )
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_incomplete_todos(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> list[AgentTodoItem]:
        stmt = select(AgentTodoItem).where(
            and_(
                AgentTodoItem.job_id == job_id,
                AgentTodoItem.tenant_key == tenant_key,
                AgentTodoItem.status.notin_(["completed", "skipped"]),
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def find_other_active_executions_by_agent_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        exclude_agent_id: str,
    ) -> AgentExecution | None:
        stmt = select(AgentExecution).where(
            AgentExecution.job_id == job_id,
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id != exclude_agent_id,
            AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_decommissioned_execution(
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
                AgentExecution.status == "decommissioned",
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


    async def persist_job_and_execution(
        self,
        session: AsyncSession,
        agent_job: AgentJob,
        agent_execution: AgentExecution,
        project: Any | None = None,
        is_orchestrator: bool = False,
    ) -> tuple[AgentJob, AgentExecution]:
        session.add(agent_job)

        if is_orchestrator and project is not None:
            project.staging_status = "staging"
            project.updated_at = datetime.now(UTC)

        session.add(agent_execution)
        await session.flush()
        await session.refresh(agent_job)
        await session.refresh(agent_execution)
        return agent_job, agent_execution

    async def get_predecessor_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        predecessor_job_id: str,
    ) -> AgentJob | None:
        result = await session.execute(
            select(AgentJob).where(
                and_(
                    AgentJob.job_id == predecessor_job_id,
                    AgentJob.tenant_key == tenant_key,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_completed_execution_for_job(
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
                AgentExecution.status == "complete",
            )
            .order_by(AgentExecution.completed_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_display_names_in_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> set[str]:
        result = await session.execute(
            select(AgentExecution.agent_display_name)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.status.in_(["waiting", "working", "blocked"]),
                )
            )
        )
        return {row[0] for row in result.fetchall()}

    async def get_active_template_names(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        product_id: str | None = None,
    ) -> list[str]:
        template_ids = await template_ids_for_product(session, product_id, tenant_key)

        stmt = select(AgentTemplate.name).where(
            and_(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.deleted_at.is_(None),
            )
        )
        if template_ids is not None:
            stmt = stmt.where(AgentTemplate.id.in_(template_ids))

        result = await session.execute(stmt)
        return [row[0] for row in result.fetchall()]

    async def find_active_orchestrator_in_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> AgentExecution | None:
        result = await session.execute(
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.agent_display_name == "orchestrator",
                    AgentExecution.status.in_(["waiting", "working", "blocked"]),
                )
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_template_by_name(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_name: str,
        *,
        product_id: str | None = None,
    ) -> AgentTemplate | None:
        template_ids = await template_ids_for_product(session, product_id, tenant_key)

        stmt = select(AgentTemplate).where(
            and_(
                AgentTemplate.name == agent_name,
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.deleted_at.is_(None),
            )
        )
        if template_ids is not None:
            stmt = stmt.where(AgentTemplate.id.in_(template_ids))

        result = await session.execute(stmt.order_by(AgentTemplate.created_at.desc()).limit(1))
        return result.scalars().first()
