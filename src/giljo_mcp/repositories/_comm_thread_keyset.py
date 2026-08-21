# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The keyset pagination primitives for the thread list (BE-9469 item 1).

Extracted from ``comm_thread_repository`` so that module stays under the 800-line
guardrail, and because the ORDER BY and the keyset comparison are ONE decision recorded
in two places. They must agree on both the column set and each column's direction, and
the cheapest way to keep them agreeing is to make them impossible to read separately.

The two expression builders are pure functions over SQLAlchemy expressions -- no
``self``, no state. ``resolve_thread_cursor`` takes a session because resolving a cursor
is a read, and it takes ``tenant_key`` explicitly because the resolution MUST be
tenant-scoped: that scoping is what makes a foreign-tenant cursor indistinguishable from
a nonexistent one.

Edition Scope: Both.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.comm import CommThread


def thread_list_order_clauses() -> list[Any]:
    """``created_at DESC, id ASC`` -- newest first, with a UNIQUE tiebreak.

    ``id`` is what makes a page boundary reproducible. Without it PostgreSQL is free to
    return a tie group in any order it likes, so even a correct keyset comparison walks
    an unstable sequence: measured on real Postgres, a six-row tie group came back in
    neither ``id`` order nor insertion order.

    The tiebreak DIRECTION is load-bearing, not cosmetic -- :func:`thread_keyset_after`
    compares ``id >`` to match this ``ASC``. Change one and you must change the other, or
    the walk skips at the far end of every tie group instead of the near end.
    """
    return [CommThread.created_at.desc(), CommThread.id.asc()]


def thread_keyset_after(cursor_ts: datetime, before_id: str) -> Any:
    """Rows sorting strictly AFTER ``(cursor_ts, before_id)`` under the order above.

    **The bug this replaces.** ``CommThread.created_at`` takes
    ``server_default=func.now()`` and PostgreSQL's ``now()`` is TRANSACTION-scoped, so
    every row written in one transaction carries a byte-identical timestamp. The
    original comparison was a strict single-column ``created_at < cursor_ts``, which
    discarded the ENTIRE tie group -- including the tied rows the walk had not yet
    returned. Measured on real Postgres: five tied rows paged at ``limit=4`` returned
    four, and paged at ``limit=1`` returned ONE. Both reported completion. No error, no
    warning, no truncation signal -- an answer quietly missing rows, which is worse than
    a failure because the caller acts on it.

    **Why an explicit OR and not a row-value comparison.** ``(created_at, id) < (ts,
    before_id)`` is the shorter spelling and it is WRONG here: a row-value comparison
    applies one direction to every element, so it would mean ``id`` DESCENDING while the
    ORDER BY sorts ``id`` ascending. That reintroduces the skip at the opposite end of
    each tie group -- a fix that looks tidier and loses different rows.

    **NULL ``created_at`` needs no clause of its own.** Both operands of the OR are
    NULL-false, so a NULL row is excluded, and that is the correct exclusion: ``DESC``
    sorts NULLs FIRST in PostgreSQL, so a NULL row already sorts BEFORE any non-NULL
    cursor and belongs to a page the walk has passed.
    """
    return or_(
        CommThread.created_at < cursor_ts,
        and_(CommThread.created_at == cursor_ts, CommThread.id > before_id),
    )


async def resolve_thread_cursor(session: AsyncSession, tenant_key: str, before_id: str) -> datetime:
    """Resolve ``before_id`` to its ``created_at``, or REFUSE. Never tolerates.

    **The behavior this replaces, and it is a deliberate change.** The caller previously
    resolved the cursor with ``scalar_one_or_none()`` and, on None, applied NO keyset at
    all -- so a ``before_id`` naming a thread that does not exist, or one belonging to
    another tenant, silently returned the FIRST page again. A client that trusts the
    cursor then collects page one forever and never terminates.

    Museum check, done before changing it: the block landed in BE-6131b with no comment
    on the None arm, no test covering it, and a docstring describing only the
    found-cursor case. Nothing made tolerate-on-None deliberate; it is an oversight.

    So a call that "succeeded" with wrong data now fails with a remedy, on the reasoning
    that a silently-wrong success is worse than an honest refusal.

    **The refusal message carries NO identifier, and that is a security property rather
    than terseness.** The lookup is ``tenant_key``-scoped, so a nonexistent id and
    another tenant's id both arrive here identically -- and a message that distinguished
    them would turn a pagination parameter into an oracle for whether another tenant's
    thread id exists. One message, one raise site, no branch: the indistinguishability is
    structural and cannot drift.
    """
    cursor_ts = (
        await session.execute(
            select(CommThread.created_at).where(
                CommThread.tenant_key == tenant_key,
                CommThread.id == before_id,
            )
        )
    ).scalar_one_or_none()
    if cursor_ts is None:
        raise ValidationError(
            "before_id does not name a thread on this list. It may have been deleted "
            "since the page that produced it. Restart the walk by calling again without "
            "before_id.",
            context={"operation": "comm_thread.list"},
        )
    return cursor_ts
