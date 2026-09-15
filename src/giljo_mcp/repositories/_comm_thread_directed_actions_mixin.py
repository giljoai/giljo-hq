# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.comm import (
    LOOP_DIRECTIVE_MESSAGE_TYPE,
    TERMINAL_THREAD_STATUSES,
    CommThread,
)
from giljo_mcp.models.tasks import (
    Message,
    MessageAcknowledgment,
    MessageRecipient,
)


class CommThreadDirectedActionsMixin:

    async def get_threads_with_pending_directed_action(
        self, session: AsyncSession, tenant_key: str, agent_id: str
    ) -> list[CommThread]:
        ack_exists = (
            select(MessageAcknowledgment.id)
            .where(
                MessageAcknowledgment.message_id == Message.id,
                MessageAcknowledgment.agent_id == agent_id,
                MessageAcknowledgment.tenant_key == tenant_key,
            )
            .exists()
        )
        stmt = (
            select(CommThread)
            .join(Message, Message.thread_id == CommThread.id)
            .join(MessageRecipient, MessageRecipient.message_id == Message.id)
            .where(
                CommThread.tenant_key == tenant_key,
                CommThread.deleted_at.is_(None),
                CommThread.status.notin_(TERMINAL_THREAD_STATUSES),
                Message.tenant_key == tenant_key,
                Message.requires_action.is_(True),
                Message.message_type.notin_(("broadcast", LOOP_DIRECTIVE_MESSAGE_TYPE)),
                MessageRecipient.tenant_key == tenant_key,
                MessageRecipient.agent_id == agent_id,
                ~ack_exists,
            )
            .distinct()
            .order_by(CommThread.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
