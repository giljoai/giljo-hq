# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CommThreadService — the owning service for the Agent Message Hub (BE-6054b).

Sits on the BE-6054a CommThreadRepository data foundation and provides the
behaviour the 8 MCP tools delegate to: create/join threads, post to a thread
(SIDE-EFFECT-FREE — never routes through orchestration send_message), the baton
queries (get_my_turn / pass_baton), list/search, and read-only history.

Session handling mirrors TaxonomyService: a transactional test session
(``session=``) is used verbatim, otherwise a request-scoped
``get_session_async`` (which commits on clean exit) is opened. Every operation
runs inside ``tenant_session_context`` and filters ``tenant_key``.

Edition Scope: CE.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.harness_resolver import GENERIC_HARNESS
from giljo_mcp.models.comm import (
    BOUND_THREAD_MARKER_SUBJECT,
    LOOP_DIRECTIVE_MESSAGE_TYPE,
    TERMINAL_THREAD_STATUSES,
    VALID_PARTICIPANT_TYPES,
    CommParticipant,
    CommThread,
)
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.repositories.user_repository import UserRepository
from giljo_mcp.schemas.comm_serializers import message_dict, thread_dict
from giljo_mcp.services._comm_thread_baton_mixin import CommThreadBatonMixin
from giljo_mcp.services._comm_thread_chain_hub_mixin import CommThreadChainHubMixin
from giljo_mcp.services._comm_thread_create_binding_mixin import CommThreadCreateBindingMixin
from giljo_mcp.services._comm_thread_edit_mixin import CommThreadEditMixin
from giljo_mcp.services._comm_thread_liveness_mixin import (
    CommThreadLivenessMixin,
    _build_skipped_recipients_notice,
)
from giljo_mcp.services._comm_thread_operator_read_mixin import CommThreadOperatorReadMixin
from giljo_mcp.services._comm_thread_softdelete_mixin import CommThreadSoftDeleteMixin
from giljo_mcp.services._comm_thread_wake_mixin import CommThreadWakeMixin
from giljo_mcp.services.comm_author_identity import resolve_and_register_author, validate_post_author_input
from giljo_mcp.services.comm_baton_targets import (
    broadcast_reply_should_clear_baton,
    enrol_addressee,
    post_target_rejection,
    resolve_operator_alias,
)
from giljo_mcp.services.comm_post_validation import resolve_loop_interval, validate_post_vocabularies
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)

# Length cap for an agent-supplied author identity (FE-6122). Mirrors MCP_ID_MAX
# at the tool boundary; enforced here too so the owning service validates the
# input itself ("no unvalidated agent input to DB"), not only the MCP wrapper.
_FROM_AGENT_MAX = 64

# BE-6226: bounds for the get_thread_history incremental-fetch ``tail`` (last N).
# Validated at the owning service so the repo never receives unbounded agent input.
_TAIL_MIN = 1
_TAIL_MAX = 500

# Returned on a mark_read read whose filters/truncation forbid a cursor advance.
# The acks ARE written (exactly the posts returned — that is what clears the completion
# gate); the per-participant watermark is not, so unread_only keeps returning them. Say
# so, rather than let a repeated non-zero count read as progress that is not happening.
_NARROWED_MARK_READ_NOTE = (
    "Acknowledged exactly the posts returned, but the per-participant read cursor did "
    "NOT advance: this read was narrowed (directed_only / action_required_only) or "
    "truncated (tail / after_message_id / since), so the returned set is not the "
    "contiguous run up to the newest post and advancing would skip what it excluded. "
    "unread_only will keep returning these posts until you re-read the thread with "
    "as_participant + mark_read=true and NO filters."
)


class CommThreadService(
    CommThreadChainHubMixin,
    CommThreadOperatorReadMixin,
    CommThreadCreateBindingMixin,
    CommThreadSoftDeleteMixin,
    CommThreadEditMixin,
    CommThreadBatonMixin,
    CommThreadWakeMixin,
    CommThreadLivenessMixin,
):
    """Service surface for comm_threads / comm_participants + thread messaging."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        session: AsyncSession | None = None,
    ) -> None:
        self._db_manager = db_manager
        self._tenant_manager = tenant_manager
        self._session = session
        self._repo = CommThreadRepository()
        self._user_repo = UserRepository()
        self._agent_ops = AgentOperationsRepository()

    # ------------------------------------------------------------------
    # Session + tenant plumbing
    # ------------------------------------------------------------------

    def _resolve_tenant(self, tenant_key: str | None) -> str:
        tk = tenant_key or self._tenant_manager.get_current_tenant()
        if not tk:
            raise ValidationError("tenant_key is required", context={"operation": "comm_thread"})
        return tk

    @asynccontextmanager
    async def _scoped_session(self, tenant_key: str):
        if self._session is not None:
            with tenant_session_context(self._session, tenant_key):
                yield self._session
        else:
            async with self._db_manager.get_session_async(tenant_key=tenant_key) as session:
                with tenant_session_context(session, tenant_key):
                    yield session

    async def _require_thread(self, session: AsyncSession, tenant_key: str, thread_id: str) -> CommThread:
        thread = await self._repo.get_by_id(session, tenant_key, thread_id)
        if thread is None:
            raise ResourceNotFoundError(
                message="Thread not found or access denied",
                context={"operation": "comm_thread", "thread_id": thread_id},
            )
        return thread

    # ------------------------------------------------------------------
    # Tool operations
    # ------------------------------------------------------------------

    async def create_thread(
        self,
        *,
        subject: str | None = None,
        severity: str | None = None,
        product_id: str | None = None,
        project_id: str | None = None,
        creator_id: str | None = None,
        creator_type: str = "agent",
        creator_display_name: str | None = None,
        sequence_run_id: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a thread (mints the CHT-#### serial). Optionally registers the
        creator as the first participant + hands them the baton.

        ``sequence_run_id`` (BE-9291) marks the thread as THE coordination hub of a
        chain run, which is how ``resolve_chain_hub_thread`` finds it later. The repo
        verifies the run belongs to this tenant before storing it. It is also exempt
        from FE-9530's mandatory product resolution ever REFUSING the create for
        lacking a product -- the chain conductor is deliberately PROJECT-LESS and its
        Step-0 hub-thread create must never 422 -- but BE-9537 closed the gap where
        that exemption left the thread permanently untagged: an omitted
        ``product_id`` is now DERIVED from the run's head project via
        ``_resolve_create_product_id`` (never raising for this path; see that
        method), the same as any other omitted ``product_id``.

        FE-9530: "a thread MUST carry a product, unless
        application has no product." An omitted ``product_id`` is resolved via
        ``_resolve_create_product_id`` rather than left NULL by default.
        """
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            if not product_id:
                product_id = await self._resolve_create_product_id(
                    session, tk, product_id=product_id, project_id=project_id, sequence_run_id=sequence_run_id
                )
            thread = await self._repo.create_thread(
                session,
                tk,
                subject=subject,
                severity=severity,
                product_id=product_id,
                project_id=project_id,
                next_action_owner=creator_id,
                sequence_run_id=sequence_run_id,
            )
            if creator_id:
                ctype = creator_type if creator_type in VALID_PARTICIPANT_TYPES else "agent"
                await self._repo.add_participant(
                    session,
                    tk,
                    thread.id,
                    participant_id=creator_id,
                    participant_type=ctype,
                    display_name=creator_display_name,
                    role="creator",
                )
            return thread_dict(thread)

    async def resolve_or_create_bound_thread(self, *, project_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        """Resolve (or create) THE project's bound thread — the single source of
        truth shared by the D9 deprecation shims and the D1(a) 360-pane, using the
        same precedence the ce_0072 fold does (see the repo method). Tenant-scoped."""
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            thread = await self._repo.resolve_or_create_bound_thread(
                session, tk, project_id, marker=BOUND_THREAD_MARKER_SUBJECT
            )
            return thread_dict(thread)

    async def join_thread(
        self,
        *,
        thread_id: str,
        participant_id: str,
        participant_type: str = "agent",
        display_name: str | None = None,
        role: str | None = None,
        detected_harness: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Declare/claim an identity on a thread (collision-safe).

        BE-9289a: ``detected_harness`` is resolved by the MCP boundary from the
        ``initialize`` clientInfo and threaded down — it is NEVER a value the caller
        declares about itself. A caller with no detection (the REST path, the in-memory
        transport, an unknown client) resolves to ``generic``, the fail-safe floor.
        """
        tk = self._resolve_tenant(tenant_key)
        if not participant_id:
            raise ValidationError("participant_id is required", context={"operation": "comm_thread.join"})
        async with self._scoped_session(tk) as session:
            await self._require_thread(session, tk, thread_id)
            participant = await self._repo.add_participant(
                session,
                tk,
                thread_id,
                participant_id=participant_id,
                participant_type=participant_type,
                display_name=display_name,
                role=role,
                harness=detected_harness or GENERIC_HARNESS,
                touch_last_seen=True,  # joining is activity
                authoritative=True,  # join_thread is the participant DECLARING itself
            )
            return {
                "participant_id": participant.participant_id,
                "thread_id": thread_id,
                "participant_type": participant.participant_type,
            }

    async def _rename_before_post(self, thread_id: str, rename_to: str | None, tenant_key: str) -> None:
        """BE-9502a: applied before the post via ``update_thread`` (the dashboard's
        own writer), so a refused rename (project-bound thread) posts nothing."""
        if rename_to is not None:
            await self.update_thread(thread_id=thread_id, subject=rename_to, tenant_key=tenant_key)

    async def post_to_thread(
        self,
        *,
        thread_id: str,
        content: str,
        from_agent: str | None = None,
        to_participant: str | None = None,
        message_type: str = "direct",
        priority: str = "normal",
        requires_action: bool = False,
        set_status: str | None = None,
        loop_directive: bool = False,
        loop_interval_minutes: int | None = None,
        pass_baton_to: str | None = None,
        clear_baton_on_broadcast_reply: bool = False,
        user_id: str | None = None,
        as_user: bool = False,
        detected_harness: str | None = None,
        self_reported_status: str | None = None,
        rename_to: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Post a message to a thread (broadcast to all participants, or direct to
        one). SIDE-EFFECT-FREE: persists Message + message_recipients only — never
        the orchestration send_message side-effects. Accepts a NULL project_id.

        BE-9197: a non-'none' ``pass_baton_to`` hands the baton ATOMICALLY with
        the post (one transaction — a failed post rolls the hand-off back);
        'none'/omitted leave it untouched (posting is never clearing). The
        auto-pass default resolves at the MCP boundary, NOT here, so the REST
        and internal callers keep prior behavior unless they pass the param.
        BE-9560's ``clear_baton_on_broadcast_reply`` is REST-only, never set by
        the MCP wrapper -- see ``comm_baton_targets.broadcast_reply_should_clear_baton``.

        BE-6054c: ``loop_directive=True`` marks the message so addressed agents get
        the "loop/sleep until this thread is resolved/closed" directive in their
        next mission. The loop terminates when the thread reaches a terminal status.

        FE-6140: ``loop_interval_minutes`` is the operator-chosen auto-check-in
        cadence. It is persisted on the loop_directive message and surfaced on the
        get_my_turn / get_thread_history poll responses (the harness-neutral inject)
        so a running agent re-reads it and self-schedules its wake. Ignored unless
        ``loop_directive`` is True (a non-directive message never carries a cadence).

        BE-9475: ``self_reported_status`` is the poster's own claim about what it is
        doing, stored on its participant row and served only where ``agent_executions``
        has nothing to say (validated by comm_post_validation.validate_post_vocabularies).
        BE-9502a: ``rename_to`` -- see ``_rename_before_post``."""
        tk = self._resolve_tenant(tenant_key)
        if not content or not content.strip():
            raise ValidationError("content is required", context={"operation": "comm_thread.post"})
        validate_post_vocabularies(set_status, self_reported_status)
        await self._rename_before_post(thread_id, rename_to, tk)
        interval_to_persist = resolve_loop_interval(loop_directive, loop_interval_minutes)

        # (A) Author attribution -- see comm_author_identity.validate_post_author_input
        # for the full rationale (BE-9560 extracted it there to make size-budget room).
        from_agent = validate_post_author_input(from_agent, as_user, _FROM_AGENT_MAX)

        async with self._scoped_session(tk) as session:
            thread = await self._require_thread(session, tk, thread_id)

            # BE-9365b: expand "user" BEFORE the guard, so everything downstream sees an
            # ordinary id; an unresolvable alias falls through and the guard refuses it
            # rather than it being silently dropped. Full rationale on the resolver.
            to_participant = (
                await resolve_operator_alias(self._user_repo, session, tk, to_participant) or to_participant
            )
            pass_baton_to = await resolve_operator_alias(self._user_repo, session, tk, pass_baton_to) or pass_baton_to

            # BE-9292a: refuse an addressee or a hand-off that could never be
            # delivered, BEFORE any write, so a refused post persists neither message
            # nor baton. BE-9292a-F1: the ADDRESSEE is screened too — the auto-pass
            # makes it the baton target, and delivering to it enrols it.
            rejection = await post_target_rejection(
                self._repo,
                self._user_repo,
                session,
                tk,
                thread_id,
                to_participant=to_participant,
                pass_baton_to=pass_baton_to,
                author_id=from_agent or user_id or "orchestrator",
                current_owner=thread.next_action_owner,
            )
            if rejection is not None:
                return rejection

            # BE-9197/BE-9560: hand-off or clear written BEFORE the persist (rollback-safe).
            baton_passed = baton_cleared = False
            if pass_baton_to and pass_baton_to != "none":
                await self._repo.set_next_action_owner(session, tk, thread_id, pass_baton_to)
                baton_passed = True
            elif broadcast_reply_should_clear_baton(
                clear_baton_on_broadcast_reply, to_participant, thread.next_action_owner, user_id
            ):
                await self._repo.set_next_action_owner(session, tk, thread_id, None)
                baton_cleared = True

            # BE-9289a: who wrote this, and register them — see comm_author_identity for
            # why the KIND is recorded here rather than inferred by any later reader.
            author = await resolve_and_register_author(
                self._repo,
                self._user_repo,
                session,
                tk,
                thread_id,
                from_agent=from_agent,
                user_id=user_id,
                detected_harness=detected_harness,
                as_user=as_user,
                self_reported_status=self_reported_status,
            )
            from_agent_id, from_kind = author.agent_id, author.kind
            from_display_name, attribution_warning = author.display_name, author.warning

            recipient_ids, skipped_recipients, candidate_count = await self._resolve_recipients(
                session,
                tk,
                thread,
                to_participant=to_participant,
                from_agent_id=from_agent_id,
                requires_action=requires_action,
            )

            # A loop-directive post is marked with the reserved message_type so the
            # mission composer can detect it; otherwise broadcast vs direct as usual.
            if loop_directive:
                resolved_message_type = LOOP_DIRECTIVE_MESSAGE_TYPE
            elif to_participant:
                resolved_message_type = message_type
            else:
                resolved_message_type = "broadcast"

            message = await self._repo.persist_thread_message(
                session,
                tenant_key=tk,
                thread_id=thread_id,
                project_id=thread.project_id,  # may be NULL (standalone thread)
                content=content,
                from_agent_id=from_agent_id,
                from_display_name=from_display_name,
                from_kind=from_kind,
                message_type=resolved_message_type,
                priority=priority,
                requires_action=requires_action,
                recipient_ids=recipient_ids,
                loop_interval_minutes=interval_to_persist,
            )
            if set_status is not None:
                await self._repo.set_status(session, tk, thread_id, set_status)
            # BE-9296a: read inside the session, written after it commits (below).
            notice = await self.collect_handover_notice(
                session, tk, thread, pass_baton_to if baton_passed else None, from_display_name
            )
            result = {
                "message_id": message.id,
                "thread_id": thread_id,
                "recipients": recipient_ids,
                "to_participant": to_participant,  # FE-9546: RESOLVED addressee, for the WS filter
                "from_agent_id": from_agent_id,
                "from_display_name": from_display_name,
                # BE-9289a: returned so the WS broadcast can carry the SAME server-
                # resolved kind the persisted row has. A live message that arrived
                # without it would fall back to a default and could render the
                # operator's own post as an agent.
                "from_kind": from_kind,
                "attribution_warning": attribution_warning,
                "loop_directive_armed": loop_directive,
                "loop_interval_minutes": interval_to_persist,
                # BE-9197/BE-9560 (additive): did THIS post move or clear the baton.
                "baton_passed": baton_passed,
                "baton_cleared": baton_cleared,
                "next_action_owner": thread.next_action_owner,
                # Stay-on-the-line (1CZA1D): see _post_advice_entry / POST_ADVICE.
                **self._post_advice_entry(set_status),
            }
            # BE-9491: additive, mirrors BE-9247's forward_notice -- post already succeeded.
            skipped_notice = _build_skipped_recipients_notice(
                skipped_recipients, recipient_ids, candidate_count, is_broadcast=not to_participant
            )
            if skipped_notice:
                result["skipped_recipients"] = skipped_notice
                result["skipped_recipient_details"] = skipped_recipients

        # BE-9296a: COMMITTED here, and not one line earlier — see the mixin.
        self._signal_post_wake(tk, to_participant, requires_action, pass_baton_to, baton_passed, recipient_ids)
        await self.emit_handover_notice(notice)
        return result

    async def list_threads(
        self,
        *,
        status: str | None = None,
        owner: str | None = None,
        product_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
        before_id: str | None = None,
        viewer_id: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """List threads with optional filters.

        BE-6131b: ``limit`` + ``before_id`` keyset pagination added to bound the
        Hub thread list (mirrors the BE-6071 bound on the ``/messages`` endpoint).

        BE-9289b: ``viewer_id`` opts into the card facts the Quiet Cards list needs —
        ``project_name``, ``participants``, ``last_message`` and ``unread`` — in ONE
        extra round trip for the whole page, replacing the per-thread follow-up call the
        UI used to make. It is OPT-IN because it is a presentation concern: the MCP
        agent path passes no viewer and its payload stays byte-identical. ``unread`` is
        per-viewer, so it cannot be computed without knowing who is asking.
        """
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            threads = await self._repo.list_threads(
                session,
                tk,
                status=status,
                next_action_owner=owner,
                product_id=product_id,
                project_id=project_id,
                limit=limit,
                before_id=before_id,
            )
            payload = [thread_dict(t) for t in threads]
            if viewer_id:
                facts = await self._repo.list_threads_enriched(session, tk, viewer_id=viewer_id, threads=threads)
                for entry in payload:
                    entry.update(facts.get(entry["thread_id"], {}))
            return {"count": len(threads), "threads": payload}

    async def _apply_mark_read(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        participant: CommParticipant,
        as_participant: str,
        messages: list,
        narrowed: bool,
    ) -> tuple[int, bool]:
        """Ack the returned posts and, on a clean forward drain, advance the cursor.

        Returns ``(marked_read, cursor_advanced)``. ``marked_read`` is the number of
        acks NEWLY written — not ``len(messages)``. Those differ on every repeat read,
        and reporting the latter was the defect: a second identical filtered call
        re-reported the same non-zero count while changing nothing, so the caller could
        not tell a real acknowledgement from a no-op.

        The cursor is advanced ONLY on a clean forward drain. Narrowing
        (directed/action) or truncation (tail/marker) means the returned set is not the
        contiguous run up to newest, so advancing would skip unread posts it excluded.
        That refusal is deliberate (BE-9012a) and stays; the acks are exact and
        per-message either way, which is what the completion gate reads. What the
        caller now gets is a signal that it happened — ``cursor_advanced`` — instead of
        a silent stall that makes ``unread_only`` repeat forever.
        """
        # D4: per-recipient acted-on state for every post seen (idempotent).
        marked_read = await self._repo.ack_messages_for_participant(
            session, tenant_key, agent_id=as_participant, message_ids=[m.id for m in messages]
        )
        if narrowed:
            return marked_read, False
        newest = messages[-1]  # oldest-first => last is the newest returned
        if newest.created_at is not None and (
            participant.last_read_at is None or newest.created_at > participant.last_read_at
        ):
            participant.last_read_message_id = newest.id
            participant.last_read_at = newest.created_at
            await session.flush()
            return marked_read, True
        return marked_read, False

    async def get_thread_history(
        self,
        *,
        thread_id: str,
        after_message_id: str | None = None,
        since: str | None = None,
        tail: int | None = None,
        as_participant: str | None = None,
        unread_only: bool = False,
        mark_read: bool = False,
        directed_only: bool = False,
        action_required_only: bool = False,
        include_recipient_state: bool = False,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Read a thread's message timeline (READ-ONLY unless ``mark_read=True``).

        FE-6140: also surfaces ``loop_directive`` — ``{active, interval_minutes}``
        for the thread. ``active`` is True iff the latest loop_directive message
        exists AND the thread is non-terminal (a resolved/closed thread silences the
        directive, the same gate that makes the loop provably terminate). This is the
        harness-neutral inject a running agent re-reads on each poll.

        BE-6226 — incremental fetch (backward-compatible). With NONE of the optional
        params the response is byte-identical to the pre-BE-6226 full-timeline read.
        A chain conductor passes a marker to pull only NEW messages each poll instead
        of re-fetching the whole thread:
          - ``after_message_id`` — only messages after that message id (the poll cursor).
          - ``since`` — ISO-8601 timestamp; only messages created strictly after it.
          - ``tail`` — only the last N messages (1..500), applied after any marker.
        ``after_message_id`` and ``since`` are mutually exclusive (both name a start
        marker); ``count`` reflects the rows actually returned.

        BE-9012a (D6/D4) — server-persistent per-(thread, participant) cursor, so a
        unified-Hub read is O(N) drain-equivalent, not an O(N^2) re-read (INF-6201 §1).
        ``as_participant`` (the reader's participant_id) is REQUIRED for the four below:
          - ``unread_only`` — only posts after the reader's stored ``last_read_at``.
            No cursor / never joined => the whole timeline (honest "nothing read yet").
          - ``mark_read`` — ack the returned posts in ``message_acknowledgments``
            (idempotent) and, on a clean forward drain (no narrowing/truncation),
            advance the cursor to the newest returned post. Refuses with a structured
            ``NOT_A_PARTICIPANT`` rejection if the reader never joined. ONLY write path.
            ``marked_read`` counts acks NEWLY written, so a repeat drain reports 0;
            ``cursor_advanced`` says whether the watermark moved, and a narrowed read
            also carries ``mark_read_note`` naming the unfiltered call that advances it.
          - ``directed_only`` / ``action_required_only`` — posts delivered to the reader
            (DM or received broadcast) / ``requires_action=True`` posts.
        Every query is ``tenant_key``-scoped; the cursor is per-(thread, participant) —
        ADR-009 Teams-ready (never per-user account-level state).

        FE-9012c (D3/D4) — ``include_recipient_state`` (default False, so the MCP agent
        poll path stays byte-identical + does zero extra queries) surfaces per-post
        MESSAGE-relative junction state for the Hub's in-thread waiting/read/sent filter:
        each message dict gains ``recipients`` / ``acked_by`` / ``completed_by`` /
        ``pending_for`` (recipients minus those who acked-or-completed). One batched
        tenant-scoped fetch across the returned message ids — not per-message."""
        if after_message_id and since:
            raise ValidationError(
                "Pass at most one of 'after_message_id' or 'since' (both name a start marker).",
                context={"operation": "comm_thread.history", "thread_id": thread_id},
            )

        # BE-9012a: cursor params need the reader's identity (never inferred) -> clean 422.
        if (unread_only or mark_read or directed_only or action_required_only) and not as_participant:
            raise ValidationError(
                "as_participant is required when using unread_only / mark_read / "
                "directed_only / action_required_only (the per-participant cursor "
                "must know who is reading).",
                context={"operation": "comm_thread.history", "thread_id": thread_id},
            )

        since_dt: datetime | None = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    "'since' must be an ISO-8601 timestamp (e.g. a message's created_at).",
                    context={"operation": "comm_thread.history", "since": since},
                ) from exc

        if tail is not None:
            if not isinstance(tail, int) or isinstance(tail, bool):
                raise ValidationError(
                    "'tail' must be an integer number of messages.",
                    context={"operation": "comm_thread.history"},
                )
            if not (_TAIL_MIN <= tail <= _TAIL_MAX):
                raise ValidationError(
                    f"'tail' must be between {_TAIL_MIN} and {_TAIL_MAX}.",
                    context={"operation": "comm_thread.history", "tail": tail},
                )

        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            thread = await self._require_thread(session, tk, thread_id)

            participant = None  # BE-9012a: the reader's per-(thread, participant) cursor row.
            if as_participant:
                # BE-9289a: a read is activity — an agent that only listens is still
                # alive. An UPDATE, so a non-participant reader enrolls nobody.
                await self._repo.touch_participant_last_seen(session, tk, as_participant, thread_id=thread_id)
                participant = await self._repo.get_participant(session, tk, thread_id, as_participant)

            if mark_read and participant is None:
                # BE-9292a: enrolment follows DELIVERY, so a reader holding a post
                # addressed to it belongs here and the missing row is the defect, not
                # the reader. Threads that diverged before the write boundary started
                # registering addressees heal themselves on the next read — no
                # migration, and no CE self-hoster left with a wedged thread.
                delivered = await self._repo.get_thread_messages(
                    session, tk, thread_id, directed_to=as_participant, tail=1
                )
                if delivered:
                    participant = await enrol_addressee(
                        self._repo,
                        self._user_repo,
                        session,
                        tk,
                        thread_id,
                        as_participant,
                        touch_last_seen=True,  # this read is the activity
                    )
                else:
                    # BE-6081 carve-out: a deliberate domain rejection (not an error). A
                    # silent no-op would let the caller believe it acked when it did not —
                    # the closeout-dance failure this chain exists to kill. Still the right
                    # answer for a reader with NOTHING delivered to it: nothing to ack.
                    return {
                        "success": False,
                        "error": "NOT_A_PARTICIPANT",
                        "thread_id": thread_id,
                        "as_participant": as_participant,
                        "hint": "join_thread this thread first (re-joining is a safe no-op), then retry mark_read.",
                    }

            # unread keys on the stored timestamp (reaper-safe); no cursor => whole timeline.
            unread_after = participant.last_read_at if (unread_only and participant is not None) else None
            directed_to = as_participant if directed_only else None

            messages = await self._repo.get_thread_messages(
                session,
                tk,
                thread_id,
                after_message_id=after_message_id or None,
                since=since_dt,
                tail=tail,
                unread_after=unread_after,
                directed_to=directed_to,
                action_required_only=action_required_only,
            )

            narrowed = bool(directed_only or action_required_only or tail or after_message_id or since)
            marked_read = 0
            cursor_advanced = False
            if mark_read and participant is not None and messages:
                marked_read, cursor_advanced = await self._apply_mark_read(
                    session,
                    tk,
                    participant=participant,
                    as_participant=as_participant,
                    messages=messages,
                    narrowed=narrowed,
                )

            # FE-9012c (D3): one batched junction fetch, merged per message. Gated so
            # the default read (MCP agent poll) is byte-identical and query-identical.
            recipient_state: dict[str, dict[str, list[str]]] = {}
            if include_recipient_state and messages:
                recipient_state = await self._repo.get_recipient_state_for_messages(
                    session, tk, message_ids=[m.id for m in messages]
                )

            directive = await self._repo.get_latest_loop_directive(session, tk, thread_id)
            active = directive is not None and not self.is_terminal_status(thread.status)
            response = {
                "thread": thread_dict(thread),
                "count": len(messages),
                "messages": [
                    message_dict(m, recipient_state.get(m.id) if include_recipient_state else None) for m in messages
                ],
                "loop_directive": {
                    "active": active,
                    "interval_minutes": directive.loop_interval_minutes if (directive and active) else None,
                },
            }
            # Additive only when mark_read requested (legacy read stays byte-identical).
            if mark_read:
                response["marked_read"] = marked_read
                response["cursor_advanced"] = cursor_advanced
                if messages and narrowed:
                    response["mark_read_note"] = _NARROWED_MARK_READ_NOTE
            return response

    async def search_threads(self, *, query: str, limit: int = 50, tenant_key: str | None = None) -> dict[str, Any]:
        """Find threads by subject, CHT serial, message content, or participant."""
        tk = self._resolve_tenant(tenant_key)
        if not query or not query.strip():
            raise ValidationError("query is required", context={"operation": "comm_thread.search"})
        async with self._scoped_session(tk) as session:
            threads = await self._repo.search_threads(session, tk, query, limit=limit)
            return {"query": query, "count": len(threads), "threads": [thread_dict(t) for t in threads]}

    async def list_participants(self, *, thread_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        """Return the participant directory for a thread (BE-6054ef REST adapter).

        TSK-9457: this carries ``status`` — the SAME ``latest_execution_status``
        expression the Hub's thread-card list serves — and it must be present even when
        NULL. Absent is not null here, and that difference WAS the bug: the client reads a
        missing status with a present ``last_seen_at`` as ``idle``, labelled "Monitoring",
        so a ``silent`` agent read "Silent" on the card and "Monitoring" once you clicked
        into it. That second label was not a competing judgement — it was a default the
        client invented because this read handed it nothing, and the one that reads
        HEALTHY for an agent we had lost contact with. NULL stays NULL for the reason
        documented on ``latest_execution_status``.
        """
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            await self._require_thread(session, tk, thread_id)
            parts = await self._repo.get_participants_with_status(session, tk, thread_id)
            return {
                "thread_id": thread_id,
                "count": len(parts),
                "participants": [
                    {
                        "participant_id": p.participant_id,
                        "participant_type": p.participant_type,
                        "display_name": p.display_name,
                        "role": p.role,
                        # BE-9289a: server-stamped identity the Hub's agent pills render.
                        "harness": p.harness,
                        "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
                        "joined_at": p.joined_at.isoformat() if p.joined_at else None,
                        # TSK-9457: one source of truth with the card list — agent_executions.
                        "status": status,
                    }
                    for p, status in parts
                ],
            }

    @staticmethod
    def is_terminal_status(status: str | None) -> bool:
        """Whether a thread status ends the loop/sleep coordination (BE-6054c uses this)."""
        return status in TERMINAL_THREAD_STATUSES
