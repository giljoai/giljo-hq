# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CommThreadRepository — persistence + CHT serial minting for the Agent
Message Hub (BE-6054a Data Foundation).

This is the data-foundation seam the MCP tool surface (BE-6054b) builds its
reads/writes on. It owns:

- ``mint_serial`` — the per-tenant ``CHT-####`` counter (``max(serial)+1``).
- ``create_thread`` — verify the tenant has the reserved CHT taxonomy type
  (else a clear 422, never a confusing serial), mint the serial, validate the
  ``resolution`` JSONB, and persist the thread.
- ``add_participant`` — collision-safe join (upsert on the
  ``(thread_id, participant_id)`` unique; see the per-column conflict rules there).
- tenant-filtered reads (``get_by_id``, ``list_threads``).

CRITICAL: every query filters ``tenant_key`` — no exceptions.
Edition Scope: CE.
"""

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
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import (
    Message,
    MessageAcknowledgment,
    MessageCompletion,
    MessageRecipient,
)
from giljo_mcp.repositories._comm_thread_chain_hub_mixin import CommThreadChainHubMixin
from giljo_mcp.repositories._comm_thread_directed_actions_mixin import CommThreadDirectedActionsMixin
from giljo_mcp.repositories._comm_thread_list_enrichment_mixin import CommThreadListEnrichmentMixin
from giljo_mcp.repositories._comm_thread_participants_mixin import CommThreadParticipantsMixin
from giljo_mcp.repositories.taxonomy_repository import TaxonomyRepository
from giljo_mcp.schemas.comm_jsonb_validators import validate_comm_thread_resolution
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class CommThreadRepository(
    CommThreadChainHubMixin,
    CommThreadDirectedActionsMixin,
    CommThreadListEnrichmentMixin,
    CommThreadParticipantsMixin,
):
    """Data access for comm_threads / comm_participants."""

    def __init__(self) -> None:
        self._taxonomy = TaxonomyRepository()

    async def _ensure_cht_type(self, session: AsyncSession, tenant_key: str) -> None:
        """Confirm the tenant has the reserved CHT taxonomy type.

        The CHT row is seeded for new tenants (``DEFAULT_TAXONOMY_TYPES``) and
        backfilled for existing tenants (``ce_0054``). If it is somehow absent we
        fail loudly with a 422 rather than minting an orphan serial — this is the
        exact 422 the scope warns about ("minting CHT-0001 would 422").

        Note: we look the row up DIRECTLY (not via ``TaxonomyService.validate``)
        because CHT is a *reserved* abbreviation — ``validate`` intentionally
        rejects reserved tags for the project-facing path.
        """
        row = await self._taxonomy.get_by_abbreviation(session, tenant_key, CHT_TAXONOMY_ABBR)
        if row is None:
            raise ValidationError(
                f"The '{CHT_TAXONOMY_ABBR}' chat-thread taxonomy type is missing for this "
                "tenant. Run database migrations (ce_0054 backfill) before creating threads.",
                context={"operation": "comm_thread.create", "abbreviation": CHT_TAXONOMY_ABBR},
            )

    async def mint_serial(self, session: AsyncSession, tenant_key: str) -> int:
        """Allocate the next CHT serial for a tenant (``max(serial) + 1``).

        Independent of the project/task shared counter — chat threads carry their
        own ``CHT-####`` sequence per tenant. A concurrent create racing on the
        same ``max+1`` is caught by the ``uq_comm_thread_serial`` unique; the
        higher-level tool path (BE-6054b) may retry.
        """
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
        """Create a comm thread, minting its CHT serial. Tenant-isolated.

        ``sequence_run_id`` (BE-9291) marks this thread as THE coordination hub of a
        chain run, and is checked twice before it is written. It must name a real run
        IN THIS TENANT -- the FK alone would turn a bad id into a 500, and a run id
        from another tenant would otherwise be accepted by the constraint while
        silently creating a cross-tenant link. And that run must not already have a
        live hub: a second link makes resolution ambiguous rather than wrong-and-loud,
        so the refusal names the hub that exists.
        """
        if not tenant_key:
            raise ValidationError("tenant_key is required", context={"operation": "comm_thread.create"})

        await self._ensure_cht_type(session, tenant_key)
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
        """Resolve THE project's bound thread, creating the marker thread if none.

        The single source of truth for "the project's bound thread", shared by the
        D9 deprecation shims and the D1(a) 360-pane — the SAME precedence the
        ce_0072 fold migration replicates. Tenant-isolated.

        Precedence among LIVE (``deleted_at IS NULL``) project-bound threads:
          1. exactly one -> that thread (any subject);
          2. none        -> create one with the ``marker`` subject;
          3. several      -> the marker-subject one if present, else the OLDEST.

        The CASE order-by (not a bare ``subject == marker``) keeps a NULL-subject
        thread from sorting ahead of a marker thread. An existing ORGANIC bound
        thread (a chain hub) is reused, never duplicated — this is what makes the
        /jobs + ThreadList resolution deterministic post-(d).
        """
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
        # None exists -> create the marker thread. product_id mirrors the project
        # (a filter dim), matching what the ce_0072 fold sets for parity.
        product_id = (
            await session.execute(select(Project.product_id).where(Project.id == project_id))
        ).scalar_one_or_none()
        return await self.create_thread(
            session, tenant_key, subject=marker, project_id=project_id, product_id=product_id
        )

    async def get_by_id(self, session: AsyncSession, tenant_key: str, thread_id: str) -> CommThread | None:
        """Fetch a LIVE thread by id within a tenant (soft-deleted rows excluded)."""
        result = await session.execute(
            select(CommThread).where(
                CommThread.tenant_key == tenant_key,
                CommThread.id == thread_id,
                CommThread.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def soft_delete(self, session: AsyncSession, tenant_key: str, thread_id: str) -> bool:
        """Soft-delete a thread (stamp ``deleted_at``). Tenant-isolated.

        Returns True if a live thread was deleted, False if it did not exist (or
        was already deleted). Message history + participants are left intact —
        every read filters ``deleted_at IS NULL``, so they simply stop surfacing.
        """
        thread = await self.get_by_id(session, tenant_key, thread_id)
        if thread is None:
            return False
        thread.deleted_at = func.now()
        await session.flush()
        return True

    async def get_deleted_by_id(self, session: AsyncSession, tenant_key: str, thread_id: str) -> CommThread | None:
        """Fetch a SOFT-DELETED thread by id within a tenant (for restore).

        Mirror of ``get_by_id`` but for the trash: returns only rows with
        ``deleted_at IS NOT NULL`` so a live thread can never be "restored".
        """
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
        """List soft-deleted threads for a tenant (most-recently-deleted first).

        Powers the Hub "recover deleted threads" dialog. The CHT serial counter
        keeps counting these rows (see ``mint_serial``), so a restore keeps the
        thread's original ``CHT-####`` handle.
        """
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
        """Permanently delete a SOFT-DELETED thread (TSK-6132 reaper). Tenant-isolated.

        Restricted to trashed rows (``deleted_at IS NOT NULL``) so a live thread
        can never be reaped. ``comm_participants`` and ``messages`` (and the
        message junction rows) all carry ``ON DELETE CASCADE`` to ``comm_threads``,
        so the row's full subtree is removed at the DB level by this one delete —
        FK-safe and cascade-complete. Returns True if a trashed thread was deleted,
        False if none matched (idempotent — a row already reaped is a no-op).
        """
        thread = await self.get_deleted_by_id(session, tenant_key, thread_id)
        if thread is None:
            return False
        await session.delete(thread)
        await session.flush()
        return True

    async def restore(self, session: AsyncSession, tenant_key: str, thread_id: str) -> CommThread | None:
        """Restore a soft-deleted thread (clear ``deleted_at``). Tenant-isolated.

        Returns the restored thread, or None if no soft-deleted thread matched.
        The thread keeps its original CHT serial (it was never freed — the serial
        counter counts deleted rows), so no re-mint is needed.
        """
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
    ) -> list[CommThread]:
        """List threads for a tenant with optional filters (newest first).

        BE-6131b: ``limit`` + ``before_id`` keyset pagination mirrors the BE-6071
        bound on the ``/messages`` endpoint. When ``limit`` is supplied the result
        set is capped server-side. ``before_id`` is a keyset cursor: only threads
        whose ``created_at`` is strictly older than the named thread are returned
        (for the next page).

        The MCP tool surface (BE-6054b) extends this with the full filter set;
        link a provides the tenant-isolated foundation + the common dims.
        """
        query = select(CommThread).where(
            CommThread.tenant_key == tenant_key,
            CommThread.deleted_at.is_(None),
        )
        if status is not None:
            query = query.where(CommThread.status == status)
        if next_action_owner is not None:
            query = query.where(CommThread.next_action_owner == next_action_owner)
        if product_id is not None:
            query = query.where(CommThread.product_id == product_id)
        if project_id is not None:
            query = query.where(CommThread.project_id == project_id)

        if before_id is not None:
            cursor_result = await session.execute(
                select(CommThread.created_at).where(
                    CommThread.tenant_key == tenant_key,
                    CommThread.id == before_id,
                )
            )
            cursor_ts = cursor_result.scalar_one_or_none()
            if cursor_ts is not None:
                query = query.where(CommThread.created_at < cursor_ts)

        query = query.order_by(CommThread.created_at.desc())
        if limit is not None and limit > 0:
            query = query.limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_recipient_state_for_messages(
        self, session: AsyncSession, tenant_key: str, *, message_ids: list[str]
    ) -> dict[str, dict[str, list[str]]]:
        """Per-message recipient acted-on state for the Hub in-thread filter (FE-9012c, D3/D4).

        Batched — three grouped, tenant-scoped ``array_agg`` queries over the given
        message ids (one per junction), NOT a per-message fetch. Returns
        ``{message_id: {recipients, acked_by, completed_by}}``; the service derives
        ``pending_for`` = recipients minus those who acked-or-completed. A message with no rows
        in a junction defaults to an empty list for that key. Tenant-scoped on every
        junction, matching the predicate the D4 writers use.
        """
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

    # ------------------------------------------------------------------
    # BE-6054b reads/writes the MCP tool surface builds on.
    # ------------------------------------------------------------------

    async def set_next_action_owner(
        self, session: AsyncSession, tenant_key: str, thread_id: str, owner: str | None
    ) -> CommThread | None:
        """Pass the baton: set next_action_owner. Returns the updated thread, or None."""
        thread = await self.get_by_id(session, tenant_key, thread_id)
        if thread is None:
            return None
        thread.next_action_owner = owner
        await session.flush()
        return thread

    async def set_status(
        self, session: AsyncSession, tenant_key: str, thread_id: str, status: str
    ) -> CommThread | None:
        """Set the thread status (open|active|resolved|closed + freeform). Returns the thread."""
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
        """All messages on a thread, oldest-first. READ-ONLY — no ack, no status
        mutation (mirrors the retired bus's MessageService.list_messages read
        shape, not its ack-on-read receive_messages).

        BE-9012a (D6) — cursor filters (AND-combined with the BE-6226 markers, all
        optional so existing callers stay byte-identical): ``unread_after`` (only
        messages strictly after the participant's ``last_read_at``; NULL => whole
        timeline), ``directed_to`` (only messages with a ``message_recipients`` row for
        that participant — a DM to them OR a received broadcast), ``action_required_only``.

        BE-6226 — incremental fetch (backward-compatible; NO filter => byte-identical
        to the pre-BE-6226 full-timeline catch-up): ``after_message_id`` (only messages
        created after that message's ``created_at``; an id not on this thread => empty,
        not an error), ``since`` (only messages with ``created_at`` strictly after it),
        ``tail`` (last N, applied after any marker, still oldest-first). Marker filters
        are strictly ``> created_at``, consistent with the timeline's ordering."""
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
                # Cursor not on this thread -> nothing to catch up on (no error).
                return []
            conditions.append(Message.created_at > marker)

        if since is not None:
            conditions.append(Message.created_at > since)

        if unread_after is not None:  # BE-9012a (D6): cursor + directed/action filters.
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
            # Last N, oldest-first: take the N newest (DESC + limit), then reverse.
            result = await session.execute(
                select(Message).where(*conditions).order_by(Message.created_at.desc()).limit(tail)
            )
            return list(reversed(result.scalars().all()))

        result = await session.execute(select(Message).where(*conditions).order_by(Message.created_at.asc()))
        return list(result.scalars().all())

    async def ack_messages_for_participant(
        self, session: AsyncSession, tenant_key: str, *, agent_id: str, message_ids: list[str]
    ) -> None:
        """Record per-recipient acknowledgment of thread posts (BE-9012a, D4).

        Bulk-inserts ``message_acknowledgments``, ON CONFLICT DO NOTHING (uq_msg_ack)
        so a repeated mark_read is idempotent. Reuses the junction; caller commits."""
        if not message_ids:
            return
        rows = [
            {"id": generate_uuid(), "message_id": mid, "agent_id": agent_id, "tenant_key": tenant_key}
            for mid in message_ids
        ]
        stmt = pg_insert(MessageAcknowledgment.__table__).values(rows).on_conflict_do_nothing(constraint="uq_msg_ack")
        await session.execute(stmt)
        await session.flush()

    async def search_threads(
        self, session: AsyncSession, tenant_key: str, query: str, *, limit: int = 50
    ) -> list[CommThread]:
        """Find threads by subject, CHT serial, message content, or participant.

        Tenant-scoped. Case-insensitive ILIKE over subject; a CHT-#### / numeric
        query also matches the serial; EXISTS subqueries cover message content and
        participant id/display_name. Newest-first.
        """
        like = f"%{query.strip()}%"
        conditions = [CommThread.subject.ilike(like)]

        # CHT-#### or a bare number -> match the serial exactly. BE-6208b: a
        # full UUID query (e.g. a 36-char thread id) yields a huge digit string
        # whose int() overflows the serial column's 32-bit cast -> Postgres 500.
        # Only take the serial-equality branch for a plausible serial length
        # (<= 9 digits fits int4); a UUID-shaped query falls through to the
        # subject/content/participant matching and returns a normal result.
        digits = "".join(ch for ch in query if ch.isdigit())
        if digits and len(digits) <= 9:
            conditions.append(CommThread.serial == int(digits))

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
            .order_by(CommThread.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def has_active_loop_directive(self, session: AsyncSession, tenant_key: str, agent_id: str) -> bool:
        """Does this agent have a LIVE loop directive? (BE-6054c)

        True iff a ``loop_directive`` message is addressed to ``agent_id`` on a
        thread whose status is NOT terminal (resolved/closed). Once the thread
        closes the directive goes silent — this is what makes the loop provably
        terminate. Tenant-scoped; mirrors the message+recipient+thread EXISTS
        join used by ``search_threads``.
        """
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
        """SIDE-EFFECT-FREE thread message persist (BE-6054b carve-out).

        Reuses ONLY the Message + message_recipients fan-out — NOT the
        orchestration send_message side-effects (no counter bumps, no auto-block
        of completed recipients, no reactivation). Accepts a NULL project_id for
        standalone chat threads. Caller commits.

        FE-6140: ``loop_interval_minutes`` is the operator-chosen auto-check-in
        cadence carried on a ``loop_directive`` message (NULL on every other
        message); surfaced on the poll responses so a running agent reads it.

        BE-9289a: ``from_kind`` ('agent'|'user') is the SERVER's answer to what the
        author is, decided by the caller's attribution branch. It is stored alongside
        ``from_agent_id``, never derived from it — the slug is self-declared and its
        shape says nothing about the author's kind.
        """
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
        """The most recent ``loop_directive`` message on a thread, or None (FE-6140).

        Drives the get_thread_history poll inject. "Latest wins" gives the rolling
        cadence — a fresh loop_directive post supersedes the previous interval.
        Tenant-scoped. Whether the directive is ACTIVE (thread non-terminal) is the
        caller's call — this returns the message regardless of thread status so the
        service can pair it with the thread it already loaded.
        """
        result = await session.execute(
            select(Message)
            .where(
                Message.tenant_key == tenant_key,
                Message.thread_id == thread_id,
                Message.message_type == LOOP_DIRECTIVE_MESSAGE_TYPE,
            )
            # id.desc() is a stable tiebreaker for posts that share a created_at
            # (e.g. two posts in one transaction) so "latest wins" is deterministic.
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_loop_directives_for_agent(
        self, session: AsyncSession, tenant_key: str, agent_id: str
    ) -> list[dict]:
        """Active loop directives for every thread the agent PARTICIPATES in (FE-6140).

        Drives the get_my_turn poll inject. Scope is ALL participant agents (not
        just the baton-holder / addressed recipient): a row is returned for each
        NON-terminal, non-deleted thread where ``agent_id`` is a participant AND the
        thread carries at least one ``loop_directive`` message. The latest such
        message's interval is used (rolling cadence). Reaching every participant —
        including late-joiners — is the design intent: a coordination thread armed
        once should loop ALL its agents.

        Returns ``[{thread_id, serial, interval_minutes}]``; the service formats the
        CHT-#### handle. Tenant-scoped on every joined table.
        """
        # Latest loop_directive message per thread (DISTINCT ON the thread).
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
            # DISTINCT ON the thread keeps the latest directive; id.desc() is a
            # stable tiebreaker when two posts share a created_at (one transaction).
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
