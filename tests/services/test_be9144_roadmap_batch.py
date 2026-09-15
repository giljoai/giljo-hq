# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, select

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.roadmaps import RoadmapItem
from giljo_mcp.services.roadmap_service import RoadmapService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


class _StatementCounter:

    def __init__(self, engine):
        self._engine = engine
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(self._engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *exc):
        event.remove(self._engine, "before_cursor_execute", self._on)

    def _on(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def count(self, needle: str) -> int:
        upper = needle.upper()
        return sum(1 for s in self.statements if upper in s.upper())


@pytest_asyncio.fixture
async def seeded(db_session, test_tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"RM {uuid4().hex[:6]}",
        description="be9144 roadmap batch",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    project_ids: list[str] = []
    for idx in range(5):
        project = Project(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            product_id=product.id,
            name=f"P{idx}",
            description="d",
            mission="m",
            series_number=next_series_number(),
            status="inactive",
        )
        db_session.add(project)
        project_ids.append(project.id)
    await db_session.flush()
    return {"product_id": product.id, "project_ids": project_ids}


def _service(db_session):
    return RoadmapService(tenant_manager=TenantManager(), session=db_session)


async def test_upsert_many_items_issues_one_insert(db_session, db_manager, test_tenant_key, seeded):
    svc = _service(db_session)
    items = [
        {"item_type": "project", "project_id": pid, "sort_order": i, "risk": "low"}
        for i, pid in enumerate(seeded["project_ids"])
    ]

    engine = db_manager.async_engine.sync_engine
    with _StatementCounter(engine) as counter:
        result = await svc.upsert_metadata(items=items, tenant_key=test_tenant_key)

    assert counter.count("INSERT INTO roadmap_items") == 1, counter.statements
    assert result["items_upserted"] == 5
    assert result["items_removed"] == 0

    rows = (
        (await db_session.execute(select(RoadmapItem).where(RoadmapItem.tenant_key == test_tenant_key))).scalars().all()
    )
    assert {r.project_id for r in rows} == set(seeded["project_ids"])
    assert {r.sort_order for r in rows} == {0, 1, 2, 3, 4}


async def test_remove_refs_issues_one_delete(db_session, db_manager, test_tenant_key, seeded):
    svc = _service(db_session)
    items = [
        {"item_type": "project", "project_id": pid, "sort_order": i} for i, pid in enumerate(seeded["project_ids"])
    ]
    await svc.upsert_metadata(items=items, tenant_key=test_tenant_key)

    remove = [{"item_type": "project", "project_id": pid} for pid in seeded["project_ids"][:3]]
    engine = db_manager.async_engine.sync_engine
    with _StatementCounter(engine) as counter:
        result = await svc.upsert_metadata(items=[], remove=remove, tenant_key=test_tenant_key)

    assert counter.count("DELETE FROM roadmap_items") == 1, counter.statements
    assert result["items_removed"] == 3

    remaining = (
        (await db_session.execute(select(RoadmapItem).where(RoadmapItem.tenant_key == test_tenant_key))).scalars().all()
    )
    assert {r.project_id for r in remaining} == set(seeded["project_ids"][3:])


async def test_duplicate_items_last_write_wins(db_session, db_manager, test_tenant_key, seeded):
    svc = _service(db_session)
    pid = seeded["project_ids"][0]
    items = [
        {"item_type": "project", "project_id": pid, "sort_order": 1, "risk": "low"},
        {"item_type": "project", "project_id": pid, "sort_order": 9, "risk": "high"},
    ]

    result = await svc.upsert_metadata(items=items, tenant_key=test_tenant_key)

    assert result["items_upserted"] == 2
    rows = (await db_session.execute(select(RoadmapItem).where(RoadmapItem.project_id == pid))).scalars().all()
    assert len(rows) == 1
    assert rows[0].sort_order == 9
    assert rows[0].risk == "high"


async def test_empty_items_and_removes_issue_no_row_statements(db_session, db_manager, test_tenant_key, seeded):
    svc = _service(db_session)

    engine = db_manager.async_engine.sync_engine
    with _StatementCounter(engine) as counter:
        result = await svc.upsert_metadata(items=[], tenant_key=test_tenant_key)

    assert counter.count("INSERT INTO roadmap_items") == 0
    assert counter.count("DELETE FROM roadmap_items") == 0
    assert result["items_upserted"] == 0
    assert result["items_removed"] == 0
