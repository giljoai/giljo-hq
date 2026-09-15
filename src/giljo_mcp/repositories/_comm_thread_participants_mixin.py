# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.harness_resolver import GENERIC_HARNESS
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.comm import VALID_PARTICIPANT_TYPES, CommParticipant
from giljo_mcp.utils.log_sanitizer import sanitize


def latest_execution_status(tenant_key: str):
    return (
        select(AgentExecution.status)
        .where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == CommParticipant.participant_id,
        )
        .order_by(AgentExecution.started_at.desc())
        .limit(1)
        .correlate(CommParticipant)
        .scalar_subquery()
    )


def participant_display_status(tenant_key: str):
    return func.coalesce(latest_execution_status(tenant_key), CommParticipant.self_reported_status)


_PARTICIPANT_ID_MAX = 255
_DISPLAY_NAME_MAX = 255
_ROLE_MAX = 50


class CommThreadParticipantsMixin:

    async def add_participant(
        self,
        session: AsyncSession,
        tenant_key: str,
        thread_id: str,
        *,
        participant_id: str,
        participant_type: str,
        display_name: str | None = None,
        role: str | None = None,
        harness: str | None = None,
        self_reported_status: str | None = None,
        touch_last_seen: bool = False,
        authoritative: bool = False,
    ) -> CommParticipant:
        if participant_type not in VALID_PARTICIPANT_TYPES:
            raise ValidationError(
                f"participant_type must be one of {VALID_PARTICIPANT_TYPES}, got '{participant_type}'.",
                context={"operation": "comm_thread.add_participant", "participant_type": participant_type},
            )

        if len(participant_id) > _PARTICIPANT_ID_MAX:
            raise ValidationError(
                f"participant_id exceeds {_PARTICIPANT_ID_MAX} characters.",
                context={"operation": "comm_thread.add_participant", "participant_id_len": len(participant_id)},
            )
        if display_name is not None and len(display_name) > _DISPLAY_NAME_MAX:
            display_name = display_name[:_DISPLAY_NAME_MAX]
        if role is not None and len(role) > _ROLE_MAX:
            role = role[:_ROLE_MAX]

        insert_stmt = pg_insert(CommParticipant.__table__).values(
            id=generate_uuid(),
            tenant_key=tenant_key,
            thread_id=thread_id,
            participant_id=participant_id,
            participant_type=participant_type,
            display_name=display_name,
            role=role,
            harness=harness,
            last_seen_at=datetime.now(UTC) if touch_last_seen else None,
            self_reported_status=self_reported_status,
            self_reported_status_at=datetime.now(UTC) if self_reported_status else None,
        )
        excluded = insert_stmt.excluded
        existing = CommParticipant.__table__.c

        def claimed(column_name: str):
            incoming, current = getattr(excluded, column_name), existing[column_name]
            return func.coalesce(incoming, current) if authoritative else func.coalesce(current, incoming)

        await session.execute(
            insert_stmt.on_conflict_do_update(
                constraint="uq_comm_participant",
                set_={
                    "display_name": claimed("display_name"),
                    "role": claimed("role"),
                    "harness": func.coalesce(
                        func.nullif(excluded.harness, GENERIC_HARNESS),
                        existing.harness,
                        excluded.harness,
                    ),
                    "last_seen_at": func.coalesce(excluded.last_seen_at, existing.last_seen_at),
                    "self_reported_status": func.coalesce(excluded.self_reported_status, existing.self_reported_status),
                    "self_reported_status_at": func.coalesce(
                        excluded.self_reported_status_at, existing.self_reported_status_at
                    ),
                },
            )
        )
        await session.flush()

        row = (
            await session.execute(
                select(CommParticipant)
                .where(
                    CommParticipant.tenant_key == tenant_key,
                    CommParticipant.thread_id == thread_id,
                    CommParticipant.participant_id == participant_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:  # pragma: no cover - insert+select within one tx always resolves
            raise RuntimeError(f"Failed to register participant {sanitize(participant_id)} on thread {thread_id}")
        return row

    async def touch_participant_last_seen(
        self,
        session: AsyncSession,
        tenant_key: str,
        participant_id: str,
        *,
        thread_id: str | None = None,
    ) -> None:
        conditions = [
            CommParticipant.tenant_key == tenant_key,
            CommParticipant.participant_id == participant_id,
        ]
        if thread_id is not None:
            conditions.append(CommParticipant.thread_id == thread_id)
        await session.execute(update(CommParticipant).where(*conditions).values(last_seen_at=datetime.now(UTC)))

    async def get_participants(self, session: AsyncSession, tenant_key: str, thread_id: str) -> list[CommParticipant]:
        result = await session.execute(
            select(CommParticipant).where(
                CommParticipant.tenant_key == tenant_key,
                CommParticipant.thread_id == thread_id,
            )
        )
        return list(result.scalars().all())

    async def get_participants_with_status(
        self, session: AsyncSession, tenant_key: str, thread_id: str
    ) -> list[tuple[CommParticipant, str | None]]:
        result = await session.execute(
            select(CommParticipant, participant_display_status(tenant_key)).where(
                CommParticipant.tenant_key == tenant_key,
                CommParticipant.thread_id == thread_id,
            )
        )
        return [(row[0], row[1]) for row in result.all()]

    async def get_participant(
        self, session: AsyncSession, tenant_key: str, thread_id: str, participant_id: str
    ) -> CommParticipant | None:
        result = await session.execute(
            select(CommParticipant).where(
                CommParticipant.tenant_key == tenant_key,
                CommParticipant.thread_id == thread_id,
                CommParticipant.participant_id == participant_id,
            )
        )
        return result.scalar_one_or_none()
