# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9469 item 2 -- the NULLS FIRST keyset, measured at the SQL layer.

``list_projects``' completion-oriented read is ordered
``completed_at DESC NULLS FIRST, id ASC`` (BE-9455 Symptom A --
``_project_keyset.completion_recency_order_clauses``, museum-protected and NOT changed
here). That ordering has TWO regions, and a continuation cursor has to know which one it
is standing in:

* inside the NULLs, every row's ``completed_at`` is NULL, so ``id`` alone decides;
* past them, ``(completed_at, id)`` decides.

**A cursor that compares on ``completed_at`` alone cannot express either region**, and
MEASUREMENT showed it fails two different ways rather than the one that was predicted:

* inside the NULLs it cannot be CONSTRUCTED -- SQLAlchemy rejects ``column < None``;
* past the NULLs it compiles and silently drops the whole tie group (2 of 5 rows
  returned, measured).

The first of those refuted the prediction written into this file's first draft -- that a
NULL comparison would be NULL-false and merely return an empty page. It never reaches the
database. That is a stronger result, and it is recorded on the assertion itself rather
than smoothed over. This suite measures both BEFORE the composite comparison is built, so
the design rests on execution results rather than on an argument.

**How the experiment isolates the variable.** Both walks below run the SAME query
construction and import the SAME ordering from production
(``completion_recency_order_clauses``). The ONLY difference is the keyset predicate:
``_naive_keyset_after`` (test-local, the single-column form) versus
``project_keyset_after`` (production). So a difference in the rows collected is
attributable to the predicate and to nothing else.

The naive walks are kept as permanent tests rather than deleted once green. They
reproduce the original failure, so a future change back to a single-column comparison
fails immediately instead of shipping a walk that silently loses rows.

Real Postgres via the rollback-isolated ``db_session`` fixture, no mocks.
Edition Scope: Both.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import ArgumentError

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories._project_keyset import (
    COMPLETION_RECENCY_AXIS,
    CREATED_RECENCY_AXIS,
    completion_recency_order_clauses,
    keyset_axis_for_sort_key,
    project_keyset_after,
)
from giljo_mcp.repositories.project_repository import ProjectRepository


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9469nk_{suffix}"


def _at(day: int) -> datetime:
    return datetime(2026, 7, day, 12, 0, 0, tzinfo=UTC)


async def _seed_board(db_session, tenant: str, *, nulls: int, completed: int) -> tuple[str, list[Project]]:
    """Seed one active product plus ``nulls`` unfinished and ``completed`` finished projects.

    The finished rows all share ONE ``completed_at`` so they form a tie group -- ``id`` is
    the only thing separating them, exactly as inside the NULL region. That is deliberate:
    the boundary and the ties are the two failure modes, and seeding them together means a
    walk cannot pass by getting one of them right.
    """
    product_id = str(uuid.uuid4())
    session = db_session
    session.add(
        Product(
            id=product_id,
            name=f"BE-9469 keyset board {uuid.uuid4().hex[:6]}",
            description="Seeded for the NULLS FIRST keyset reproduction.",
            tenant_key=tenant,
            is_active=True,
            product_memory={},
        )
    )
    rows: list[Project] = []
    for index in range(nulls + completed):
        finished = index >= nulls
        project = Project(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            product_id=product_id,
            name=f"{'finished' if finished else 'unfinished'} {index}",
            description="Seeded for the NULLS FIRST keyset reproduction.",
            mission="Prove the cursor crosses the null boundary without loss.",
            # "inactive", not "active": idx_project_single_active_per_product is a
            # partial unique index on status='active', so a product may hold only ONE
            # active project. The unfinished rows only need completed_at IS NULL, which
            # "inactive" gives without fighting a real constraint.
            status="completed" if finished else "inactive",
            staging_status="staging_complete",
            series_number=index + 1,
            created_at=_at(1 + index),
            # ONE shared timestamp across every finished row -> a real tie group.
            completed_at=_at(20) if finished else None,
        )
        session.add(project)
        rows.append(project)
    await session.flush()
    return product_id, rows


def _base_query(tenant: str, product_id: str):
    """The rows in scope, ordered by the REAL production ordering.

    The ordering is imported, never restated: a copy in a test can agree with production
    today and drift tomorrow, and this whole suite is about a comparison that has to match
    an ORDER BY exactly.
    """
    return (
        select(Project)
        .where(
            Project.tenant_key == tenant,
            Project.product_id == product_id,
            Project.deleted_at.is_(None),
        )
        .order_by(*completion_recency_order_clauses())
    )


def _naive_keyset_after(sort_value: Any, row_id: str) -> Any:
    """The WRONG comparison, kept so its failure can be measured rather than argued.

    A single-column ``completed_at < cursor_value``, the same shape item 1 removed from
    the thread list. It fails in two DIFFERENT ways depending on which region the cursor
    stands in, and the two are measured separately below:

    * **Inside the NULLs it cannot be CONSTRUCTED.** SQLAlchemy refuses
      ``column < None`` outright -- ``ArgumentError: Only '=', '!=', 'is_()', ...
      operators can be used with None/True/False``. So a naive implementation does not
      get as far as a wrong query; it either raises at the first page boundary inside the
      NULL region, or its author adds a "if the value is None, skip the keyset" guard and
      recreates item 1's restart-from-page-one defect one layer up.
    * **Past the NULLs it compiles and silently drops the tie group**, including the tied
      rows the walk has not returned yet -- item 1's failure verbatim.
    """
    del row_id  # the naive form has no tiebreak to use -- that is the defect
    return Project.completed_at < sort_value


async def _walk(db_session, tenant: str, product_id: str, *, page_size: int, keyset, max_pages: int = 30) -> list[str]:
    """Page the board with ``keyset`` and collect the ids seen, in order.

    ``keyset`` takes ``(sort_value, row_id)`` from the last row of the previous page and
    returns the WHERE clause for the next one -- the same shape a real cursor decodes to.
    ``max_pages`` bounds a pathological repeat so a broken keyset shows up as a wrong id
    list rather than as a hung test.
    """
    seen: list[str] = []
    cursor: tuple[Any, str] | None = None
    for _ in range(max_pages):
        query = _base_query(tenant, product_id)
        if cursor is not None:
            query = query.where(keyset(*cursor))
        page = (await db_session.execute(query.limit(page_size))).scalars().all()
        if not page:
            break
        seen.extend(p.id for p in page)
        cursor = (page[-1].completed_at, page[-1].id)
    return seen


async def _ground_truth_order(db_session, tenant: str, product_id: str) -> list[Project]:
    return list((await db_session.execute(_base_query(tenant, product_id))).scalars().all())


# --------------------------------------------------------------------------
# Instrument checks -- these must PASS on both sides of the change.
# --------------------------------------------------------------------------


async def test_the_seeded_board_really_has_a_null_boundary_and_a_tie_group(db_session):
    """Prove the fixture built the shape this suite depends on.

    Without this, a green walk is ambiguous: it could mean the keyset handles the boundary,
    or it could mean the fixture never produced one. This is the same instrument check the
    item-1 suite carries, for the same reason.
    """
    tenant = _tk("precondition")
    with tenant_session_context(db_session, tenant):
        product_id, _ = await _seed_board(db_session, tenant, nulls=3, completed=3)
        ordered = await _ground_truth_order(db_session, tenant, product_id)

    completed_at = [p.completed_at for p in ordered]
    assert completed_at[:3] == [None, None, None], f"the NULLs are not first: {completed_at}"
    assert all(v is not None for v in completed_at[3:]), f"the NULL region is not contiguous: {completed_at}"
    assert len(set(completed_at[3:])) == 1, f"the finished rows are not a tie group: {completed_at[3:]}"
    # id ASC is the tiebreak inside each region, and it must hold in both.
    assert [p.id for p in ordered[:3]] == sorted(p.id for p in ordered[:3])
    assert [p.id for p in ordered[3:]] == sorted(p.id for p in ordered[3:])


async def test_an_uncursored_read_returns_the_whole_board(db_session):
    """The both-sides guard: with no keyset at all, every row comes back.

    If this goes red the fixture or the query is broken and every other result in this
    file is meaningless.
    """
    tenant = _tk("no_keyset")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=3, completed=3)
        ordered = await _ground_truth_order(db_session, tenant, product_id)

    assert {p.id for p in ordered} == {p.id for p in rows}


# --------------------------------------------------------------------------
# The reproduction -- the naive single-column comparison loses rows.
# --------------------------------------------------------------------------


async def test_the_naive_comparison_cannot_even_be_built_inside_the_null_region(db_session):
    """A cursor standing in the NULLs cannot be expressed by a single-column compare at all.

    **This assertion replaces a prediction that measurement refuted, and the correction is
    the point.** The expectation was that ``completed_at < NULL`` would be NULL-false and
    return an empty page, ending the walk after page one. It never gets that far:
    SQLAlchemy rejects ``column < None`` when the clause is CONSTRUCTED --
    ``ArgumentError: Only '=', '!=', 'is_()', 'is_not()', 'is_distinct_from()',
    'is_not_distinct_from()' operators can be used with None/True/False``.

    That is a stronger result than the one predicted. A naive implementation has exactly
    two ways out at the first page boundary inside the NULL region, and both are failures:
    raise on a perfectly ordinary walk, or add "if the cursor value is None, skip the
    keyset" -- which is item 1's tolerate-and-restart defect rebuilt one layer up. Neither
    is a cursor. The region has to be part of the comparison.

    Seeded 3 unfinished + 3 finished, paged 2 at a time: page one is two unfinished rows,
    so the cursor's ``completed_at`` is NULL and the second page is where it breaks.
    """
    tenant = _tk("naive_in_nulls")
    with tenant_session_context(db_session, tenant):
        product_id, _ = await _seed_board(db_session, tenant, nulls=3, completed=3)
        with pytest.raises(ArgumentError) as exc:
            await _walk(db_session, tenant, product_id, page_size=2, keyset=_naive_keyset_after)

    assert "None" in str(exc.value)


async def test_the_naive_comparison_drops_the_tie_group_past_the_boundary(db_session):
    """Even starting PAST the NULLs, the strict single-column compare loses the tie group.

    Seeded 1 unfinished + 4 finished sharing one ``completed_at``, paged 2 at a time. Page
    one is the null row plus the first finished row; the next request compares
    ``completed_at < <that shared timestamp>``, which excludes all four tied rows -- the
    three not yet returned included.
    """
    tenant = _tk("naive_past_boundary")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=1, completed=4)
        seen = await _walk(db_session, tenant, product_id, page_size=2, keyset=_naive_keyset_after)

    expected = {p.id for p in rows}
    assert set(seen) != expected, "the naive comparison unexpectedly returned the whole board"
    assert len(seen) == 2, f"expected the naive walk to lose the tie group, got {len(seen)} of {len(expected)}"


# --------------------------------------------------------------------------
# The acceptance assertions -- the composite comparison walks the whole board.
# --------------------------------------------------------------------------


def _composite_keyset(sort_value: Any, row_id: str) -> Any:
    return project_keyset_after(COMPLETION_RECENCY_AXIS, sort_value, row_id)


async def test_the_composite_comparison_crosses_the_boundary_mid_page(db_session):
    """Boundary inside a page: 3 unfinished + 3 finished at page_size=2.

    Ground-truth order is N,N,N,C,C,C, so the pages are [N,N], [N,C], [C,C] -- the second
    page STRADDLES the boundary, which is where a region-blind comparison goes wrong.
    """
    tenant = _tk("composite_midpage")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=3, completed=3)
        ordered = await _ground_truth_order(db_session, tenant, product_id)
        seen = await _walk(db_session, tenant, product_id, page_size=2, keyset=_composite_keyset)

    # Assert the shape the test claims to exercise, rather than trusting the arithmetic.
    assert ordered[2].completed_at is None and ordered[3].completed_at is not None, (
        "the boundary is not straddled by page two -- this test is not exercising a mid-page crossing"
    )
    assert len(seen) == len(set(seen)), f"the walk returned a duplicate id: {seen}"
    assert set(seen) == {p.id for p in rows}, (
        f"the walk skipped {sorted({p.id for p in rows} - set(seen))} -- {len(seen)} of {len(rows)} rows returned"
    )
    assert seen == [p.id for p in ordered], "the walk returned the board in a different order than an uncursored read"


async def test_the_composite_comparison_crosses_the_boundary_on_the_page_edge(db_session):
    """Boundary exactly on a page edge: 2 unfinished + 4 finished at page_size=2.

    Pages are [N,N], [C,C], [C,C]: the last row of page one is the FINAL null and the
    first row of page two is the FIRST finished row. **This is the case a naive
    implementation passes by luck** -- the cursor never sits mid-region, so an
    off-by-one in the region test does not show up. It is a separate assertion from the
    mid-page crossing precisely because the two fail differently.
    """
    tenant = _tk("composite_pageedge")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=2, completed=4)
        ordered = await _ground_truth_order(db_session, tenant, product_id)
        seen = await _walk(db_session, tenant, product_id, page_size=2, keyset=_composite_keyset)

    assert ordered[1].completed_at is None and ordered[2].completed_at is not None, (
        "the boundary does not fall on the page-one/page-two edge -- this test is not exercising an edge crossing"
    )
    assert len(seen) == len(set(seen)), f"the walk returned a duplicate id: {seen}"
    assert set(seen) == {p.id for p in rows}, (
        f"the walk skipped {sorted({p.id for p in rows} - set(seen))} -- {len(seen)} of {len(rows)} rows returned"
    )
    assert seen == [p.id for p in ordered]


async def test_the_composite_comparison_walks_one_row_at_a_time(db_session):
    """page_size=1 -- every step is a boundary or a tie. The worst case, from item 1's lesson.

    Item 1 measured that the smaller the page, the larger the silent loss: a 1-row page
    lost 80% of the set. So the tightest page is the strongest regression test available
    and it belongs here too.
    """
    tenant = _tk("composite_one_by_one")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=3, completed=4)
        ordered = await _ground_truth_order(db_session, tenant, product_id)
        seen = await _walk(db_session, tenant, product_id, page_size=1, keyset=_composite_keyset)

    assert len(seen) == len(set(seen)), f"the walk returned a duplicate id: {seen}"
    assert set(seen) == {p.id for p in rows}
    assert seen == [p.id for p in ordered]


async def test_the_composite_comparison_walks_a_board_with_no_finished_rows(db_session):
    """All NULLs -- the walk never leaves the first region.

    The degenerate case in one direction. A comparison written only for the crossing can
    fail here by never advancing at all.
    """
    tenant = _tk("composite_all_nulls")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=5, completed=0)
        seen = await _walk(db_session, tenant, product_id, page_size=2, keyset=_composite_keyset)

    assert len(seen) == len(set(seen))
    assert set(seen) == {p.id for p in rows}


async def test_the_composite_comparison_walks_a_board_with_no_unfinished_rows(db_session):
    """All finished, all tied -- the walk never enters the NULL region.

    The degenerate case in the other direction, and the one that is pure tie-break: every
    row shares a ``completed_at``, so ``id`` carries the entire walk.
    """
    tenant = _tk("composite_all_completed")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=0, completed=5)
        seen = await _walk(db_session, tenant, product_id, page_size=2, keyset=_composite_keyset)

    assert len(seen) == len(set(seen))
    assert set(seen) == {p.id for p in rows}


async def test_the_created_recency_axis_keyset_walks_its_own_board(db_session):
    """The OTHER axis: ``created_at DESC, id ASC``, the non-completion fallback.

    ``list_projects`` picks its ordering from the caller's question
    (``_is_completion_oriented``), so a cursor issued against the fallback axis has to work
    too. ``created_at`` is never NULL here, so this is the tie-break case without a
    boundary -- seeded with a real tie so it is not a trivially-ordered set.
    """
    tenant = _tk("created_axis")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=2, completed=2)
        # Collapse every created_at onto one value so id carries the whole walk.
        for row in rows:
            row.created_at = _at(5)
        await db_session.flush()

        query = (
            select(Project)
            .where(
                Project.tenant_key == tenant,
                Project.product_id == product_id,
                Project.deleted_at.is_(None),
            )
            .order_by(Project.created_at.desc(), Project.id.asc())
        )
        seen: list[str] = []
        cursor: tuple[Any, str] | None = None
        for _ in range(30):
            stmt = query
            if cursor is not None:
                stmt = stmt.where(project_keyset_after(CREATED_RECENCY_AXIS, cursor[0], cursor[1]))
            page = (await db_session.execute(stmt.limit(2))).scalars().all()
            if not page:
                break
            seen.extend(p.id for p in page)
            cursor = (page[-1].created_at, page[-1].id)

    assert len(seen) == len(set(seen)), f"the walk returned a duplicate id: {seen}"
    assert set(seen) == {p.id for p in rows}


async def test_an_unknown_axis_is_refused_rather_than_silently_ignored(db_session):
    """A keyset for an axis the builder does not know must raise, not return a match-all.

    A predicate builder that fell through to ``True`` would produce a cursor that pages
    from the start every time -- the item-1 defect rebuilt one layer up.
    """
    del db_session
    with pytest.raises(ValueError) as exc:
        project_keyset_after("not_an_axis", _at(20), str(uuid.uuid4()))
    assert "not_an_axis" in str(exc.value)


def test_the_keyset_and_the_ordering_name_the_same_columns():
    """The comparison and the ORDER BY must agree, and this asserts it on the OBSERVABLE.

    Not a string check on source: it compiles the completion-recency ORDER BY and the
    completion-recency keyset and asserts both mention ``completed_at`` and ``id``. A
    keyset that stopped referencing the tiebreak column would still compile, still return
    rows, and silently skip -- so the agreement is what has to be pinned, not the spelling.
    """
    ordering = " ".join(str(clause) for clause in completion_recency_order_clauses())
    keyset = str(project_keyset_after(COMPLETION_RECENCY_AXIS, _at(20), "an-id"))
    for column in ("completed_at", "id"):
        assert column in ordering, f"the completion-recency ORDER BY stopped naming {column}: {ordering}"
        assert column in keyset, f"the completion-recency keyset stopped naming {column}: {keyset}"
    # NULLS FIRST is the half that makes the two regions exist at all.
    assert "NULLS FIRST" in ordering.upper(), f"the completion-recency ORDER BY lost its NULLS FIRST: {ordering}"


def test_the_composite_keyset_is_not_a_row_value_comparison():
    """Guard the item-1 lesson at this layer too.

    ``(completed_at, id) < (ts, id0)`` is the tempting short spelling and it is wrong: the
    columns sort in OPPOSITE directions, so a row-value form silently means ``id`` DESC.
    Asserted on the compiled SQL, which is the observable -- a row-value comparison
    compiles to a parenthesised tuple compare, an explicit OR does not.
    """
    compiled = str(project_keyset_after(COMPLETION_RECENCY_AXIS, _at(20), "an-id"))
    assert " OR " in compiled.upper(), f"the keyset is not an explicit OR: {compiled}"
    # A cursor standing INSIDE the NULL region has to compare on NULL-ness, not on a
    # value it does not have. If this clause stopped naming IS NULL, the walk would
    # either abandon itself at page one or re-serve the nulls forever.
    inside_nulls = str(project_keyset_after(COMPLETION_RECENCY_AXIS, None, "an-id"))
    assert "IS NULL" in inside_nulls.upper(), f"the in-nulls keyset does not compare on NULL-ness: {inside_nulls}"
    assert "IS NOT NULL" in inside_nulls.upper(), (
        f"the in-nulls keyset cannot reach the finished region: {inside_nulls}"
    )


def test_the_repository_sort_key_and_the_keyset_axis_are_the_same_string():
    """The repository's sort key and the keyset axis MUST be the same value.

    ``keyset_axis_for_sort_key`` maps one to the other by equality, written against the
    AXIS constant because importing the repository's constant into the keyset module would
    be an import cycle. So the two are load-bearing-equal and nothing enforces it in the
    code -- this does. If they ever diverge, the axis resolver raises on the completion
    axis and every completion-oriented walk stops working; asserting it here turns that
    into one failing test instead of a broken feature.
    """
    assert ProjectRepository.COMPLETION_RECENCY_SORT_KEY == COMPLETION_RECENCY_AXIS
    assert keyset_axis_for_sort_key(ProjectRepository.COMPLETION_RECENCY_SORT_KEY) == COMPLETION_RECENCY_AXIS
    assert keyset_axis_for_sort_key(None) == CREATED_RECENCY_AXIS
    # An unsupported ordering must refuse rather than fall through to a match-all.
    with pytest.raises(ValueError) as exc:
        keyset_axis_for_sort_key(ProjectRepository.ROADMAP_SORT_KEY)
    assert ProjectRepository.ROADMAP_SORT_KEY in str(exc.value)
