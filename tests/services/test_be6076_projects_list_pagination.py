# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints.projects import router as projects_router
from api.endpoints.projects.dependencies import get_project_service
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.tenant import TenantManager




@pytest_asyncio.fixture(scope="function")
async def seeded_projects(db_session):
    tenant = TenantManager.generate_tenant_key()
    product = Product(
        id=str(uuid.uuid4()),
        name="BE-6076 Product",
        description="seed",
        tenant_key=tenant,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()

    be_type = TaxonomyType(id=str(uuid.uuid4()), tenant_key=tenant, abbreviation="BE", label="Backend")
    db_session.add(be_type)
    await db_session.commit()

    base = datetime(2026, 1, 1, tzinfo=UTC)

    def _proj(name, series, status="inactive", hidden=False, day=1, completed=None):
        return Project(
            id=str(uuid.uuid4()),
            name=name,
            description="d",
            mission="m",
            tenant_key=tenant,
            product_id=product.id,
            status=status,
            hidden=hidden,
            project_type_id=be_type.id,
            series_number=series,
            created_at=base.replace(day=day),
            completed_at=completed,
        )

    rows = [
        _proj("Alpha login", 5001, day=1),
        _proj("Bravo cache", 5002, day=2),
        _proj("Charlie api", 5003, day=3),
        _proj("Delta alpha sync", 5004, day=4),
        _proj("Echo queue", 5005, day=5),
        _proj("Foxtrot ui", 5006, day=6),
        _proj("Hidden ghost", 5007, hidden=True, day=7),
        _proj("Zulu done", 5008, status="completed", day=8, completed=base.replace(day=9)),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    for r in rows:
        await db_session.refresh(r)

    return {"tenant": tenant, "product": product, "type": be_type, "rows": rows}


_REPO = ProjectRepository()

_ACTIVE_STATUSES = ["active", "inactive", "completed", "cancelled", "terminated"]




@pytest.mark.asyncio
async def test_default_path_no_pagination_returns_full_set(db_session, seeded_projects):
    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]

    rows = await _REPO.list_projects(db_session, tenant, include_cancelled=True, product_id=product.id)
    assert len(rows) == 8
    assert {r.name for r in rows} == {
        "Alpha login",
        "Bravo cache",
        "Charlie api",
        "Delta alpha sync",
        "Echo queue",
        "Foxtrot ui",
        "Hidden ghost",
        "Zulu done",
    }




@pytest.mark.asyncio
async def test_pagination_slices_sorted_page(db_session, seeded_projects):
    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]

    page1 = await _REPO.list_projects(
        db_session,
        tenant,
        status=_ACTIVE_STATUSES,
        product_id=product.id,
        sort_key="series_number",
        sort_dir="asc",
        limit=3,
        offset=0,
    )
    page2 = await _REPO.list_projects(
        db_session,
        tenant,
        status=_ACTIVE_STATUSES,
        product_id=product.id,
        sort_key="series_number",
        sort_dir="asc",
        limit=3,
        offset=3,
    )
    assert [r.series_number for r in page1] == [5001, 5002, 5003]
    assert [r.series_number for r in page2] == [5004, 5005, 5006]
    assert not ({r.id for r in page1} & {r.id for r in page2})


@pytest.mark.asyncio
async def test_sort_desc_applied_in_sql(db_session, seeded_projects):
    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]

    rows = await _REPO.list_projects(
        db_session,
        tenant,
        status=_ACTIVE_STATUSES,
        product_id=product.id,
        sort_key="name",
        sort_dir="desc",
    )
    names = [r.name for r in rows]
    assert names == sorted(names, reverse=True), f"rows not SQL-sorted desc: {names}"




async def _seed_roadmap(db_session, tenant, product, ordered_projects):
    from giljo_mcp.models.roadmaps import Roadmap, RoadmapItem

    roadmap = Roadmap(id=str(uuid.uuid4()), tenant_key=tenant, product_id=product.id)
    db_session.add(roadmap)
    await db_session.commit()

    for position, proj in enumerate(ordered_projects):
        db_session.add(
            RoadmapItem(
                id=str(uuid.uuid4()),
                tenant_key=tenant,
                roadmap_id=roadmap.id,
                item_type="project",
                project_id=proj.id,
                sort_order=position,
            )
        )
    await db_session.commit()
    return roadmap


@pytest.mark.asyncio
async def test_roadmap_sort_matches_roadmap_item_order(db_session, seeded_projects):
    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]
    rows = seeded_projects["rows"]

    roadmap_order = [rows[3], rows[0], rows[5], rows[2]]
    await _seed_roadmap(db_session, tenant, product, roadmap_order)

    page = await _REPO.list_projects(
        db_session,
        tenant,
        status=_ACTIVE_STATUSES,
        product_id=product.id,
        hidden=False,
        sort_key="roadmap",
        sort_dir="asc",
    )

    on_roadmap_ids = {p.id for p in roadmap_order}
    leading = [r for r in page if r.id in on_roadmap_ids]
    assert [r.id for r in leading] == [p.id for p in roadmap_order]
    assert [r.name for r in leading] == [
        "Delta alpha sync",
        "Alpha login",
        "Foxtrot ui",
        "Charlie api",
    ]


@pytest.mark.asyncio
async def test_roadmap_sort_places_off_roadmap_projects_last(db_session, seeded_projects):
    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]
    rows = seeded_projects["rows"]

    on_roadmap = [rows[2], rows[0]]
    await _seed_roadmap(db_session, tenant, product, on_roadmap)
    on_roadmap_ids = {p.id for p in on_roadmap}

    page = await _REPO.list_projects(
        db_session,
        tenant,
        status=_ACTIVE_STATUSES,
        product_id=product.id,
        hidden=False,
        sort_key="roadmap",
        sort_dir="asc",
    )

    assert [r.id for r in page[: len(on_roadmap)]] == [p.id for p in on_roadmap]
    assert all(r.id not in on_roadmap_ids for r in page[len(on_roadmap) :])
    assert len(page) == 7


@pytest.mark.asyncio
async def test_roadmap_sort_is_tenant_scoped(db_session, seeded_projects):
    from giljo_mcp.models.roadmaps import Roadmap, RoadmapItem

    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]
    rows = seeded_projects["rows"]

    other_tenant = TenantManager.generate_tenant_key()
    other_product = Product(
        id=str(uuid.uuid4()),
        name="Foreign Product",
        description="x",
        tenant_key=other_tenant,
        is_active=True,
    )
    db_session.add(other_product)
    await db_session.commit()
    other_roadmap = Roadmap(id=str(uuid.uuid4()), tenant_key=other_tenant, product_id=other_product.id)
    db_session.add(other_roadmap)
    await db_session.commit()
    db_session.add(
        RoadmapItem(
            id=str(uuid.uuid4()),
            tenant_key=other_tenant,
            roadmap_id=other_roadmap.id,
            item_type="project",
            project_id=rows[0].id,
            sort_order=0,
        )
    )
    await db_session.commit()

    our_roadmap = Roadmap(id=str(uuid.uuid4()), tenant_key=tenant, product_id=product.id)
    db_session.add(our_roadmap)
    await db_session.commit()
    db_session.add(
        RoadmapItem(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            roadmap_id=our_roadmap.id,
            item_type="project",
            project_id=rows[4].id,
            sort_order=5,
        )
    )
    await db_session.commit()

    with tenant_session_context(db_session, tenant):
        page = await _REPO.list_projects(
            db_session,
            tenant,
            status=_ACTIVE_STATUSES,
            product_id=product.id,
            hidden=False,
            sort_key="roadmap",
            sort_dir="asc",
        )
    assert page[0].id == rows[4].id




@pytest.mark.asyncio
async def test_count_reflects_search_not_unfiltered(db_session, seeded_projects):
    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]

    total = await _REPO.count_projects(
        db_session, tenant, status=_ACTIVE_STATUSES, product_id=product.id, search="alpha"
    )
    assert total == 2, "count must reflect the search filter, not the full set"

    page = await _REPO.list_projects(
        db_session,
        tenant,
        status=_ACTIVE_STATUSES,
        product_id=product.id,
        search="alpha",
        sort_key="series_number",
        sort_dir="asc",
        limit=10,
        offset=0,
    )
    assert {r.name for r in page} == {"Alpha login", "Delta alpha sync"}
    assert len(page) == total, "page rows must agree with the filtered count"


@pytest.mark.asyncio
async def test_search_matches_taxonomy_alias(db_session, seeded_projects):
    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]

    rows = await _REPO.list_projects(
        db_session, tenant, status=_ACTIVE_STATUSES, product_id=product.id, search="BE-5004"
    )
    assert {r.name for r in rows} == {"Delta alpha sync"}


@pytest.mark.asyncio
async def test_count_reflects_hidden_filter(db_session, seeded_projects):
    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]

    visible = await _REPO.count_projects(
        db_session, tenant, status=_ACTIVE_STATUSES, product_id=product.id, hidden=False
    )
    only_hidden = await _REPO.count_projects(
        db_session, tenant, status=_ACTIVE_STATUSES, product_id=product.id, hidden=True
    )
    assert visible == 7
    assert only_hidden == 1


@pytest.mark.asyncio
async def test_count_matches_page_total_across_pages(db_session, seeded_projects):
    tenant = seeded_projects["tenant"]
    product = seeded_projects["product"]

    total = await _REPO.count_projects(db_session, tenant, status=_ACTIVE_STATUSES, product_id=product.id, hidden=False)
    collected = []
    offset = 0
    while True:
        page = await _REPO.list_projects(
            db_session,
            tenant,
            status=_ACTIVE_STATUSES,
            product_id=product.id,
            hidden=False,
            sort_key="series_number",
            sort_dir="asc",
            limit=2,
            offset=offset,
        )
        if not page:
            break
        collected.extend(page)
        offset += 2
    assert len(collected) == total
    assert len({r.id for r in collected}) == total, "no duplicate rows across pages"




_FAKE_TENANT = "tenant-be6076"


class _FakeUser:
    id = "user-be6076"
    username = "be6076_tester"
    tenant_key = _FAKE_TENANT


class _StubProjectService:

    def __init__(self, items):
        self._items = items
        self.list_calls: list[dict] = []
        self.count_calls: list[dict] = []

    async def list_projects(self, **kwargs):
        self.list_calls.append(kwargs)
        return list(self._items)

    async def count_projects(self, **kwargs):
        self.count_calls.append(kwargs)
        return 137


def _item(name="P", status="active"):
    from giljo_mcp.schemas.service_responses import ProjectListItem

    now = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    return ProjectListItem(
        id=str(uuid.uuid4()),
        name=name,
        mission="",
        description="",
        status=status,
        staging_status=None,
        tenant_key=_FAKE_TENANT,
        product_id="prod-1",
        created_at=now,
        updated_at=now,
        completed_at=None,
        execution_mode=None,
        project_type_id=None,
        project_type=None,
        series_number=1,
        subseries=None,
        taxonomy_alias="abc123",
        hidden=False,
    )


def _build_app(stub: _StubProjectService) -> FastAPI:
    app = FastAPI()
    app.include_router(projects_router)

    async def _override_user() -> _FakeUser:
        return _FakeUser()

    async def _override_service() -> AsyncIterator[_StubProjectService]:
        yield stub

    app.dependency_overrides[get_current_active_user] = _override_user
    app.dependency_overrides[get_project_service] = _override_service
    return app


@pytest.mark.asyncio
async def test_endpoint_default_path_body_is_bare_list_and_header_is_len():
    stub = _StubProjectService([_item("A"), _item("B")])
    app = _build_app(stub)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list) and len(body) == 2
    assert resp.headers["X-Total-Count"] == "2"
    assert stub.count_calls == [], "default path must not run the extra COUNT query"


@pytest.mark.asyncio
async def test_endpoint_paginated_path_uses_filtered_count_header():
    stub = _StubProjectService([_item("A")])
    app = _build_app(stub)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/projects/",
            params={
                "limit": 10,
                "offset": 0,
                "search": "alpha",
                "statuses": ["active", "inactive"],
                "sort": "series_number",
                "sort_dir": "desc",
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.headers["X-Total-Count"] == "137", "paginated total must come from count_projects"

    list_kwargs = stub.list_calls[-1]
    assert list_kwargs["search"] == "alpha"
    assert list_kwargs["status"] == ["active", "inactive"]
    assert list_kwargs["limit"] == 10
    assert list_kwargs["sort_key"] == "series_number"
    assert list_kwargs["sort_dir"] == "desc"
    count_kwargs = stub.count_calls[-1]
    assert count_kwargs["search"] == "alpha"
    assert count_kwargs["status"] == ["active", "inactive"]
    assert "limit" not in count_kwargs and "sort_key" not in count_kwargs
