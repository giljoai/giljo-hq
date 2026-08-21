# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9355 -- a trashed project made its taxonomy type permanently undeletable.

``TaxonomyRepository.get_project_count_for_type`` counted every project row ever
assigned to a type, soft-deleted ones included. It feeds the delete guard in
``taxonomy_ops.delete_taxonomy_type``, which then told the user:

    Cannot delete taxonomy type 'XX': 1 project(s) assigned.
    Reassign or remove them first.

The user could do neither. The project was already removed -- it was sitting in
the trash -- and a trashed project is not reachable in the UI to be reassigned.
The type stayed undeletable for the whole retention window, with the error text
pointing at an action that had already been taken. That is the user-facing half
of this fix; the count-inflation sites next to it merely showed wrong numbers.

The sibling ``list_with_project_counts`` had the same missing predicate and
inflated the ``project_count`` badge on the taxonomy list.

Real database rows throughout: the defect is a missing WHERE clause, and no mock
can observe one.
"""

from datetime import UTC, datetime
from itertools import count
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.services.taxonomy_ops import (
    delete_taxonomy_type,
    get_project_count_for_type,
    list_taxonomy_types,
)


def _typed_project(tenant_key: str, type_id: str, *, series: int, product_id: str, trashed: bool = False) -> Project:
    """A project classified under ``type_id``, optionally already in the trash.

    ``status='deleted'`` alongside ``deleted_at`` is not a contrivance -- it is
    exactly the pair ``ProjectDeletionService.delete_project`` stamps.
    ``product_id`` stays NULL so the single-active-project index does not reject
    the seeded mix.

    ``series`` must come from a per-fixture counter, never a random draw:
    ``uq_project_taxonomy_active`` is NULLS NOT DISTINCT
    (``baseline_v38_unified.py:2052``), so the NULL ``product_id`` and ``subseries``
    compare EQUAL and two live rows of the same type that drew the same number
    collide with an IntegrityError.

    BE-9429: this was true of the SHIPPED index but not of the schema these tests
    actually ran against -- ``models/projects.py`` omitted
    ``postgresql_nulls_not_distinct`` and the pytest schema is built from the
    models, so the collision described above could not occur in CI. The model now
    carries the flag, so the reason this fixture counts is now the reason it says.
    """
    now = datetime.now(UTC)
    return Project(
        tenant_key=tenant_key,
        product_id=product_id,
        name="be9355 project",
        description="seeded for the taxonomy count tests",
        mission="seeded mission",
        status="deleted" if trashed else "active",
        project_type_id=type_id,
        series_number=series,
        deleted_at=now if trashed else None,
    )


def _taxonomy_type(tenant_key: str, abbreviation: str, label: str) -> TaxonomyType:
    return TaxonomyType(
        tenant_key=tenant_key,
        abbreviation=abbreviation,
        label=label,
        color="#607D8B",
        sort_order=0,
    )


@pytest_asyncio.fixture
async def taxonomy_with_trashed_projects(db_session, test_tenant_key):
    """Three types covering the three shapes the count has to tell apart.

    * **trash-only** -- one project, and it is in the trash. The dead-end.
    * **mixed** -- 2 live projects and 1 trashed. The 2-vs-1 asymmetry means an
      inverted predicate returns a different number than the correct one, so no
      assertion here can pass by landing on the wrong side of the boundary.
    * **empty** -- no projects at all. Guards against the count being moved into
      the outer WHERE, which would drop zero-project types off the list entirely.

    Abbreviations are randomised per test: ``uq_taxonomy_type_abbr`` is
    (tenant_key, abbreviation) and each test gets its own tenant, but the tenant's
    default types are seeded elsewhere with fixed abbreviations.
    """
    tenant = test_tenant_key
    suffix = uuid4().hex[:2].upper()
    series = count(1)

    with tenant_session_context(db_session, tenant):
        trash_only = _taxonomy_type(tenant, f"T{suffix}", "Trash Only")
        mixed = _taxonomy_type(tenant, f"M{suffix}", "Mixed")
        empty = _taxonomy_type(tenant, f"E{suffix}", "Empty")
        db_session.add_all([trash_only, mixed, empty])
        await db_session.flush()

        # BE-9437: product_id is NOT NULL. The two LIVE rows get a product each --
        # idx_project_single_active_per_product allows one active project per
        # product. The trashed rows carry status='deleted' and sit outside that
        # index, so they can share.
        product_one = Product(tenant_key=tenant, name=f"be9355 P1 {suffix}", description="d", is_active=False)
        product_two = Product(tenant_key=tenant, name=f"be9355 P2 {suffix}", description="d", is_active=False)
        db_session.add_all([product_one, product_two])
        await db_session.flush()

        db_session.add_all(
            [
                _typed_project(tenant, trash_only.id, series=next(series), product_id=product_one.id, trashed=True),
                _typed_project(tenant, mixed.id, series=next(series), product_id=product_one.id),
                _typed_project(tenant, mixed.id, series=next(series), product_id=product_two.id),
                _typed_project(tenant, mixed.id, series=next(series), product_id=product_two.id, trashed=True),
            ]
        )
        await db_session.flush()

    return {
        "tenant": tenant,
        "trash_only_id": trash_only.id,
        "trash_only_label": "Trash Only",
        "mixed_id": mixed.id,
        "mixed_label": "Mixed",
        "empty_label": "Empty",
    }


@pytest.mark.asyncio
async def test_type_whose_only_project_is_trashed_can_be_deleted(db_session, taxonomy_with_trashed_projects):
    """The dead-end: the guard demanded an action the user had already taken.

    Deleting the type must succeed, because from the user's point of view no
    project is assigned to it any more.
    """
    tenant = taxonomy_with_trashed_projects["tenant"]
    type_id = taxonomy_with_trashed_projects["trash_only_id"]

    with tenant_session_context(db_session, tenant):
        await delete_taxonomy_type(db_session, tenant, type_id)

        remaining = await db_session.scalar(select(TaxonomyType).where(TaxonomyType.id == type_id))
    assert remaining is None, "the taxonomy type was not actually removed"


@pytest.mark.asyncio
async def test_deleting_the_type_leaves_the_trashed_project_recoverable(db_session, taxonomy_with_trashed_projects):
    """End-to-end consequence check: the trashed project must survive, untyped.

    ``projects.project_type_id`` is ``ondelete="SET NULL"``, so removing the type
    detaches the trashed project rather than deleting it or raising an integrity
    error. Restoring it later yields an untyped project -- recoverable, which the
    permanent dead-end was not.
    """
    tenant = taxonomy_with_trashed_projects["tenant"]
    type_id = taxonomy_with_trashed_projects["trash_only_id"]

    with tenant_session_context(db_session, tenant):
        before = await db_session.scalar(
            select(Project).where(Project.tenant_key == tenant, Project.project_type_id == type_id)
        )
        assert before is not None, "fixture guard: the trashed project should exist before the delete"
        project_id = before.id

        await delete_taxonomy_type(db_session, tenant, type_id)
        db_session.expire_all()

        survivor = await db_session.scalar(
            select(Project).where(Project.tenant_key == tenant, Project.id == project_id)
        )
    assert survivor is not None, "deleting the taxonomy type destroyed the trashed project"
    assert survivor.project_type_id is None, (
        f"the trashed project still points at a deleted type, got={survivor.project_type_id}"
    )
    assert survivor.deleted_at is not None, "the project must still be in the trash, not silently restored"


@pytest.mark.asyncio
async def test_type_with_a_live_project_is_still_protected(db_session, taxonomy_with_trashed_projects):
    """Over-exclusion guard: a type in real use must remain undeletable.

    This is the assertion an inverted predicate (``is_not(None)``) fails -- it
    would count 1 trashed project here instead of 2 live ones... and 0 for a type
    whose projects are all live, letting the delete through.
    """
    tenant = taxonomy_with_trashed_projects["tenant"]
    type_id = taxonomy_with_trashed_projects["mixed_id"]

    with tenant_session_context(db_session, tenant), pytest.raises(ValueError, match="project"):
        await delete_taxonomy_type(db_session, tenant, type_id)


@pytest.mark.asyncio
async def test_project_count_for_type_counts_only_live_projects(db_session, taxonomy_with_trashed_projects):
    """The number in the error message and in the update response.

    2 live and 1 trashed: the correct answer (2) differs from both the unfiltered
    answer (3) and the inverted one (1).
    """
    tenant = taxonomy_with_trashed_projects["tenant"]

    with tenant_session_context(db_session, tenant):
        count = await get_project_count_for_type(db_session, tenant, taxonomy_with_trashed_projects["mixed_id"])
        trash_only = await get_project_count_for_type(
            db_session, tenant, taxonomy_with_trashed_projects["trash_only_id"]
        )

    assert count == 2, f"soft-deleted projects are being counted against the type, got={count}"
    assert trash_only == 0, f"a type whose only project is trashed must report 0, got={trash_only}"


@pytest.mark.asyncio
async def test_taxonomy_list_badge_excludes_trashed_projects(db_session, taxonomy_with_trashed_projects):
    """The ``project_count`` badge on the taxonomy list had the same defect."""
    tenant = taxonomy_with_trashed_projects["tenant"]

    with tenant_session_context(db_session, tenant):
        types = await list_taxonomy_types(db_session, tenant)
    counts = {t.label: t.project_count for t in types}

    assert counts.get(taxonomy_with_trashed_projects["mixed_label"]) == 2, (
        f"the taxonomy list badge is counting soft-deleted projects, got={counts}"
    )
    assert counts.get(taxonomy_with_trashed_projects["trash_only_label"]) == 0, (
        f"a type whose only project is trashed must show 0, got={counts}"
    )


@pytest.mark.asyncio
async def test_taxonomy_list_still_lists_types_with_no_live_projects(db_session, taxonomy_with_trashed_projects):
    """A type must never disappear from the list just because its count is 0.

    Pins the predicate to the correlated subquery: moved into the outer WHERE it
    would filter the taxonomy rows themselves, and the empty and trash-only types
    would vanish from the picker instead of showing zero.
    """
    tenant = taxonomy_with_trashed_projects["tenant"]

    with tenant_session_context(db_session, tenant):
        labels = {t.label for t in await list_taxonomy_types(db_session, tenant)}

    assert {
        taxonomy_with_trashed_projects["empty_label"],
        taxonomy_with_trashed_projects["trash_only_label"],
        taxonomy_with_trashed_projects["mixed_label"],
    } <= labels, f"a taxonomy type dropped out of the list, got={sorted(labels)}"
