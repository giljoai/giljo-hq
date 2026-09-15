# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy import and_, case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Message, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob


logger = logging.getLogger(__name__)


class MessageRepository:

    def __init__(self):
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def batch_update_counters(
        self,
        session: AsyncSession,
        tenant_key: str,
        sent_increments: dict[str, int] | None = None,
        waiting_increments: dict[str, int] | None = None,
    ) -> int:
        sent_increments = sent_increments or {}
        waiting_increments = waiting_increments or {}

        all_agent_ids = set(sent_increments.keys()) | set(waiting_increments.keys())
        if not all_agent_ids:
            return 0

        values: dict = {}

        if sent_increments:
            values["messages_sent_count"] = case(
                *[
                    (AgentExecution.agent_id == agent_id, AgentExecution.messages_sent_count + inc)
                    for agent_id, inc in sent_increments.items()
                ],
                else_=AgentExecution.messages_sent_count,
            )

        if waiting_increments:
            values["messages_waiting_count"] = case(
                *[
                    (AgentExecution.agent_id == agent_id, AgentExecution.messages_waiting_count + inc)
                    for agent_id, inc in waiting_increments.items()
                ],
                else_=AgentExecution.messages_waiting_count,
            )

        stmt = (
            update(AgentExecution)
            .where(
                AgentExecution.agent_id.in_(all_agent_ids),
                AgentExecution.tenant_key == tenant_key,
            )
            .values(**values)
        )
        result = await session.execute(stmt)

        self._logger.debug(
            "Batch counter update: %d rows affected (sent=%s, waiting=%s)",
            result.rowcount,
            list(sent_increments.keys()),
            list(waiting_increments.keys()),
        )
        return result.rowcount


    async def get_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        result = await session.execute(
            select(Project).where(
                and_(
                    Project.tenant_key == tenant_key,
                    Project.id == project_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_message_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        message_id: str,
    ) -> Message | None:
        result = await session.execute(
            select(Message).where(
                and_(
                    Message.tenant_key == tenant_key,
                    Message.id == message_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def resolve_sender_display_name(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        from_agent: str,
    ) -> str | None:
        result = await session.execute(
            select(AgentExecution.agent_display_name)
            .join(AgentJob)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentExecution.tenant_key == tenant_key,
                    (AgentExecution.agent_display_name == from_agent) | (AgentExecution.agent_id == from_agent),
                )
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def flush(self, session: AsyncSession) -> None:
        await session.flush()

    async def get_execution_by_agent_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_id: str,
    ) -> AgentExecution | None:
        result = await session.execute(
            select(AgentExecution)
            .where(
                AgentExecution.agent_id == agent_id,
                AgentExecution.tenant_key == tenant_key,
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_agent_job_by_job_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentJob | None:
        result = await session.execute(
            select(AgentJob).where(
                AgentJob.job_id == job_id,
                AgentJob.tenant_key == tenant_key,
            )
        )
        return result.scalar_one_or_none()

    async def get_job_id_and_project_for_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> Any:
        result = await session.execute(
            select(AgentJob.job_id, AgentJob.project_id, Project.product_id)
            .outerjoin(
                Project,
                and_(Project.id == AgentJob.project_id, Project.tenant_key == AgentJob.tenant_key),
            )
            .where(
                AgentJob.job_id == job_id,
                AgentJob.tenant_key == tenant_key,
            )
        )
        return result.first()
