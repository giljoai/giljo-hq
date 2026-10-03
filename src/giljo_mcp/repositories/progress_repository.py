# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

from sqlalchemy import delete as sql_delete
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.repositories.agent_job_repository import latest_execution_for_job


logger = logging.getLogger(__name__)


class ProgressRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def get_active_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        return await latest_execution_for_job(
            session, tenant_key, job_id, AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES)
        )

    async def get_decommissioned_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        return await latest_execution_for_job(session, tenant_key, job_id, AgentExecution.status == "decommissioned")

    async def get_completed_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        return await latest_execution_for_job(
            session, tenant_key, job_id, AgentExecution.status.in_(["complete", "closed"])
        )

    async def get_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentJob | None:
        result = await session.execute(
            select(AgentJob).where(AgentJob.job_id == job_id, AgentJob.tenant_key == tenant_key)
        )
        return result.scalar_one_or_none()


    async def get_todo_items(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> list[AgentTodoItem]:
        result = await session.execute(
            select(AgentTodoItem)
            .where(AgentTodoItem.job_id == job_id, AgentTodoItem.tenant_key == tenant_key)
            .order_by(AgentTodoItem.sequence)
        )
        return list(result.scalars().all())

    async def delete_todo_items(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> None:
        await session.execute(
            sql_delete(AgentTodoItem).where(AgentTodoItem.job_id == job_id, AgentTodoItem.tenant_key == tenant_key)
        )

    async def add_todo_item(self, session: AsyncSession, todo_item: AgentTodoItem) -> None:
        session.add(todo_item)

    async def get_max_todo_sequence(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> int:
        result = await session.execute(
            select(sa_func.max(AgentTodoItem.sequence))
            .where(AgentTodoItem.job_id == job_id)
            .where(AgentTodoItem.tenant_key == tenant_key)
        )
        return result.scalar() or -1

    async def count_todos_by_status(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        status: str,
    ) -> int:
        result = await session.execute(
            select(sa_func.count(AgentTodoItem.id))
            .where(AgentTodoItem.job_id == job_id)
            .where(AgentTodoItem.tenant_key == tenant_key)
            .where(AgentTodoItem.status == status)
        )
        return result.scalar() or 0

    async def count_all_todos(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> int:
        result = await session.execute(
            select(sa_func.count(AgentTodoItem.id))
            .where(AgentTodoItem.job_id == job_id)
            .where(AgentTodoItem.tenant_key == tenant_key)
        )
        return result.scalar() or 0


    async def refresh(self, session: AsyncSession, entity) -> None:
        await session.refresh(entity)

    async def flush(self, session: AsyncSession) -> None:
        await session.flush()
