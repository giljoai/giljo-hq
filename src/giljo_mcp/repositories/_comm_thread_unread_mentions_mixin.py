# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Unread mentions, as a server fact (FE-9586).

"Was I mentioned" used to be decided on the CLIENT, in
``useHubNotifications.getSignal()``, by matching the user's display name against
``payload.content``. That put the definition in the one place that cannot
reliably see the text: a post over ~5.8 KB rides the cross-worker broker as a
bounded EXCERPT (pg_notify caps a NOTIFY payload at 7999 bytes, BE-9414), and
that composable's own docblock admits it falls back to the excerpt when the
hydrating read fails. A mention written past the cut-off was therefore invisible
to the very reader it named. This query reads the ``content`` column whole, so
where the name sits in the body cannot matter.

It is also what lets a mention BANNER exist. A banner follows STATE,
and until now nothing said "you have been named and have not looked" -- which is
why FE-9553 had to ship mention popouts event-shaped with a TTL instead of as
projections.

ONE DEFINITION, NOT TWO. The client's match is DELETED in the same change that
adds this. Two definitions of "mention" that can disagree is the failure this
project exists to remove: the first time they diverge, someone gets a bell row
with no banner or the reverse.

TENANT-SCOPED, NOT PARTICIPATION-SCOPED -- a deliberate divergence from the
BE-9207 directed-action sibling, which requires a ``message_recipients`` row.
Directedness is DELIVERY; a mention is NAMING. The Hub's WS fan-out is
tenant-wide (``broadcast_event_to_tenant``), so the operator is signalled today
for any thread in the tenant where their name appears, participant or not.
Requiring participation would SILENCE mentions they currently receive.

RESOLUTION is the read watermark, not an acknowledgment: a mention is answered
when the reader has read the thread ("acting in the Hub clears it"). No
participant row, or a NULL cursor, means nothing has been read -- so any naming
post counts, which is the honest reading of "never looked".

Tenant-scoped on every joined table -- and one honest note about that. The
``Message.tenant_key`` predicate is defence in depth, not load-bearing: mutating
it away kills no test, because the thread is already tenant-scoped, the join is
on ``thread_id``, and row-level security blocks a message row stamped with a
foreign tenant from being written or read at all. It stays for consistency with
every sibling query and with the codebase rule that every query filters by
tenant_key. It is recorded as unproven rather than described as a guard.

Edition Scope: Both.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.comm import TERMINAL_THREAD_STATUSES, CommParticipant, CommThread
from giljo_mcp.models.tasks import Message


# LIKE's own metacharacters, plus the escape character itself. A display name is
# user-controlled text, not a pattern: unescaped, a name like ``A_B`` would also
# match ``AxB`` because ``_`` is LIKE's single-character wildcard, and would
# report a mention of somebody nobody named.
_LIKE_ESCAPE = "\\"


def _literal_contains_pattern(needle: str) -> str:
    """``%needle%`` with every LIKE metacharacter in ``needle`` neutralised."""
    escaped = needle.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
    escaped = escaped.replace("%", f"{_LIKE_ESCAPE}%").replace("_", f"{_LIKE_ESCAPE}_")
    return f"%{escaped}%"


class CommThreadUnreadMentionsMixin:
    """Per-viewer unread-mention read. Inherited by CommThreadRepository."""

    async def get_unread_mentions(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        viewer_id: str,
        display_name: str | None,
    ) -> list[tuple[CommThread, str]]:
        """``(thread, message_id)`` for every unread post that NAMES ``viewer_id``.

        IT NAMES THE POSTS, not just the threads, and that is not convenience. Both
        consumers are post-anchored: the durable bell row keys on the post (a second
        mention is a second thing somebody asked you, so collapsing them onto one
        thread-keyed row loses one), and the popout deep-links to the exact post
        rather than the thread tail. A thread-only projection would force the client
        to guess which arriving event the verdict referred to -- and with two posts
        landing together it would sometimes guess wrong and anchor a bell row to the
        post that did NOT name anybody.

        Newest post first. The caller groups by thread for the banner; the raw pairs
        are what the bell and the deep-link need.

        A thread qualifies when it holds at least one message that is ALL of:
          - naming ``display_name``, case-insensitively, matched LITERALLY;
          - not the viewer's own post (writing your own name is not being named);
          - newer than the viewer's read cursor, or the viewer has never read the
            thread at all;
        with the thread itself LIVE (``deleted_at IS NULL``) and NON-terminal --
        "done" and "needs you" cannot both be true (FE-9365i, BE-9207).

        An empty or absent ``display_name`` matches NOTHING and returns early. It
        must never fall through to the query: ``%`` || '' || ``%`` matches every
        post ever written, so a user who has not set a display name would be told
        that every thread in the tenant mentions them.

        Tenant-scoped on every joined table. No schema change.
        """
        if not display_name:
            return []

        # The viewer's cursor for THIS thread. ``correlate(CommThread)`` is
        # load-bearing exactly as it is on the BE-9289b enrichment: this subquery is
        # consumed inside a query whose FROM is ``messages``, so auto-correlation
        # would not find ``comm_threads`` there and would add one -- turning the
        # thread match into a self-join across every thread and returning a row per
        # thread the viewer belongs to. Postgres then raises CardinalityViolation for
        # any viewer in two or more threads, which is every real user.
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
                # A NULL author is not the viewer. Spelled as an OR rather than a bare
                # ``!=`` because ``NULL != 'x'`` is NULL, not true, so the bare form
                # would silently drop every post whose author was not recorded --
                # posts that legitimately name the viewer.
                or_(Message.from_agent_id.is_(None), Message.from_agent_id != viewer_id),
                or_(last_read.is_(None), Message.created_at > last_read),
            )
            .order_by(Message.created_at.desc())
        )
        result = await session.execute(stmt)
        # No DISTINCT: one row per NAMING POST is the point, and several posts on one
        # thread are several facts. ``.all()`` rather than ``.scalars()`` -- scalars()
        # would silently keep only the first column and throw the message ids away.
        return [(row[0], row[1]) for row in result.all()]
