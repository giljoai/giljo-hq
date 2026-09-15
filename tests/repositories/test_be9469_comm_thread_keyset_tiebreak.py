# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    await ensure_default_types_seeded(db_session, tenant)
    repo = CommThreadRepository()
    threads = [await repo.create_thread(db_session, tenant, subject=f"tied {i}") for i in range(count)]
    await db_session.flush()
    return threads


async def _walk(db_session, tenant: str, *, page_size: int, max_pages: int = 20) -> list[str]:
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
    tenant = _tk("tie_precondition")
    with tenant_session_context(db_session, tenant):
        threads = await _seed_tied_threads(db_session, tenant, 5)

    timestamps = {t.created_at for t in threads}
    assert len(timestamps) == 1, (
        f"expected all 5 rows to share one transaction-scoped created_at, got {sorted(timestamps)}"
    )


async def test_paging_a_tied_page_boundary_returns_every_row(db_session):
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
    tenant = _tk("stable_order")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await _seed_tied_threads(db_session, tenant, 6)
        first = [t.id for t in await repo.list_threads(db_session, tenant, limit=6)]
        second = [t.id for t in await repo.list_threads(db_session, tenant, limit=6)]

    assert first == second, f"tied rows came back in two different orders: {first} vs {second}"
    assert first == sorted(first), f"tied rows are not ordered by the id tiebreak: {first}"


async def test_no_cursor_page_is_unchanged_by_the_tiebreak(db_session):
    tenant = _tk("no_cursor")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await _seed_tied_threads(db_session, tenant, 5)
        page = await repo.list_threads(db_session, tenant, limit=3)
        unbounded = await repo.list_threads(db_session, tenant)

    assert len(page) == 3
    assert len(unbounded) == 5




async def test_an_unknown_before_id_is_refused_instead_of_restarting_the_walk(db_session):
    tenant = _tk("unknown_cursor")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await _seed_tied_threads(db_session, tenant, 3)
        with pytest.raises(ValidationError) as exc:
            await repo.list_threads(db_session, tenant, limit=2, before_id="00000000-0000-0000-0000-000000000000")

    message = str(exc.value)
    assert "before_id" in message
    assert "restart" in message.lower()


async def test_a_foreign_tenants_before_id_is_refused_identically(db_session):
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
    tenant = _tk("valid_cursor")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        threads = await _seed_tied_threads(db_session, tenant, 4)
        first = await repo.list_threads(db_session, tenant, limit=2)
        second = await repo.list_threads(db_session, tenant, limit=2, before_id=first[-1].id)

    assert len(second) == 2
    assert {t.id for t in first}.isdisjoint({t.id for t in second})
    assert {t.id for t in first} | {t.id for t in second} == {t.id for t in threads}
