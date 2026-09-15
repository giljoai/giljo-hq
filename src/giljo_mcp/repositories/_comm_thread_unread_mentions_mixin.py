# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.comm import TERMINAL_THREAD_STATUSES, CommParticipant, CommThread
from giljo_mcp.models.tasks import Message


_LIKE_ESCAPE = "\\"


def _literal_contains_pattern(needle: str) -> str:
    escaped = needle.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
    escaped = escaped.replace("%", f"{_LIKE_ESCAPE}%").replace("_", f"{_LIKE_ESCAPE}_")
    return f"%{escaped}%"


class CommThreadUnreadMentionsMixin:

    async def get_unread_mentions(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        viewer_id: str,
        display_name: str | None,
    ) -> list[tuple[CommThread, str]]:
        if not display_name:
            return []

        last_read = (
            select(CommParticipant.last_read_at)
            .where(
                CommParticipant.tenant_key == tenant_key,
                CommParticipant.thread_id == CommThread.id,
                CommParticipant.participant_id == viewer_id,
            )
            .correlate(CommThread)
            .scalar_subquery()
        )

        stmt = (
            select(CommThread, Message.id)
            .join(Message, Message.thread_id == CommThread.id)
            .where(
                CommThread.tenant_key == tenant_key,
                CommThread.deleted_at.is_(None),
                CommThread.status.notin_(TERMINAL_THREAD_STATUSES),
                Message.tenant_key == tenant_key,
                Message.content.ilike(_literal_contains_pattern(display_name), escape=_LIKE_ESCAPE),
                or_(Message.from_agent_id.is_(None), Message.from_agent_id != viewer_id),
                or_(last_read.is_(None), Message.created_at > last_read),
            )
            .order_by(Message.created_at.desc())
        )
        result = await session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
