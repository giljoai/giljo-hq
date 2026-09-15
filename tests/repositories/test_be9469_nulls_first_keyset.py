# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
            status="completed" if finished else "inactive",
            staging_status="staging_complete",
            series_number=index + 1,
            created_at=_at(1 + index),
            completed_at=_at(20) if finished else None,
        )
        session.add(project)
        rows.append(project)
    await session.flush()
    return product_id, rows


def _base_query(tenant: str, product_id: str):
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
    del row_id
    return Project.completed_at < sort_value


async def _walk(db_session, tenant: str, product_id: str, *, page_size: int, keyset, max_pages: int = 30) -> list[str]:
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




async def test_the_seeded_board_really_has_a_null_boundary_and_a_tie_group(db_session):
    tenant = _tk("precondition")
    with tenant_session_context(db_session, tenant):
        product_id, _ = await _seed_board(db_session, tenant, nulls=3, completed=3)
        ordered = await _ground_truth_order(db_session, tenant, product_id)

    completed_at = [p.completed_at for p in ordered]
    assert completed_at[:3] == [None, None, None], f"the NULLs are not first: {completed_at}"
    assert all(v is not None for v in completed_at[3:]), f"the NULL region is not contiguous: {completed_at}"
    assert len(set(completed_at[3:])) == 1, f"the finished rows are not a tie group: {completed_at[3:]}"
    assert [p.id for p in ordered[:3]] == sorted(p.id for p in ordered[:3])
    assert [p.id for p in ordered[3:]] == sorted(p.id for p in ordered[3:])


async def test_an_uncursored_read_returns_the_whole_board(db_session):
    tenant = _tk("no_keyset")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=3, completed=3)
        ordered = await _ground_truth_order(db_session, tenant, product_id)

    assert {p.id for p in ordered} == {p.id for p in rows}




async def test_the_naive_comparison_cannot_even_be_built_inside_the_null_region(db_session):
    tenant = _tk("naive_in_nulls")
    with tenant_session_context(db_session, tenant):
        product_id, _ = await _seed_board(db_session, tenant, nulls=3, completed=3)
        with pytest.raises(ArgumentError) as exc:
            await _walk(db_session, tenant, product_id, page_size=2, keyset=_naive_keyset_after)

    assert "None" in str(exc.value)


async def test_the_naive_comparison_drops_the_tie_group_past_the_boundary(db_session):
    tenant = _tk("naive_past_boundary")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=1, completed=4)
        seen = await _walk(db_session, tenant, product_id, page_size=2, keyset=_naive_keyset_after)

    expected = {p.id for p in rows}
    assert set(seen) != expected, "the naive comparison unexpectedly returned the whole board"
    assert len(seen) == 2, f"expected the naive walk to lose the tie group, got {len(seen)} of {len(expected)}"




def _composite_keyset(sort_value: Any, row_id: str) -> Any:
    return project_keyset_after(COMPLETION_RECENCY_AXIS, sort_value, row_id)


async def test_the_composite_comparison_crosses_the_boundary_mid_page(db_session):
    tenant = _tk("composite_midpage")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=3, completed=3)
        ordered = await _ground_truth_order(db_session, tenant, product_id)
        seen = await _walk(db_session, tenant, product_id, page_size=2, keyset=_composite_keyset)

    assert ordered[2].completed_at is None and ordered[3].completed_at is not None, (
        "the boundary is not straddled by page two -- this test is not exercising a mid-page crossing"
    )
    assert len(seen) == len(set(seen)), f"the walk returned a duplicate id: {seen}"
    assert set(seen) == {p.id for p in rows}, (
        f"the walk skipped {sorted({p.id for p in rows} - set(seen))} -- {len(seen)} of {len(rows)} rows returned"
    )
    assert seen == [p.id for p in ordered], "the walk returned the board in a different order than an uncursored read"


async def test_the_composite_comparison_crosses_the_boundary_on_the_page_edge(db_session):
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
    tenant = _tk("composite_one_by_one")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=3, completed=4)
        ordered = await _ground_truth_order(db_session, tenant, product_id)
        seen = await _walk(db_session, tenant, product_id, page_size=1, keyset=_composite_keyset)

    assert len(seen) == len(set(seen)), f"the walk returned a duplicate id: {seen}"
    assert set(seen) == {p.id for p in rows}
    assert seen == [p.id for p in ordered]


async def test_the_composite_comparison_walks_a_board_with_no_finished_rows(db_session):
    tenant = _tk("composite_all_nulls")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=5, completed=0)
        seen = await _walk(db_session, tenant, product_id, page_size=2, keyset=_composite_keyset)

    assert len(seen) == len(set(seen))
    assert set(seen) == {p.id for p in rows}


async def test_the_composite_comparison_walks_a_board_with_no_unfinished_rows(db_session):
    tenant = _tk("composite_all_completed")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=0, completed=5)
        seen = await _walk(db_session, tenant, product_id, page_size=2, keyset=_composite_keyset)

    assert len(seen) == len(set(seen))
    assert set(seen) == {p.id for p in rows}


async def test_the_created_recency_axis_keyset_walks_its_own_board(db_session):
    tenant = _tk("created_axis")
    with tenant_session_context(db_session, tenant):
        product_id, rows = await _seed_board(db_session, tenant, nulls=2, completed=2)
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
    del db_session
    with pytest.raises(ValueError) as exc:
        project_keyset_after("not_an_axis", _at(20), str(uuid.uuid4()))
    assert "not_an_axis" in str(exc.value)


def test_the_keyset_and_the_ordering_name_the_same_columns():
    ordering = " ".join(str(clause) for clause in completion_recency_order_clauses())
    keyset = str(project_keyset_after(COMPLETION_RECENCY_AXIS, _at(20), "an-id"))
    for column in ("completed_at", "id"):
        assert column in ordering, f"the completion-recency ORDER BY stopped naming {column}: {ordering}"
        assert column in keyset, f"the completion-recency keyset stopped naming {column}: {keyset}"
    assert "NULLS FIRST" in ordering.upper(), f"the completion-recency ORDER BY lost its NULLS FIRST: {ordering}"


def test_the_composite_keyset_is_not_a_row_value_comparison():
    compiled = str(project_keyset_after(COMPLETION_RECENCY_AXIS, _at(20), "an-id"))
    assert " OR " in compiled.upper(), f"the keyset is not an explicit OR: {compiled}"
    inside_nulls = str(project_keyset_after(COMPLETION_RECENCY_AXIS, None, "an-id"))
    assert "IS NULL" in inside_nulls.upper(), f"the in-nulls keyset does not compare on NULL-ness: {inside_nulls}"
    assert "IS NOT NULL" in inside_nulls.upper(), (
        f"the in-nulls keyset cannot reach the finished region: {inside_nulls}"
    )


def test_the_repository_sort_key_and_the_keyset_axis_are_the_same_string():
    assert ProjectRepository.COMPLETION_RECENCY_SORT_KEY == COMPLETION_RECENCY_AXIS
    assert keyset_axis_for_sort_key(ProjectRepository.COMPLETION_RECENCY_SORT_KEY) == COMPLETION_RECENCY_AXIS
    assert keyset_axis_for_sort_key(None) == CREATED_RECENCY_AXIS
    with pytest.raises(ValueError) as exc:
        keyset_axis_for_sort_key(ProjectRepository.ROADMAP_SORT_KEY)
    assert ProjectRepository.ROADMAP_SORT_KEY in str(exc.value)
