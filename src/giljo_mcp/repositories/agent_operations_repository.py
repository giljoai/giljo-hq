# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import Row, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.models import AgentTodoItem, Message
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.tasks import MessageRecipient
from giljo_mcp.repositories._agent_heartbeat_silence_mixin import AgentHeartbeatSilenceMixin
from giljo_mcp.repositories._agent_liveness_mixin import AgentLivenessMixin
from giljo_mcp.repositories._agent_unread_counts_mixin import AgentUnreadCountsMixin


RESULT_BEARING_EXECUTION_STATUSES: tuple[str, ...] = ("complete", "closed")


class AgentOperationsRepository(AgentHeartbeatSilenceMixin, AgentUnreadCountsMixin, AgentLivenessMixin):


    async def get_active_agent_ids_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[tuple[str, str | None]]:
        query = (
            select(AgentExecution.agent_id, AgentExecution.agent_display_name)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.tenant_key == tenant_key,
                AgentJob.tenant_key == tenant_key,
                AgentJob.project_id == project_id,
                AgentExecution.status.notin_(TERMINAL_EXECUTION_STATUSES),
            )
        )
        rows = (await session.execute(query)).all()
        seen: dict[str, str | None] = {}
        for agent_id, display_name in rows:
            if agent_id not in seen:
                seen[agent_id] = display_name
        return list(seen.items())

    async def get_workflow_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        exclude_job_id: str | None = None,
    ) -> list[Row]:
        query = (
            select(
                AgentExecution.job_id,
                AgentExecution.agent_id,
                AgentExecution.agent_name,
                AgentExecution.agent_display_name,
                AgentExecution.status,
                AgentExecution.messages_waiting_count,
                AgentJob.job_type,
            )
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.tenant_key == tenant_key,
                AgentJob.project_id == project_id,
                AgentJob.project_id.isnot(None),
            )
        )
        if exclude_job_id:
            query = query.where(AgentJob.job_id != exclude_job_id)
        result = await session.execute(query)
        return list(result.all())

    async def get_todo_counts_by_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        if not job_ids:
            return {}

        stmt = (
            select(
                AgentTodoItem.job_id,
                AgentTodoItem.status,
                func.count().label("cnt"),
            )
            .where(
                AgentTodoItem.job_id.in_(job_ids),
                AgentTodoItem.tenant_key == tenant_key,
            )
            .group_by(AgentTodoItem.job_id, AgentTodoItem.status)
        )
        result = await session.execute(stmt)
        rows = result.all()

        todo_map: dict[str, dict[str, int]] = {}
        for t_job_id, t_status, t_cnt in rows:
            todo_map.setdefault(t_job_id, {})[t_status] = t_cnt
        return todo_map


    async def get_pending_executions_with_jobs(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_display_name: str | None = None,
        limit: int = 10,
    ) -> list[tuple[AgentExecution, AgentJob]]:
        stmt = (
            select(AgentExecution, AgentJob)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "waiting",
            )
        )
        if agent_display_name and agent_display_name.strip():
            stmt = stmt.where(AgentExecution.agent_display_name == agent_display_name)
        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return list(result.all())

    async def get_completed_execution_result(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> dict | None:
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status.in_(RESULT_BEARING_EXECUTION_STATUSES),
            )
            .order_by(AgentExecution.completed_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        execution = result.scalar_one_or_none()
        if execution and execution.result:
            return execution.result
        return None


    async def list_jobs_paginated(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str | None = None,
        status_filter: str | None = None,
        agent_display_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
        job_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> tuple[list[tuple[AgentExecution, AgentJob]], int]:
        query = (
            select(AgentExecution, AgentJob)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .options(selectinload(AgentJob.todo_items))
            .where(AgentExecution.tenant_key == tenant_key)
        )

        if job_id:
            query = query.where(AgentJob.job_id == job_id)
        if project_id:
            query = query.where(AgentJob.project_id == project_id, AgentJob.project_id.isnot(None))
        if project_ids is not None:
            query = query.where(AgentJob.project_id.in_(project_ids))
        if status_filter:
            query = query.where(AgentExecution.status == status_filter)
        if agent_display_name:
            query = query.where(AgentExecution.agent_display_name == agent_display_name)

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar()

        query = query.order_by(AgentJob.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        rows = list(result.all())

        return rows, total or 0

    async def get_job_messages_for_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        limit: int = 50,
    ) -> tuple[AgentExecution | None, dict[str, str], list[Message]]:
        exec_stmt = select(AgentExecution).where(
            AgentExecution.job_id == job_id,
            AgentExecution.tenant_key == tenant_key,
        )
        execution = (await session.execute(exec_stmt)).scalar_one_or_none()

        if not execution:
            return None, {}, []

        agents_stmt = select(
            AgentExecution.agent_id,
            AgentExecution.agent_name,
            AgentExecution.agent_display_name,
        ).where(
            AgentExecution.tenant_key == tenant_key,
        )
        agents_result = await session.execute(agents_stmt)

        agent_lookup: dict[str, str] = {}
        for agent_id, agent_name, agent_display_name in agents_result.all():
            display_name = agent_display_name.capitalize() if agent_display_name else "Agent"
            agent_lookup[agent_id] = display_name
            if agent_name:
                agent_lookup[agent_name] = display_name

        msg_stmt = (
            select(Message)
            .outerjoin(MessageRecipient)
            .where(
                Message.tenant_key == tenant_key,
                or_(
                    Message.from_agent_id == execution.agent_id,
                    MessageRecipient.agent_id == execution.agent_id,
                ),
            )
            .options(selectinload(Message.recipients))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = (await session.execute(msg_stmt)).scalars().unique().all()

        return execution, agent_lookup, list(messages)
