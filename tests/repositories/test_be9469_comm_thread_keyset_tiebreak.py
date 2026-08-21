# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9469 item 1 -- the composite keyset tie-break, at the repository layer.

``CommThreadRepository.list_threads`` pages with ``limit`` + ``before_id`` (BE-6131b).
The keyset compared ``created_at`` ALONE and the ORDER BY carried no unique tiebreak.
``created_at`` defaults to ``server_default=func.now()``, and PostgreSQL's ``now()`` is
TRANSACTION-scoped -- so every row inserted in one transaction carries a byte-identical
timestamp. A strict ``created_at < cursor_ts`` then discards every tied row, including
the ones the walk has not yet returned.

Measured shape: **five rows in, four rows out, one silently skipped, no error.** The walk
does not fail, does not warn, and does not report a truncation -- it just returns an
answer that is quietly missing a row, which is the defect class the whole read-layer
family exists to remove.

Latent for MCP callers (no MCP tool passes ``before_id``) but ``before_id`` is a SHIPPED
REST contract at ``api/endpoints/comm_threads.py``, so a REST client paging a thread list
can hit this today.

Failing layer = the repository, so the regression test lives here: real Postgres via the
rollback-isolated ``db_session`` fixture, no mocks. A same-transaction insert is not a
contrivance for the test -- it is precisely how the application writes, and it is why the
ties exist at all.
"""

from __future__ import annotations

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.comm import CommThread
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9469_{suffix}"


async def _seed_tied_threads(db_session, tenant: str, count: int) -> list[CommThread]:
    """Create ``count`` threads in ONE transaction, so all share a ``created_at``.

    Returns them in creation order. The tie is the point: no ``created_at`` is passed,
    so every row takes ``server_default=func.now()``, which PostgreSQL evaluates once
    per transaction.
    """
    await ensure_default_types_seeded(db_session, tenant)
    repo = CommThreadRepository()
    threads = [await repo.create_thread(db_session, tenant, subject=f"tied {i}") for i in range(count)]
    await db_session.flush()
    return threads


async def _walk(db_session, tenant: str, *, page_size: int, max_pages: int = 20) -> list[str]:
    """Page the whole list with ``limit`` + ``before_id`` and collect the ids seen.

    This is the caller's loop, written exactly as the shipped REST contract documents
    it: fetch a page, take the LAST row's id as the next ``before_id``, stop on an empty
    page. ``max_pages`` bounds a pathological repeat so a broken keyset shows up as a
    wrong id list rather than as a hung test.
    """
    repo = CommThreadRepository()
    seen: list[str] = []
    before_id: str | None = None
    for _ in range(max_pages):
        page = await repo.list_threads(db_session, tenant, limit=page_size, before_id=before_id)
        if not page:
            break
        seen.extend(t.id for t in page)
        before_id = page[-1].id
    return seen


async def test_all_rows_share_a_created_at_when_inserted_in_one_transaction(db_session):
    """THE INSTRUMENT CHECK -- proves the tie this suite depends on is real.

    Without this, a green walk test would be ambiguous: it could mean the keyset is
    correct, or it could mean the fixture never produced a tie and the walk never
    exercised the boundary. Asserting the precondition separately is what makes the
    failing walk below a reproduction rather than a coincidence.
    """
    tenant = _tk("tie_precondition")
    with tenant_session_context(db_session, tenant):
        threads = await _seed_tied_threads(db_session, tenant, 5)

    timestamps = {t.created_at for t in threads}
    assert len(timestamps) == 1, (
        f"expected all 5 rows to share one transaction-scoped created_at, got {sorted(timestamps)}"
    )


async def test_paging_a_tied_page_boundary_returns_every_row(db_session):
    """5 rows in, 5 rows out. Pre-fix this returns 4 -- one row silently skipped.

    ``page_size=4`` puts the boundary INSIDE the tie group: page one returns four of the
    five tied rows, and the next request's ``created_at < cursor_ts`` excludes all five,
    so the fifth row is unreachable. Nothing in the response says so.
    """
    tenant = _tk("walk_five")
    with tenant_session_context(db_session, tenant):
        threads = await _seed_tied_threads(db_session, tenant, 5)
        expected = {t.id for t in threads}
        seen = await _walk(db_session, tenant, page_size=4)

    assert len(seen) == len(set(seen)), f"the walk returned a duplicate id: {seen}"
    assert set(seen) == expected, (
        f"the walk skipped {sorted(expected - set(seen))} -- {len(seen)} of {len(expected)} rows returned"
    )


async def test_paging_one_row_at_a_time_across_a_full_tie_group(db_session):
    """The tightest boundary: every page boundary falls inside the tie group.

    ``page_size=1`` across five tied rows means the keyset is exercised four times with
    the cursor's own timestamp equal to every remaining row's. Pre-fix the walk stops
    after the first row.
    """
    tenant = _tk("walk_one_by_one")
    with tenant_session_context(db_session, tenant):
        threads = await _seed_tied_threads(db_session, tenant, 5)
        expected = {t.id for t in threads}
        seen = await _walk(db_session, tenant, page_size=1)

    assert len(seen) == len(set(seen)), f"the walk returned a duplicate id: {seen}"
    assert set(seen) == expected, (
        f"the walk skipped {sorted(expected - set(seen))} -- {len(seen)} of {len(expected)} rows returned"
    )


async def test_list_threads_order_is_deterministic_across_identical_requests(db_session):
    """Two identical requests over a tie group must return the SAME order.

    Without a unique tiebreak in the ORDER BY, PostgreSQL is free to return tied rows in
    any order, so a page boundary is not reproducible even when the keyset comparison is
    right. This asserts the ordering half of the fix, which the walk alone does not pin.
    """
    tenant = _tk("stable_order")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await _seed_tied_threads(db_session, tenant, 6)
        first = [t.id for t in await repo.list_threads(db_session, tenant, limit=6)]
        second = [t.id for t in await repo.list_threads(db_session, tenant, limit=6)]

    assert first == second, f"tied rows came back in two different orders: {first} vs {second}"
    # The declared contract is newest-first with a stable tiebreak; with every
    # created_at equal, the tiebreak alone decides, and it is id ASC.
    assert first == sorted(first), f"tied rows are not ordered by the id tiebreak: {first}"


async def test_no_cursor_page_is_unchanged_by_the_tiebreak(db_session):
    """Backward compatibility: a first page (no ``before_id``) still returns ``limit`` rows.

    The fix adds a tiebreak to the ORDER BY and a composite comparison to the keyset. It
    must not change how many rows an un-cursored call returns, which is the call every
    shipped caller actually makes.
    """
    tenant = _tk("no_cursor")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await _seed_tied_threads(db_session, tenant, 5)
        page = await repo.list_threads(db_session, tenant, limit=3)
        unbounded = await repo.list_threads(db_session, tenant)

    assert len(page) == 3
    assert len(unbounded) == 5


# --------------------------------------------------------------------------
# BE-9469, folded in under the project's in-boundary-discovery rule: an unresolvable
# cursor is REFUSED, not tolerated.
# --------------------------------------------------------------------------
#
# Found while fixing the tie-break, in the same function, on the same shipped line.
# ``before_id`` was resolved with ``scalar_one_or_none()`` and the None arm applied NO
# keyset at all -- so a cursor naming a thread that does not exist, or one belonging to
# another tenant, silently returned the FIRST page again. A client loop that trusts the
# cursor then never terminates, and every page it collects is page one.
#
# MUSEUM CHECK, done before treating this as an accident: the block was introduced in
# BE-6131b (``a651dc9d8``, 2026-06-18) with no comment on the None arm, no test covering
# it, and a docstring describing only the found-cursor case. Nothing makes
# tolerate-on-None deliberate. It is an oversight, not an exhibit.
#
# THE ONE DELIBERATE BEHAVIOR CHANGE in this change set: a call that "succeeds" today
# with wrong data now fails with a remedy. Taken knowingly, because a silently-wrong
# success is worse than an honest refusal -- and no in-tree caller passes ``before_id``
# at all, so the reach is the REST query parameter alone.


async def test_an_unknown_before_id_is_refused_instead_of_restarting_the_walk(db_session):
    """A cursor naming no thread must raise, not silently return page one.

    Pre-fix this returns the full first page, so a paging client believes it received
    valid rows and can loop forever.
    """
    tenant = _tk("unknown_cursor")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await _seed_tied_threads(db_session, tenant, 3)
        with pytest.raises(ValidationError) as exc:
            await repo.list_threads(db_session, tenant, limit=2, before_id="00000000-0000-0000-0000-000000000000")

    message = str(exc.value)
    # The refusal has to tell the agent what to DO, not merely that it failed.
    assert "before_id" in message
    assert "restart" in message.lower()


async def test_a_foreign_tenants_before_id_is_refused_identically(db_session):
    """A cursor from ANOTHER tenant must be indistinguishable from one that does not exist.

    Same exception type, same message text. If the two differed, the parameter would
    answer "does thread X exist in some other tenant?" -- turning a pagination cursor
    into an existence oracle for other tenants' ids.
    """
    other = _tk("foreign_owner")
    mine = _tk("foreign_caller")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, other):
        foreign = (await _seed_tied_threads(db_session, other, 1))[0]

    with tenant_session_context(db_session, mine):
        await _seed_tied_threads(db_session, mine, 3)
        with pytest.raises(ValidationError) as foreign_exc:
            await repo.list_threads(db_session, mine, limit=2, before_id=foreign.id)
        with pytest.raises(ValidationError) as unknown_exc:
            await repo.list_threads(db_session, mine, limit=2, before_id="00000000-0000-0000-0000-000000000000")

    assert str(foreign_exc.value) == str(unknown_exc.value), (
        "a foreign-tenant cursor is distinguishable from an unknown one, which leaks "
        f"whether another tenant's thread id exists: {foreign_exc.value!s} vs {unknown_exc.value!s}"
    )


async def test_a_resolvable_before_id_still_pages_normally(db_session):
    """The refusal must not fire on the happy path -- the control for the two above.

    Without this, both refusal tests would pass on an implementation that rejects EVERY
    cursor, which would be a worse bug than the one being fixed.
    """
    tenant = _tk("valid_cursor")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        threads = await _seed_tied_threads(db_session, tenant, 4)
        first = await repo.list_threads(db_session, tenant, limit=2)
        second = await repo.list_threads(db_session, tenant, limit=2, before_id=first[-1].id)

    assert len(second) == 2
    assert {t.id for t in first}.isdisjoint({t.id for t in second})
    assert {t.id for t in first} | {t.id for t in second} == {t.id for t in threads}
