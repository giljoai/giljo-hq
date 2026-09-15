# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.models import Product, VisionDocument
from giljo_mcp.services.product_memory_service import ProductMemoryService
from tests.helpers.test_db_helper import TransactionalTestContext


def _add_product(session, tenant_key: str, name: str) -> Product:
    product = Product(id=str(uuid4()), tenant_key=tenant_key, name=name, is_active=False)
    session.add(product)
    return product


def _add_vision(
    session,
    tenant_key: str,
    product_id: str,
    name: str,
    *,
    chunked: bool = False,
    chunk_count: int = 0,
    summary_light: str | None = None,
    summary_medium: str | None = None,
) -> None:
    session.add(
        VisionDocument(
            id=str(uuid4()),
            product_id=product_id,
            tenant_key=tenant_key,
            document_name=name,
            document_type="vision",
            vision_document="vision content",
            storage_type="inline",
            chunked=chunked,
            chunk_count=chunk_count,
            summary_light=summary_light,
            summary_medium=summary_medium,
        )
    )


@pytest.mark.asyncio
class TestVisionSummaryBulk:

    async def test_aggregates_mirror_card_semantics_mixed_fixture(self, db_manager):
        tenant_key = str(uuid4())

        async with TransactionalTestContext(db_manager) as session:
            p1 = _add_product(session, tenant_key, "Product One")
            p2 = _add_product(session, tenant_key, "Product Two")
            await session.flush()

            _add_vision(
                session,
                tenant_key,
                p1.id,
                "Doc A",
                chunked=True,
                chunk_count=3,
                summary_light="light",
                summary_medium="medium",
            )
            _add_vision(session, tenant_key, p1.id, "Doc B", chunked=True, chunk_count=2)
            _add_vision(
                session,
                tenant_key,
                p1.id,
                "Doc C",
                summary_light="light",
                summary_medium="medium",
            )
            _add_vision(
                session,
                tenant_key,
                p1.id,
                "Doc D",
                summary_light="light",
                summary_medium="",
            )
            await session.flush()

            service = ProductMemoryService(db_manager, tenant_key, test_session=session)
            summary = await service.get_vision_summary_bulk([str(p1.id), str(p2.id)])

            assert summary[str(p1.id)] == {
                "doc_count": 4,
                "chunked_count": 2,
                "chunk_total": 5,
                "embedded_count": 2,
            }
            assert str(p2.id) not in summary

    async def test_empty_input_returns_empty_dict(self, db_manager):
        tenant_key = str(uuid4())
        async with TransactionalTestContext(db_manager) as session:
            service = ProductMemoryService(db_manager, tenant_key, test_session=session)
            assert await service.get_vision_summary_bulk([]) == {}

    async def test_doc_count_matches_count_vision_documents_bulk(self, db_manager):
        tenant_key = str(uuid4())
        async with TransactionalTestContext(db_manager) as session:
            p1 = _add_product(session, tenant_key, "Product One")
            await session.flush()
            _add_vision(session, tenant_key, p1.id, "Doc A", chunked=True, chunk_count=1)
            _add_vision(session, tenant_key, p1.id, "Doc B")
            await session.flush()

            service = ProductMemoryService(db_manager, tenant_key, test_session=session)
            summary = await service.get_vision_summary_bulk([str(p1.id)])
            stats = await service.get_product_statistics_bulk([str(p1.id)])

            assert summary[str(p1.id)]["doc_count"] == stats[str(p1.id)]["vision_documents_count"] == 2
