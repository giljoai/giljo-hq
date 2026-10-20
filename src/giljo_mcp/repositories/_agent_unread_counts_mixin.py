# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Message
from giljo_mcp.models.tasks import MessageAcknowledgment, MessageRecipient
from giljo_mcp.repositories._agent_liveness_mixin import _should_hide_from_unread_clause


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


class AgentUnreadCountsMixin:

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
