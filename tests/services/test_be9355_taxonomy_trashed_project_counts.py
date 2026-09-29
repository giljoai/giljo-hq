# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    tenant = test_tenant_key
    suffix = uuid4().hex[:2].upper()
    series = count(1)

    with tenant_session_context(db_session, tenant):
        trash_only = _taxonomy_type(tenant, f"T{suffix}", "Trash Only")
        mixed = _taxonomy_type(tenant, f"M{suffix}", "Mixed")
        empty = _taxonomy_type(tenant, f"E{suffix}", "Empty")
        db_session.add_all([trash_only, mixed, empty])
        await db_session.flush()

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
    tenant = taxonomy_with_trashed_projects["tenant"]
    type_id = taxonomy_with_trashed_projects["trash_only_id"]

    with tenant_session_context(db_session, tenant):
        await delete_taxonomy_type(db_session, tenant, type_id)

        remaining = await db_session.scalar(select(TaxonomyType).where(TaxonomyType.id == type_id))
    assert remaining is None, "the taxonomy type was not actually removed"


@pytest.mark.asyncio
async def test_deleting_the_type_leaves_the_trashed_project_recoverable(db_session, taxonomy_with_trashed_projects):
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
    tenant = taxonomy_with_trashed_projects["tenant"]
    type_id = taxonomy_with_trashed_projects["mixed_id"]

    with tenant_session_context(db_session, tenant), pytest.raises(ValueError, match="project"):
        await delete_taxonomy_type(db_session, tenant, type_id)


@pytest.mark.asyncio
async def test_project_count_for_type_counts_only_live_projects(db_session, taxonomy_with_trashed_projects):
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
    tenant = taxonomy_with_trashed_projects["tenant"]

    with tenant_session_context(db_session, tenant):
        labels = {t.label for t in await list_taxonomy_types(db_session, tenant)}

    assert {
        taxonomy_with_trashed_projects["empty_label"],
        taxonomy_with_trashed_projects["trash_only_label"],
        taxonomy_with_trashed_projects["mixed_label"],
    } <= labels, f"a taxonomy type dropped out of the list, got={sorted(labels)}"


@pytest.mark.asyncio
async def test_stale_deleted_at_live_project_still_blocks_type_delete(db_session, test_tenant_key):
    tenant = test_tenant_key
    suffix = uuid4().hex[:3].upper()

    with tenant_session_context(db_session, tenant):
        stale_type = _taxonomy_type(tenant, f"S{suffix}", "Stale")
        db_session.add(stale_type)
        await db_session.flush()

        product = Product(tenant_key=tenant, name=f"be9663 stale product {suffix}", description="d", is_active=False)
        db_session.add(product)
        await db_session.flush()

        stale_project = _typed_project(tenant, stale_type.id, series=1, product_id=product.id)
        stale_project.deleted_at = datetime.now(UTC)
        db_session.add(stale_project)
        await db_session.flush()

        count = await get_project_count_for_type(db_session, tenant, stale_type.id)
        assert count == 1, f"a stale-deleted_at live project must still be counted, got={count}"

        with pytest.raises(ValueError, match="project"):
            await delete_taxonomy_type(db_session, tenant, stale_type.id)


@pytest.mark.asyncio
async def test_stale_deleted_at_live_project_counted_in_list_badge_too(db_session, test_tenant_key):
    tenant = test_tenant_key
    suffix = uuid4().hex[:3].upper()

    with tenant_session_context(db_session, tenant):
        stale_type = _taxonomy_type(tenant, f"L{suffix}", "Stale List")
        db_session.add(stale_type)
        await db_session.flush()

        product = Product(tenant_key=tenant, name=f"be9663 list product {suffix}", description="d", is_active=False)
        db_session.add(product)
        await db_session.flush()

        stale_project = _typed_project(tenant, stale_type.id, series=1, product_id=product.id)
        stale_project.deleted_at = datetime.now(UTC)
        db_session.add(stale_project)
        await db_session.flush()

        types = await list_taxonomy_types(db_session, tenant)

    counts = {t.label: t.project_count for t in types}
    assert counts.get("Stale List") == 1, (
        f"the taxonomy list badge must count a stale-deleted_at live project, got={counts}"
    )
