# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.comm import (
    CHT_TAXONOMY_ABBR,
    LOOP_DIRECTIVE_MESSAGE_TYPE,
    TERMINAL_THREAD_STATUSES,
    CommParticipant,
    CommThread,
)
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import (
    Message,
    MessageAcknowledgment,
    MessageCompletion,
    MessageRecipient,
)
from giljo_mcp.repositories._comm_thread_chain_hub_mixin import CommThreadChainHubMixin
from giljo_mcp.repositories._comm_thread_directed_actions_mixin import CommThreadDirectedActionsMixin
from giljo_mcp.repositories._comm_thread_keyset import (
    resolve_thread_cursor,
    thread_keyset_after,
    thread_list_order_clauses,
)
from giljo_mcp.repositories._comm_thread_list_enrichment_mixin import CommThreadListEnrichmentMixin
from giljo_mcp.repositories._comm_thread_participants_mixin import CommThreadParticipantsMixin
from giljo_mcp.repositories._comm_thread_project_tags_mixin import CommThreadProjectTagsMixin
from giljo_mcp.repositories._comm_thread_tenant_refs_mixin import CommThreadTenantRefsMixin
from giljo_mcp.repositories._comm_thread_unread_mentions_mixin import CommThreadUnreadMentionsMixin
from giljo_mcp.repositories.taxonomy_repository import TaxonomyRepository
from giljo_mcp.schemas.comm_jsonb_validators import validate_comm_thread_resolution
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class CommThreadRepository(
    CommThreadChainHubMixin,
    CommThreadDirectedActionsMixin,
    CommThreadListEnrichmentMixin,
    CommThreadParticipantsMixin,
    CommThreadProjectTagsMixin,
    CommThreadTenantRefsMixin,
    CommThreadUnreadMentionsMixin,
):

    def __init__(self) -> None:
        self._taxonomy = TaxonomyRepository()

    async def _ensure_cht_type(self, session: AsyncSession, tenant_key: str) -> None:
        row = await self._taxonomy.get_by_abbreviation(session, tenant_key, CHT_TAXONOMY_ABBR)
        if row is None:
            raise ValidationError(
                f"The '{CHT_TAXONOMY_ABBR}' chat-thread taxonomy type is missing for this "
                "tenant. Run database migrations (ce_0054 backfill) before creating threads.",
                context={"operation": "comm_thread.create", "abbreviation": CHT_TAXONOMY_ABBR},
            )

    async def mint_serial(self, session: AsyncSession, tenant_key: str) -> int:
        current_max = (
            await session.execute(
                select(func.coalesce(func.max(CommThread.serial), 0)).where(CommThread.tenant_key == tenant_key)
            )
        ).scalar_one()
        return int(current_max) + 1

    async def create_thread(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        subject: str | None = None,
        status: str = "open",
        next_action_owner: str | None = None,
        severity: str | None = None,
        product_id: str | None = None,
        project_id: str | None = None,
        resolution: dict | None = None,
        sequence_run_id: str | None = None,
    ) -> CommThread:
        if not tenant_key:
            raise ValidationError("tenant_key is required", context={"operation": "comm_thread.create"})

        await self._ensure_cht_type(session, tenant_key)
        if product_id:
            await self._require_owned_reference(
                session, tenant_key, model=Product, row_id=product_id, field="product_id"
            )
        if project_id:
            await self._require_owned_reference(
                session, tenant_key, model=Project, row_id=project_id, field="project_id"
            )
        if sequence_run_id:
            await self._require_sequence_run(session, tenant_key, sequence_run_id)
            await self._require_run_is_unhubbed(session, tenant_key, sequence_run_id)
        validated_resolution = validate_comm_thread_resolution(resolution)
        serial = await self.mint_serial(session, tenant_key)

        thread = CommThread(
            tenant_key=tenant_key,
            serial=serial,
            subject=subject,
            status=status,
            next_action_owner=next_action_owner,
            severity=severity,
            product_id=product_id,
            project_id=project_id,
            resolution=validated_resolution,
            sequence_run_id=sequence_run_id,
        )
        session.add(thread)
        await session.flush()
        logger.info(
            "Created comm thread %s (%s) for tenant %s",
            thread.id,
            thread.taxonomy_alias,
            sanitize(tenant_key),
        )
        return thread

    async def resolve_or_create_bound_thread(
        self, session: AsyncSession, tenant_key: str, project_id: str, *, marker: str
    ) -> CommThread:
        if not project_id:
            raise ValidationError("project_id is required", context={"operation": "comm_thread.resolve_bound"})
        existing = (
            await session.execute(
                select(CommThread)
                .where(
                    CommThread.tenant_key == tenant_key,
                    CommThread.project_id == project_id,
                    CommThread.deleted_at.is_(None),
                )
                .order_by(case((CommThread.subject == marker, 0), else_=1), CommThread.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        product_id = (
            await session.execute(
                select(Project.product_id).where(
                    Project.tenant_key == tenant_key,
                    Project.id == project_id,
                )
            )
        ).scalar_one_or_none()
        return await self.create_thread(
            session, tenant_key, subject=marker, project_id=project_id, product_id=product_id
        )

    async def get_by_id(self, session: AsyncSession, tenant_key: str, thread_id: str) -> CommThread | None:
        result = await session.execute(
            select(CommThread).where(
                CommThread.tenant_key == tenant_key,
                CommThread.id == thread_id,
                CommThread.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def soft_delete(self, session: AsyncSession, tenant_key: str, thread_id: str) -> bool:
        thread = await self.get_by_id(session, tenant_key, thread_id)
        if thread is None:
            return False
        thread.deleted_at = func.now()
        await session.flush()
        return True

    async def get_deleted_by_id(self, session: AsyncSession, tenant_key: str, thread_id: str) -> CommThread | None:
        result = await session.execute(
            select(CommThread).where(
                CommThread.tenant_key == tenant_key,
                CommThread.id == thread_id,
                CommThread.deleted_at.isnot(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_deleted(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        product_id: str | None = None,
        project_id: str | None = None,
    ) -> list[CommThread]:
        query = select(CommThread).where(
            CommThread.tenant_key == tenant_key,
            CommThread.deleted_at.isnot(None),
        )
        if product_id is not None:
            query = query.where(CommThread.product_id == product_id)
        if project_id is not None:
            query = query.where(CommThread.project_id == project_id)
        query = query.order_by(CommThread.deleted_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def hard_delete(self, session: AsyncSession, tenant_key: str, thread_id: str) -> bool:
        thread = await self.get_deleted_by_id(session, tenant_key, thread_id)
        if thread is None:
            return False
        await session.delete(thread)
        await session.flush()
        return True

    async def restore(self, session: AsyncSession, tenant_key: str, thread_id: str) -> CommThread | None:
        thread = await self.get_deleted_by_id(session, tenant_key, thread_id)
        if thread is None:
            return None
        thread.deleted_at = None
        await session.flush()
        return thread

    async def list_threads(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        status: str | None = None,
        next_action_owner: str | None = None,
        product_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
        before_id: str | None = None,
        exclude_terminal: bool = False,
        participant_id: str | None = None,
    ) -> list[CommThread]:
        query = select(CommThread).where(
            CommThread.tenant_key == tenant_key,
            CommThread.deleted_at.is_(None),
        )
        if status is not None:
            query = query.where(CommThread.status == status)
        if exclude_terminal:
            query = query.where(CommThread.status.notin_(TERMINAL_THREAD_STATUSES))
        if participant_id is not None:
            query = query.join(CommParticipant, CommParticipant.thread_id == CommThread.id).where(
                CommParticipant.tenant_key == tenant_key,
                CommParticipant.participant_id == participant_id,
            )
        if next_action_owner is not None:
            query = query.where(CommThread.next_action_owner == next_action_owner)
        if product_id is not None:
            query = query.where(CommThread.product_id == product_id)
        if project_id is not None:
            query = query.where(CommThread.project_id == project_id)

        if before_id is not None:
            cursor_ts = await resolve_thread_cursor(session, tenant_key, before_id)
            query = query.where(thread_keyset_after(cursor_ts, before_id))

        query = query.order_by(*thread_list_order_clauses())
        if limit is not None and limit > 0:
            query = query.limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_recipient_state_for_messages(
        self, session: AsyncSession, tenant_key: str, *, message_ids: list[str]
    ) -> dict[str, dict[str, list[str]]]:
        if not message_ids:
            return {}

        out: dict[str, dict[str, list[str]]] = {
            mid: {"recipients": [], "acked_by": [], "completed_by": []} for mid in message_ids
        }

        for model, key in (
            (MessageRecipient, "recipients"),
            (MessageAcknowledgment, "acked_by"),
            (MessageCompletion, "completed_by"),
        ):
            stmt = (
                select(model.message_id, func.array_agg(model.agent_id))
                .where(model.tenant_key == tenant_key, model.message_id.in_(message_ids))
                .group_by(model.message_id)
            )
            for mid, agents in (await session.execute(stmt)).all():
                if mid in out:
                    out[mid][key] = [a for a in (agents or []) if a is not None]

        return out


    async def set_next_action_owner(
        self, session: AsyncSession, tenant_key: str, thread_id: str, owner: str | None
    ) -> CommThread | None:
        thread = await self.get_by_id(session, tenant_key, thread_id)
        if thread is None:
            return None
        thread.next_action_owner = owner
        await session.flush()
        return thread

    async def set_status(
        self, session: AsyncSession, tenant_key: str, thread_id: str, status: str
    ) -> CommThread | None:
        thread = await self.get_by_id(session, tenant_key, thread_id)
        if thread is None:
            return None
        thread.status = status
        await session.flush()
        return thread

    async def get_thread_messages(
        self,
        session: AsyncSession,
        tenant_key: str,
        thread_id: str,
        *,
        after_message_id: str | None = None,
        since: datetime | None = None,
        tail: int | None = None,
        unread_after: datetime | None = None,
        directed_to: str | None = None,
        action_required_only: bool = False,
    ) -> list[Message]:
        conditions = [Message.tenant_key == tenant_key, Message.thread_id == thread_id]

        if after_message_id:
            marker = (
                await session.execute(
                    select(Message.created_at).where(
                        Message.tenant_key == tenant_key,
                        Message.thread_id == thread_id,
                        Message.id == after_message_id,
                    )
                )
            ).scalar_one_or_none()
            if marker is None:
                return []
            conditions.append(Message.created_at > marker)

        if since is not None:
            conditions.append(Message.created_at > since)

        if unread_after is not None:
            conditions.append(Message.created_at > unread_after)

        if directed_to is not None:
            conditions.append(
                exists().where(
                    MessageRecipient.message_id == Message.id,
                    MessageRecipient.agent_id == directed_to,
                    MessageRecipient.tenant_key == tenant_key,
                )
            )

        if action_required_only:
            conditions.append(Message.requires_action.is_(True))

        if tail is not None and tail > 0:
            result = await session.execute(
                select(Message).where(*conditions).order_by(Message.created_at.desc()).limit(tail)
            )
            return list(reversed(result.scalars().all()))

        result = await session.execute(select(Message).where(*conditions).order_by(Message.created_at.asc()))
        return list(result.scalars().all())

    async def ack_messages_for_participant(
        self, session: AsyncSession, tenant_key: str, *, agent_id: str, message_ids: list[str]
    ) -> int:
        if not message_ids:
            return 0
        rows = [
            {"id": generate_uuid(), "message_id": mid, "agent_id": agent_id, "tenant_key": tenant_key}
            for mid in message_ids
        ]
        stmt = (
            pg_insert(MessageAcknowledgment.__table__)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_msg_ack")
            .returning(MessageAcknowledgment.__table__.c.id)
        )
        newly_acked = len((await session.execute(stmt)).scalars().all())
        await session.flush()
        return newly_acked

    async def search_threads(
        self, session: AsyncSession, tenant_key: str, query: str, *, limit: int = 50
    ) -> list[CommThread]:
        like = f"%{query.strip()}%"
        conditions = [CommThread.subject.ilike(like)]

        digits = "".join(ch for ch in query if ch.isdigit())
        order = [CommThread.created_at.desc()]
        if digits and len(digits) <= 9:
            conditions.append(serial_match := CommThread.serial == int(digits))
            order.insert(0, case((serial_match, 0), else_=1))

        msg_exists = (
            select(Message.id)
            .where(
                Message.tenant_key == tenant_key,
                Message.thread_id == CommThread.id,
                Message.content.ilike(like),
            )
            .exists()
        )
        participant_exists = (
            select(CommParticipant.id)
            .where(
                CommParticipant.tenant_key == tenant_key,
                CommParticipant.thread_id == CommThread.id,
                or_(
                    CommParticipant.participant_id.ilike(like),
                    CommParticipant.display_name.ilike(like),
                ),
            )
            .exists()
        )
        conditions.extend([msg_exists, participant_exists])

        result = await session.execute(
            select(CommThread)
            .where(
                CommThread.tenant_key == tenant_key,
                CommThread.deleted_at.is_(None),
                or_(*conditions),
            )
            .order_by(*order)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def has_active_loop_directive(self, session: AsyncSession, tenant_key: str, agent_id: str) -> bool:
        stmt = (
            select(Message.id)
            .join(MessageRecipient, MessageRecipient.message_id == Message.id)
            .join(CommThread, CommThread.id == Message.thread_id)
            .where(
                Message.tenant_key == tenant_key,
                Message.message_type == LOOP_DIRECTIVE_MESSAGE_TYPE,
                MessageRecipient.tenant_key == tenant_key,
                MessageRecipient.agent_id == agent_id,
                CommThread.tenant_key == tenant_key,
                CommThread.status.notin_(TERMINAL_THREAD_STATUSES),
                CommThread.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.first() is not None

    async def persist_thread_message(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        thread_id: str,
        project_id: str | None,
        content: str,
        from_agent_id: str,
        from_display_name: str,
        message_type: str,
        priority: str,
        requires_action: bool,
        recipient_ids: list[str],
        loop_interval_minutes: int | None = None,
        from_kind: str = "agent",
    ) -> Message:
        message = Message(
            tenant_key=tenant_key,
            thread_id=thread_id,
            project_id=project_id,
            content=content,
            message_type=message_type,
            priority=priority,
            status="pending",
            from_agent_id=from_agent_id,
            from_display_name=from_display_name,
            from_kind=from_kind,
            requires_action=requires_action,
            loop_interval_minutes=loop_interval_minutes,
        )
        session.add(message)
        await session.flush()
        for rid in recipient_ids:
            session.add(MessageRecipient(message_id=message.id, agent_id=rid, tenant_key=tenant_key))
        await session.flush()
        return message

    async def get_latest_loop_directive(self, session: AsyncSession, tenant_key: str, thread_id: str) -> Message | None:
        result = await session.execute(
            select(Message)
            .where(
                Message.tenant_key == tenant_key,
                Message.thread_id == thread_id,
                Message.message_type == LOOP_DIRECTIVE_MESSAGE_TYPE,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_loop_directives_for_agent(
        self, session: AsyncSession, tenant_key: str, agent_id: str
    ) -> list[dict]:
        latest = (
            select(
                Message.thread_id.label("thread_id"),
                Message.loop_interval_minutes.label("interval_minutes"),
            )
            .where(
                Message.tenant_key == tenant_key,
                Message.message_type == LOOP_DIRECTIVE_MESSAGE_TYPE,
                Message.thread_id.isnot(None),
            )
            .order_by(Message.thread_id, Message.created_at.desc(), Message.id.desc())
            .distinct(Message.thread_id)
            .subquery()
        )
        stmt = (
            select(
                CommThread.id,
                CommThread.serial,
                latest.c.interval_minutes,
            )
            .join(latest, latest.c.thread_id == CommThread.id)
            .join(CommParticipant, CommParticipant.thread_id == CommThread.id)
            .where(
                CommThread.tenant_key == tenant_key,
                CommThread.deleted_at.is_(None),
                CommThread.status.notin_(TERMINAL_THREAD_STATUSES),
                CommParticipant.tenant_key == tenant_key,
                CommParticipant.participant_id == agent_id,
            )
        )
        rows = (await session.execute(stmt)).all()
        return [{"thread_id": row.id, "serial": row.serial, "interval_minutes": row.interval_minutes} for row in rows]
