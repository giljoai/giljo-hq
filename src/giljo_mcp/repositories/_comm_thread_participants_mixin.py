# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CommThreadRepository participant-directory access (BE-9289a split).

Cohesive unit extracted from ``CommThreadRepository`` to keep that module under the
800-line guardrail, following the same seam ``_comm_thread_directed_actions_mixin``
took: everything that reads or writes ``comm_participants`` — the registration upsert,
the liveness stamp, and the two directory reads. Inherited by ``CommThreadRepository``
so the public repository API is unchanged.

Tenant-scoped on every query; the session is passed in by the caller.
Edition Scope: CE.
"""

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
    """A participant's CURRENT execution status, as a correlated scalar subquery.

    THE one expression both participant reads use — the Hub's thread-card list
    (``list_threads_enriched``) and the opened thread's directory
    (``get_participants_with_status`` -> ``list_participants``). It lives here, with the
    participant reads, because "what is this agent doing now" is a fact ABOUT a
    participant; the card list imports it rather than owning it.

    Sharing the expression is the fix for TSK-9457 and not a tidiness preference. The
    card list selected this status and the directory selected nothing at all, so the
    directory's payload had no ``status`` key; the client's own missing-status
    normalisation then read that hole as ``idle``, which the dashboard labels
    "Monitoring". One agent therefore read "Silent" on the card and "Monitoring" inside
    it — the second of those being a default the client invented, not a second opinion.
    Two copies of this subquery would fix today's symptom and leave the two views free to
    drift apart again on the ordering rule.

    ``agent_executions`` is THE truth about an agent the platform is running, and it is
    what the Jobs board reads. That shared source is the whole point: the dot's colour
    vocabulary has to AGREE with the board the operator already learned it from. This
    expression is therefore never coalesced with anything at this level — see
    ``participant_display_status`` for the one fallback there is, and why it can only
    ever apply to a participant this subquery knows nothing about.

    BE-9475 SUPERSEDES A SENTENCE THAT USED TO BE HERE. This docstring asserted that
    "there is no status column on ``comm_participants`` and there should not be". There
    now is one, and the reasoning behind that sentence survives intact rather than being
    overruled: a participant row still does not record what a Giljo-run agent is doing —
    this subquery does, and it still wins. What the sentence missed is the case it did
    not cover. A headless agent has no execution row at all, so "the truth lives in
    ``agent_executions``" resolves to no truth whatsoever, permanently, and the client
    renders that hole as idle / "Monitoring". The column exists for exactly those
    participants and is subordinate to this expression everywhere else.

    ``started_at DESC LIMIT 1`` matches ``AgentJobRepository.get_latest_execution``
    verbatim. One ``agent_id`` accumulates several executions through succession, and
    picking a different row than the Jobs board would show two different statuses for one
    agent on two screens. Postgres orders NULLs FIRST on DESC, so a freshly staged
    successor (no ``started_at`` yet) correctly outranks the predecessor it replaced
    instead of showing that predecessor's ``complete``.

    Returns NULL when the agent never registered an execution. The client renders that as
    a hollow ring — "never checked in" — and a missing status as slate, never green.
    Absent data must not read as healthy, so callers must NOT coalesce a default onto it.

    ``correlate(CommParticipant)`` is explicit rather than left to auto-correlation: this
    is consumed inside another subquery in the card-list path, and a lost correlation
    there degrades into a cross-join over every execution in the tenant.
    """
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
    """The status a participant is SERVED as — THE one expression both reads use.

    ``latest_execution_status`` first, ``self_reported_status`` only underneath it
    (BE-9475). Both consumers import this and neither re-spells it: the Hub's
    thread-card list (``list_threads_enriched``) and the opened thread's directory
    (``get_participants_with_status`` -> ``list_participants``). That single-expression
    rule IS the TSK-9457 fix — when the card list owned its own copy the directory had
    none, the client filled the hole with ``idle``/"Monitoring", and one agent read
    "Silent" on the card and "Monitoring" inside it. A second copy would fix today's
    symptom and leave the two views free to drift apart again on the precedence rule,
    which is a far worse thing to disagree about than the ordering rule was.

    PRECEDENCE IS FREE HERE, NOT CONDITIONAL, AND THAT IS LOAD-BEARING.
    ``AgentExecution.status`` is ``nullable=False``, so an execution row can never
    contribute a NULL to this COALESCE. "Execution wins whenever a row exists" therefore
    falls straight out of the operand order, with no CASE and no EXISTS probe. If that
    column is ever made nullable, this expression silently starts letting a
    self-declaration outrank a real execution — so the nullability is a precondition of
    the fallback, not an incidental detail.

    The direction is the point. A self-declaration may never contradict the Jobs board
    about an agent the platform is actually running; it may only speak for a participant
    the platform is running nothing for. ``self_reported_status`` is therefore the answer
    to "what is this thing doing" ONLY where the previous answer was permanently NULL.

    NULL BOTH WAYS STAYS NULL. Never-registered and never-declared still serves NULL,
    which the client renders as the hollow ring — "never checked in". Absent data must
    not read as healthy, so callers must NOT coalesce a default onto this either. That
    is the same rule as before and this expression does not weaken it: COALESCE of two
    NULLs is NULL, and the no-status cases are byte-identical to their pre-BE-9475
    payloads.
    """
    return func.coalesce(latest_execution_status(tenant_key), CommParticipant.self_reported_status)


# Column caps on comm_participants (models/comm.py). Agent-supplied free text
# must be bounded HERE, at the single write choke point, because a DB
# constraint produces a 500 (asyncpg StringDataRightTruncationError, Sentry
# GILJOAI-BACKEND-Q), not a clean rejection or clamp.
_PARTICIPANT_ID_MAX = 255
_DISPLAY_NAME_MAX = 255
_ROLE_MAX = 50


class CommThreadParticipantsMixin:
    """Participant directory reads/writes. Inherited by CommThreadRepository."""

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
        """Register a participant on a thread, collision-safe (idempotent join).

        Re-joining the same ``(thread_id, participant_id)`` never duplicates the row.

        BE-9289a -- it also no longer DISCARDS what the re-join carries. This was
        ``ON CONFLICT DO NOTHING``, so the nameless row written by
        ``_auto_enroll_project_roster`` won permanently and a later ``join_thread``
        supplying a real display name was silently dropped: the directory could never
        learn the agent's name.

        AUTHORITY IS SETTLED BY WRITER, NOT BY COLUMN. There are two kinds of caller:

        - ``authoritative=True`` -- the participant is DECLARING itself (``join_thread``,
          an operator rename). Its non-null values WIN. This is the fix for the original
          defect: a real name lands over a nameless enroll.
        - ``authoritative=False`` (default) -- a PLACEHOLDER writer that merely observes
          someone is present: ``_auto_enroll_project_roster``, and registration on post.
          It FILLS BLANKS BUT NEVER CORRECTS. Auto-enroll re-runs on every broadcast to a
          project thread and carries a non-null roster name plus the literal role
          ``"auto-enrolled"``; if it could overwrite, the badge would be decided by
          whichever write happened last and would flap on every message.

        One rule covers ``display_name`` and ``role`` together, so the two cannot drift
        apart and the next reader cannot get one of them backwards.

        Two columns sit outside that rule because they are SERVER-stamped, never claimed:
        - ``harness`` -- latest CONCRETE detection wins, because it comes from the MCP
          handshake and an agent may genuinely reconnect from a different one. But
          ``generic`` is the resolver's "I could not tell", not an observation, so it
          never overwrites a known harness — see the NULLIF below.
        - ``last_seen_at`` -- advanced only when the caller says this is activity
          (``touch_last_seen``), so a passive enroll never fakes liveness.

        ``self_reported_status`` (BE-9475) sits outside the authority rule too, in the
        opposite direction: a non-NULL value ALWAYS wins, for both writer kinds. It is
        not a claim about identity that two writers could disagree on -- it is the
        participant's own report about itself, and only the ``my_status`` path ever
        supplies one. Every placeholder writer passes NULL, so the COALESCE below is what
        stops an auto-enroll (which re-runs on every broadcast to a project thread) from
        wiping a live agent's declared status back to nothing. It is validated against
        ``VALID_SELF_REPORTED_STATUSES`` before it reaches here -- see the MCP boundary.
        """
        if participant_type not in VALID_PARTICIPANT_TYPES:
            raise ValidationError(
                f"participant_type must be one of {VALID_PARTICIPANT_TYPES}, got '{participant_type}'.",
                context={"operation": "comm_thread.add_participant", "participant_type": participant_type},
            )

        # Bound agent-supplied text to the column caps. participant_id is an
        # IDENTITY — truncating it would silently change who joined, so an
        # oversized one is rejected. display_name and role are display-only
        # descriptors, safe to clamp.
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
            # Stamped only alongside a real declaration, so the timestamp can never
            # outlive or precede the status it describes.
            self_reported_status_at=datetime.now(UTC) if self_reported_status else None,
        )
        excluded = insert_stmt.excluded
        existing = CommParticipant.__table__.c

        def claimed(column_name: str):
            """A self-declared column: the authoritative writer wins, a placeholder
            writer only fills a blank."""
            incoming, current = getattr(excluded, column_name), existing[column_name]
            return func.coalesce(incoming, current) if authoritative else func.coalesce(current, incoming)

        await session.execute(
            insert_stmt.on_conflict_do_update(
                constraint="uq_comm_participant",
                set_={
                    "display_name": claimed("display_name"),
                    "role": claimed("role"),
                    # Server-stamped, never claimed -- but ``generic`` is the resolver's
                    # "I could not tell" value, not an observation, so it must never
                    # overwrite a concrete one. Without the NULLIF, any post through a
                    # path with no clientInfo (REST, in-memory transport) silently
                    # downgraded an agent that had joined as claude-code back to generic.
                    # Order: a real detection wins, else keep what we know, else record
                    # the floor so a first insert still says something.
                    "harness": func.coalesce(
                        func.nullif(excluded.harness, GENERIC_HARNESS),
                        existing.harness,
                        excluded.harness,
                    ),
                    "last_seen_at": func.coalesce(excluded.last_seen_at, existing.last_seen_at),
                    # BE-9475: a declaration wins whenever one is supplied; every other
                    # writer passes NULL and therefore preserves what is already there.
                    # The pair moves together so the timestamp always describes the
                    # status stored beside it.
                    "self_reported_status": func.coalesce(excluded.self_reported_status, existing.self_reported_status),
                    "self_reported_status_at": func.coalesce(
                        excluded.self_reported_status_at, existing.self_reported_status_at
                    ),
                },
            )
        )
        await session.flush()

        # BE-9289a: populate_existing is load-bearing now that the conflict path UPDATEs.
        # The upsert runs as Core SQL, so an instance already in the session's identity
        # map keeps its stale attributes and this read would hand back the pre-update
        # values (the very name the upsert just fixed). Force the refresh.
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
        """Stamp ``last_seen_at`` for a participant (BE-9289a liveness).

        An UPDATE, never an insert: a READ or a baton poll is evidence that a
        participant is alive, but it is not a reason to enroll anyone. Rows that do not
        exist are simply not touched.

        ``thread_id`` narrows to one thread (a thread read); omitting it stamps every
        thread this participant belongs to, which is what a thread-agnostic poll like
        ``get_my_turn`` actually tells us. Both forms are served by
        ``idx_comm_participant_lookup`` (tenant_key, participant_id).
        """
        conditions = [
            CommParticipant.tenant_key == tenant_key,
            CommParticipant.participant_id == participant_id,
        ]
        if thread_id is not None:
            conditions.append(CommParticipant.thread_id == thread_id)
        await session.execute(update(CommParticipant).where(*conditions).values(last_seen_at=datetime.now(UTC)))

    async def get_participants(self, session: AsyncSession, tenant_key: str, thread_id: str) -> list[CommParticipant]:
        """All participants registered on a thread (tenant-scoped)."""
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
        """All participants on a thread, each with its CURRENT execution status (TSK-9457).

        ``(participant, status)`` pairs, status ``None`` when the agent has neither an
        execution row nor a self-declaration (BE-9475). One query — the status is a
        correlated subquery on the same select, not a follow-up read per participant.

        Separate from ``get_participants`` deliberately: callers that only need the
        participant ROWS (registration, baton resolution, roster checks) should not pay
        for a per-row execution lookup, and ORM rows are what they want back.
        Tenant-scoped on both tables.
        """
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
        """One participant row (the D6 read-cursor anchor) or None; None = never joined
        => "nothing read yet" / mark_read refused (BE-9012a). Tenant-scoped."""
        result = await session.execute(
            select(CommParticipant).where(
                CommParticipant.tenant_key == tenant_key,
                CommParticipant.thread_id == thread_id,
                CommParticipant.participant_id == participant_id,
            )
        )
        return result.scalar_one_or_none()
