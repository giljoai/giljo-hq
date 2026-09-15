# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Row, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import AgentTodoItem, Message
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.system_setting import SystemSetting
from giljo_mcp.models.tasks import MessageAcknowledgment, MessageRecipient
from giljo_mcp.repositories._agent_liveness_mixin import AgentLivenessMixin, _should_hide_from_unread_clause


SILENCE_THRESHOLD_SETTING_KEY = "agent_silence_threshold_minutes"


def _already_acked_exists_clause(tenant_key: str):
    return (
        select(MessageAcknowledgment.id)
        .where(
            MessageAcknowledgment.message_id == Message.id,
            MessageAcknowledgment.agent_id == MessageRecipient.agent_id,
            MessageAcknowledgment.tenant_key == tenant_key,
        )
        .exists()
    )


class AgentOperationsRepository(AgentLivenessMixin):


    async def touch_heartbeat(
        self,
        session: AsyncSession,
        job_id: str,
        tenant_key: str,
        debounce_seconds: int = 30,
    ) -> bool:
        now = datetime.now(UTC)
        threshold = now - timedelta(seconds=debounce_seconds)

        conditions = [
            AgentExecution.job_id == job_id,
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.status.notin_(TERMINAL_EXECUTION_STATUSES),
            ((AgentExecution.last_activity_at.is_(None)) | (AgentExecution.last_activity_at < threshold)),
        ]

        result = await session.execute(update(AgentExecution).where(and_(*conditions)).values(last_activity_at=now))
        if result.rowcount:
            await session.flush()
            return True
        return False


    async def find_stale_working_agents(
        self,
        session: AsyncSession,
        cutoff: datetime,
    ) -> list[AgentExecution]:
        stmt = (
            select(AgentExecution)
            .options(selectinload(AgentExecution.job).selectinload(AgentJob.project))
            .where(
                AgentExecution.status == "working",
                or_(
                    AgentExecution.last_progress_at < cutoff,
                    and_(
                        AgentExecution.last_progress_at.is_(None),
                        AgentExecution.started_at < cutoff,
                    ),
                ),
            )
        )
        with tenant_isolation_bypass(
            session,
            reason="system silence monitor scans working agents across tenants",
            models=(AgentExecution, AgentJob, Project),
        ):
            result = await session.execute(stmt)
        return list(result.scalars().all())

    async def mark_agents_silent(
        self,
        session: AsyncSession,
        agents: list[AgentExecution],
    ) -> None:
        for agent in agents:
            agent.status = "silent"
        if agents:
            await session.flush()

    async def find_silent_agent_with_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> tuple[AgentExecution | None, str | None]:
        stmt = (
            select(AgentExecution, AgentJob.project_id)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "silent",
            )
        )
        result = await session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None, None
        return row[0], row[1]

    async def clear_silent_to_working(
        self,
        session: AsyncSession,
        agent: AgentExecution,
    ) -> None:
        agent.status = "working"
        agent.last_progress_at = datetime.now(UTC)
        await session.flush()

    async def find_silent_agent_by_agent_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_id: str,
    ) -> tuple[AgentExecution | None, str | None]:
        stmt = (
            select(AgentExecution, AgentJob.project_id)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.agent_id == agent_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "silent",
            )
        )
        result = await session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None, None
        return row[0], row[1]

    async def get_silence_threshold_setting(
        self,
        session: AsyncSession,
    ) -> int | None:
        stmt = select(SystemSetting.value).where(SystemSetting.key == SILENCE_THRESHOLD_SETTING_KEY)
        result = await session.execute(stmt)
        value = result.scalar_one_or_none()

        if value is None:
            return None

        try:
            return max(1, int(value))
        except ValueError:
            return None


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

    async def get_live_unread_counts_by_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_ids: list[str],
    ) -> dict[str, int]:
        if not agent_ids:
            return {}

        stmt = (
            select(MessageRecipient.agent_id, func.count(Message.id))
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id == project_id,
                Message.message_type != "completion_report",
                MessageRecipient.agent_id.in_(agent_ids),
                ~_already_acked_exists_clause(tenant_key),
                ~_should_hide_from_unread_clause(tenant_key),
            )
            .group_by(MessageRecipient.agent_id)
        )
        result = await session.execute(stmt)
        return dict(result.all())

    async def get_live_unread_counts_by_project_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
        agent_ids: list[str],
    ) -> dict[tuple[str, str], int]:
        if not project_ids or not agent_ids:
            return {}

        stmt = (
            select(Message.project_id, MessageRecipient.agent_id, func.count(Message.id))
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id.in_(project_ids),
                Message.message_type != "completion_report",
                MessageRecipient.agent_id.in_(agent_ids),
                ~_already_acked_exists_clause(tenant_key),
                ~_should_hide_from_unread_clause(tenant_key),
            )
            .group_by(Message.project_id, MessageRecipient.agent_id)
        )
        result = await session.execute(stmt)
        return {(str(pid), aid): cnt for pid, aid, cnt in result.all()}

    async def get_live_action_required_unread_counts_by_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_ids: list[str],
    ) -> dict[str, int]:
        if not agent_ids:
            return {}

        stmt = (
            select(MessageRecipient.agent_id, func.count(Message.id))
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id == project_id,
                Message.requires_action.is_(True),
                Message.auto_generated.is_(False),
                MessageRecipient.agent_id.in_(agent_ids),
                ~_already_acked_exists_clause(tenant_key),
                ~_should_hide_from_unread_clause(tenant_key),
            )
            .group_by(MessageRecipient.agent_id)
        )
        result = await session.execute(stmt)
        return dict(result.all())

    async def get_live_action_required_unread_counts_by_project_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
        agent_ids: list[str],
    ) -> dict[tuple[str, str], int]:
        if not project_ids or not agent_ids:
            return {}

        stmt = (
            select(Message.project_id, MessageRecipient.agent_id, func.count(Message.id))
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id.in_(project_ids),
                Message.requires_action.is_(True),
                Message.auto_generated.is_(False),
                MessageRecipient.agent_id.in_(agent_ids),
                ~_already_acked_exists_clause(tenant_key),
                ~_should_hide_from_unread_clause(tenant_key),
            )
            .group_by(Message.project_id, MessageRecipient.agent_id)
        )
        result = await session.execute(stmt)
        return {(str(pid), aid): cnt for pid, aid, cnt in result.all()}

    async def get_live_unread_counts_by_agent_and_thread(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        if not agent_ids:
            return {}

        stmt = (
            select(
                MessageRecipient.agent_id,
                func.coalesce(Message.thread_id, "").label("thread_id"),
                func.count(Message.id),
            )
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id == project_id,
                Message.message_type != "completion_report",
                MessageRecipient.agent_id.in_(agent_ids),
                ~_already_acked_exists_clause(tenant_key),
                ~_should_hide_from_unread_clause(tenant_key),
            )
            .group_by(MessageRecipient.agent_id, "thread_id")
        )
        result = await session.execute(stmt)
        breakdown: dict[str, dict[str, int]] = {}
        for agent_id, thread_id, count in result.all():
            breakdown.setdefault(agent_id, {})[thread_id] = count
        return breakdown

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
                AgentExecution.status == "complete",
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
