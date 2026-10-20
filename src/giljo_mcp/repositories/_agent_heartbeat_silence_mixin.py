# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.domain.job_activity import OPEN_TODO_STATUSES
from giljo_mcp.models import AgentTodoItem
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.system_setting import SystemSetting


SILENCE_THRESHOLD_SETTING_KEY = "agent_silence_threshold_minutes"


class AgentHeartbeatSilenceMixin:


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
        todo = select(AgentTodoItem.id).where(
            AgentTodoItem.job_id == AgentExecution.job_id, AgentTodoItem.tenant_key == AgentExecution.tenant_key
        )
        not_holding = or_(~todo.exists(), todo.where(AgentTodoItem.status.in_(OPEN_TODO_STATUSES)).exists())
        stmt = (
            select(AgentExecution)
            .options(selectinload(AgentExecution.job).selectinload(AgentJob.project))
            .where(
                AgentExecution.status == "working",
                or_(
                    AgentExecution.last_progress_at < cutoff,
                    and_(AgentExecution.last_progress_at.is_(None), AgentExecution.started_at < cutoff),
                ),
                not_holding,
            )
        )
        with tenant_isolation_bypass(
            session,
            reason="system silence monitor scans working agents across tenants",
            models=(AgentExecution, AgentJob, Project, AgentTodoItem),
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
