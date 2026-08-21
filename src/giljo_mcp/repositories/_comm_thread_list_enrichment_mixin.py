# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Per-thread card facts for the Hub list, in one round trip (BE-9289b).

TWO reasons this is its own module, and both are real.

The read concern is genuinely distinct. Everything else in ``CommThreadRepository`` is
thread CRUD and the baton/status queries the tool surface is built on. This is
presentation enrichment for one surface — the Quiet Cards list — and it joins across
``projects``, ``messages`` and ``comm_participants`` to assemble facts no other caller
wants. Mixing it into thread CRUD would put a card-shaped query in the middle of the
data foundation.

And the 800-line cap forced the seam: ``comm_thread_repository.py`` reached 831 lines
with this query inline, with no shrink-only budget to spend. The alternative was cutting
the rationale out of the query to fit, which is the wrong trade.

Inherited by ``CommThreadRepository``, on the seam ``_comm_thread_directed_actions_mixin``
and ``_comm_thread_participants_mixin`` already established, so the public repository API
is unchanged.

Tenant-scoped on every joined table.
Edition Scope: CE.
"""

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
    """What the card should CALL this thread (BE-9289b item 3).

    Structural, and deliberately narrow. A thread bound to a project is titled from that
    project, full stop — that is what keeps a card from reading ``(project comms)``, the
    machine-minted marker a system-created bound thread carries. The marker itself is
    untouched: it is load-bearing resolution machinery
    (``resolve_or_create_bound_thread`` orders on it and the ce_0072 fold replicates that
    precedence), so this changes only what the API DISPLAYS, never what is stored.

    Everything else renders its own stored subject verbatim, chain hubs included — and
    that is now simply the ordinary case rather than a special one. It used to be a
    hazard: a hub's subject CARRIED the run_id, the conductor's seed instruction told
    sub-orchestrators to find their hub with ``search_threads(query="{run_id}")``, and so
    the subject WAS the discovery key. Parsing a prettier title out of it would have
    broken discovery silently for every future run.

    BE-9291 moved discovery onto ``comm_threads.sequence_run_id``, a real FK, so nothing
    reads the subject to find a hub any more and new hubs are not asked to carry the id
    at all. Display and lookup are finally separate concerns. Chain hubs are still made
    readable at BIRTH, and legacy ones remain renameable by the operator.
    """
    return project_name or subject


class CommThreadListEnrichmentMixin:
    """Card-facts enrichment for the thread list. Inherited by CommThreadRepository."""

    async def list_threads_enriched(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        viewer_id: str,
        threads: list[CommThread],
    ) -> dict[str, dict[str, Any]]:
        """Per-thread card facts for the Hub list, in ONE round trip (BE-9289b).

        The card shows three things — the thread's name, who registered on it, and the
        last thing said — plus whether there is anything new. The list read could not
        supply any of them, so the UI issued a follow-up call per thread; this replaces
        that N+1 with a single query over the page of threads it was already given.

        Returns ``{thread_id: {project_name, participants, last_message, unread}}``.

        ``unread`` is a BOOLEAN, deliberately, and is an ``EXISTS`` rather than a count
        that gets cast: the card's design bar is no numbers except relative times, and a
        count on the payload is an open invitation to render one. It keys on
        ``comm_participants.last_read_at`` (the BE-9012a cursor, already stored and
        previously unused by the list) — no participant row, or a NULL cursor, means
        nothing has been read, so any message at all counts as unread.

        Tenant-scoped on every joined table.
        """
        thread_ids = [t.id for t in threads]
        if not thread_ids:
            return {}

        # The viewer's read cursor for THIS thread — correlated, so it resolves per row.
        #
        # ``correlate(CommThread)`` is load-bearing and NOT decorative. This subquery is
        # consumed inside the ``unread`` EXISTS, whose own FROM is ``messages``;
        # auto-correlation only reaches the immediately enclosing query, finds no
        # ``comm_threads`` there, and so adds one to this subquery's FROM. That turns
        # ``thread_id == CommThread.id`` into a self-join against every thread rather
        # than a correlation to the current row, and the subquery returns one row per
        # thread the viewer belongs to. With ``uq_comm_participant`` guaranteeing at most
        # one participant row per (thread, participant), more than one row can only mean
        # the correlation was lost. Postgres then raises CardinalityViolationError and
        # the whole thread list 500s — for any viewer in two or more threads, which is
        # every real user (Sentry: GET /api/v1/threads, 2026-08-04).
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

        # Newest post per thread, as a LATERAL so it costs one index seek per row
        # (idx_messages_thread_created serves exactly this) instead of a second query.
        #
        # FE-9418: ``message_id`` is the ANCHOR — the id of the post this summary
        # describes. It is labelled, not projected as a bare ``id``, and that is
        # load-bearing: the outer select already carries ``CommThread.id``, so two
        # columns named ``id`` would land in one row tuple and attribute access would
        # resolve to the first. The THREAD id would then be served as the message
        # anchor, the client would deep-link to a message that does not exist, and any
        # assertion weaker than "it differs from the thread id" would stay green.
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

        # The status this participant is SERVED as, for the card's status dot.
        #
        # TSK-9457 moved this expression to ``_comm_thread_participants_mixin`` and left
        # a call here. It is IMPORTED, never re-spelled: the opened thread's directory
        # read serves the same field, and when the card list owned its own copy the
        # directory simply had none — the client filled that hole with ``idle``, labelled
        # "Monitoring", and one agent read "Silent" on the card and "Monitoring" inside
        # it. Two copies would fix that once and let the two views drift again.
        #
        # BE-9475 widened WHAT the shared expression resolves to (execution status, then
        # a headless participant's own declaration underneath it) without forking it —
        # this call site changed name and nothing else, which is the whole benefit of
        # having imported it rather than spelled it.
        #
        # The precedence rule, the ordering rule, the deliberate NULL, and why
        # ``correlate`` is explicit are all documented on ``participant_display_status``
        # and ``latest_execution_status``. That correlation matters here for
        # exactly the reason documented on ``last_read`` above: this sits inside another
        # subquery, and losing it degrades into a cross-join over every execution in the
        # tenant.
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
                            # NULL when the agent has neither an execution row nor a
                            # self-declaration (BE-9475). The client renders that as a
                            # hollow ring — "never checked in" —
                            # and a missing status as slate, never green. Absent data
                            # must not read as healthy, so do NOT coalesce a default here.
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
                        # FE-9418: the anchor a baton notification pins to. Absent
                        # posts still yield ``last_message: None`` below, so a thread
                        # nobody has spoken in names nothing to pin.
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
