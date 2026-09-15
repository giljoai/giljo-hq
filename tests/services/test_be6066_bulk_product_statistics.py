# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
from sqlalchemy import event

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project, Task, VisionDocument
from giljo_mcp.services.product_memory_service import ProductMemoryService
from tests.helpers.test_db_helper import TransactionalTestContext


_STATS_FIELDS = (
    "project_count",
    "unfinished_projects",
    "task_count",
    "unresolved_tasks",
    "vision_documents_count",
    "has_vision",
)


def _add_product(session, tenant_key: str, name: str) -> Product:
    product = Product(id=str(uuid4()), tenant_key=tenant_key, name=name, is_active=False)
    session.add(product)
    return product


def _add_project(session, tenant_key: str, product_id: str, status: str, series_number: int) -> None:
    session.add(
        Project(
            id=str(uuid4()),
            name=f"Project {series_number}",
            description="desc",
            mission="mission",
            status=status,
            product_id=product_id,
            tenant_key=tenant_key,
            series_number=series_number,
        )
    )


def _add_task(session, tenant_key: str, product_id: str, status: str) -> None:
    session.add(
        Task(
            id=str(uuid4()),
            title="Task",
            description="desc",
            tenant_key=tenant_key,
            product_id=product_id,
            status=status,
            priority="medium",
        )
    )


def _add_vision(session, tenant_key: str, product_id: str, name: str = "Vision") -> None:
    session.add(
        VisionDocument(
            id=str(uuid4()),
            product_id=product_id,
            tenant_key=tenant_key,
            document_name=name,
            document_type="vision",
            vision_document="vision content",
            storage_type="inline",
        )
    )


@pytest.mark.asyncio
class TestBulkProductStatistics:

    async def test_bulk_matches_per_product_path_with_soft_deletes(self, db_manager):
        tenant_key = str(uuid4())

        async with TransactionalTestContext(db_manager) as session:
            p1 = _add_product(session, tenant_key, "Product One")
            p2 = _add_product(session, tenant_key, "Product Two")
            p3 = _add_product(session, tenant_key, "Product Three")
            await session.flush()

            series = 1
            for status in (
                ProjectStatus.ACTIVE,
                ProjectStatus.INACTIVE,
                ProjectStatus.INACTIVE,
                ProjectStatus.COMPLETED,
                ProjectStatus.DELETED,
            ):
                _add_project(session, tenant_key, p1.id, status, series)
                series += 1
            for status in ("pending", "pending", "in_progress", "completed", "cancelled"):
                _add_task(session, tenant_key, p1.id, status)
            _add_vision(session, tenant_key, p1.id, "Vision A")
            _add_vision(session, tenant_key, p1.id, "Vision B")

            _add_project(session, tenant_key, p2.id, ProjectStatus.ACTIVE, series)
            series += 1
            _add_task(session, tenant_key, p2.id, "pending")

            await session.flush()

            service = ProductMemoryService(db_manager, tenant_key, test_session=session)
            product_ids = [str(p1.id), str(p2.id), str(p3.id)]

            bulk = await service.get_product_statistics_bulk(product_ids)

            assert set(bulk.keys()) == set(product_ids)

            for pid in product_ids:
                legacy = await service.get_product_statistics(pid)
                for field in _STATS_FIELDS:
                    assert bulk[pid][field] == getattr(legacy, field), (
                        f"mismatch for product {pid} field {field}: "
                        f"bulk={bulk[pid][field]} legacy={getattr(legacy, field)}"
                    )

            assert bulk[str(p1.id)]["project_count"] == 4
            assert bulk[str(p1.id)]["unfinished_projects"] == 3
            assert bulk[str(p1.id)]["task_count"] == 5
            assert bulk[str(p1.id)]["unresolved_tasks"] == 3
            assert bulk[str(p1.id)]["vision_documents_count"] == 2
            assert bulk[str(p1.id)]["has_vision"] is True

            assert bulk[str(p3.id)] == {
                "project_count": 0,
                "unfinished_projects": 0,
                "task_count": 0,
                "unresolved_tasks": 0,
                "vision_documents_count": 0,
                "has_vision": False,
            }

    async def test_bulk_is_o1_in_product_count(self, db_manager):
        tenant_key = str(uuid4())

        async with TransactionalTestContext(db_manager) as session:
            products = [_add_product(session, tenant_key, f"Product {i}") for i in range(3)]
            await session.flush()
            for i, product in enumerate(products):
                _add_project(session, tenant_key, product.id, ProjectStatus.ACTIVE, i + 1)
                _add_task(session, tenant_key, product.id, "pending")
                _add_vision(session, tenant_key, product.id)
            await session.flush()

            service = ProductMemoryService(db_manager, tenant_key, test_session=session)
            ids = [str(p.id) for p in products]

            sync_engine = db_manager.async_engine.sync_engine
            counter = {"n": 0}

            def _count(conn, cursor, statement, parameters, context, executemany):
                counter["n"] += 1

            event.listen(sync_engine, "before_cursor_execute", _count)
            try:
                counter["n"] = 0
                await service.get_product_statistics_bulk(ids[:1])
                one_product_stmts = counter["n"]

                counter["n"] = 0
                await service.get_product_statistics_bulk(ids)
                three_product_stmts = counter["n"]
            finally:
                event.remove(sync_engine, "before_cursor_execute", _count)

            assert one_product_stmts > 0
            assert one_product_stmts == three_product_stmts, (
                "stats query count scales with product count — the per-product "
                f"loop is not fully batched (1 product={one_product_stmts}, "
                f"3 products={three_product_stmts})"
            )
