# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.comm import CommParticipant, CommThread
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message
from giljo_mcp.repositories._comm_thread_participants_mixin import participant_display_status


def _card_title(project_name: str | None, subject: str | None) -> str | None:
    return project_name or subject


class CommThreadListEnrichmentMixin:

    async def list_threads_enriched(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        viewer_id: str,
        threads: list[CommThread],
    ) -> dict[str, dict[str, Any]]:
        thread_ids = [t.id for t in threads]
        if not thread_ids:
            return {}

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

        latest = (
            select(
                Message.id.label("message_id"),
                Message.from_display_name.label("author"),
                Message.from_agent_id.label("author_id"),
                Message.content.label("excerpt"),
                Message.created_at.label("said_at"),
            )
            .where(Message.tenant_key == tenant_key, Message.thread_id == CommThread.id)
            .order_by(Message.created_at.desc())
            .limit(1)
            .lateral("last_message")
        )

        latest_status = participant_display_status(tenant_key)

        participants = (
            select(
                func.coalesce(
                    func.jsonb_agg(
                        func.jsonb_build_object(
                            "participant_id",
                            CommParticipant.participant_id,
                            "participant_type",
                            CommParticipant.participant_type,
                            "display_name",
                            CommParticipant.display_name,
                            "role",
                            CommParticipant.role,
                            "harness",
                            CommParticipant.harness,
                            "last_seen_at",
                            CommParticipant.last_seen_at,
                            "status",
                            latest_status,
                        )
                    ),
                    func.cast("[]", JSONB),
                )
            )
            .where(
                CommParticipant.tenant_key == tenant_key,
                CommParticipant.thread_id == CommThread.id,
            )
            .scalar_subquery()
        )

        unread = (
            select(1)
            .where(
                Message.tenant_key == tenant_key,
                Message.thread_id == CommThread.id,
                or_(last_read.is_(None), Message.created_at > last_read),
            )
            .exists()
        )

        rows = await session.execute(
            select(
                CommThread.id,
                Project.name.label("project_name"),
                participants.label("participants"),
                unread.label("unread"),
                CommThread.subject,
                latest.c.message_id,
                latest.c.author,
                latest.c.author_id,
                latest.c.excerpt,
                latest.c.said_at,
            )
            .select_from(CommThread)
            .outerjoin(Project, Project.id == CommThread.project_id)
            .outerjoin(latest, true())
            .where(CommThread.tenant_key == tenant_key, CommThread.id.in_(thread_ids))
        )

        return {
            row.id: {
                "title": _card_title(row.project_name, row.subject),
                "project_name": row.project_name,
                "participants": row.participants or [],
                "unread": bool(row.unread),
                "last_message": (
                    {
                        "id": row.message_id,
                        "author": row.author or row.author_id,
                        "excerpt": row.excerpt,
                        "created_at": row.said_at.isoformat() if row.said_at else None,
                    }
                    if row.said_at is not None
                    else None
                ),
            }
            for row in rows
        }
