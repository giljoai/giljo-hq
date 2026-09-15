# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution
from giljo_mcp.models.tasks import Message, MessageRecipient


def _recipient_agent_is_terminal_clause(tenant_key: str):
    has_any_execution = (
        select(AgentExecution.id)
        .where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == MessageRecipient.agent_id,
        )
        .exists()
    )
    has_active_execution = (
        select(AgentExecution.id)
        .where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == MessageRecipient.agent_id,
            AgentExecution.status.notin_(TERMINAL_EXECUTION_STATUSES),
        )
        .exists()
    )
    return and_(has_any_execution, ~has_active_execution)


def _should_hide_from_unread_clause(tenant_key: str):
    return and_(
        _recipient_agent_is_terminal_clause(tenant_key),
        Message.message_type == "broadcast",
        ~Message.requires_action.is_(True),
    )


class AgentLivenessMixin:

    async def get_terminal_agent_ids(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_ids: list[str],
    ) -> set[str]:
        if not agent_ids:
            return set()
        stmt = select(AgentExecution.agent_id, AgentExecution.status).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id.in_(agent_ids),
        )
        rows = (await session.execute(stmt)).all()
        statuses_by_agent: dict[str, list[str]] = {}
        for agent_id, status in rows:
            statuses_by_agent.setdefault(agent_id, []).append(status)
        return {
            agent_id
            for agent_id, statuses in statuses_by_agent.items()
            if all(status in TERMINAL_EXECUTION_STATUSES for status in statuses)
        }
