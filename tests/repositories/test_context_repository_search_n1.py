# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event

from giljo_mcp.models import MCPContextIndex
from giljo_mcp.models.products import Product
from giljo_mcp.repositories.context_repository import ContextRepository


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def seeded_product_with_chunks(db_session, test_tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"Ctx Product {uuid4().hex[:6]}",
        description="BE-6003 N+1 search test",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    for order in range(12):
        db_session.add(
            MCPContextIndex(
                tenant_key=test_tenant_key,
                product_id=product.id,
                content=f"chunk {order} mentions orchestration architecture",
                keywords=["orchestration", "architecture"],
                chunk_order=order,
            )
        )
    await db_session.commit()
    return product


async def test_search_chunks_no_n_plus_one(db_session, db_manager, test_tenant_key, seeded_product_with_chunks):
    repo = ContextRepository(db_manager)

    sync_engine = db_manager.async_engine.sync_engine
    statements: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        results = await repo.search_chunks(
            db_session,
            tenant_key=test_tenant_key,
            product_id=seeded_product_with_chunks.id,
            query="orchestration",
            limit=10,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    assert len(results) == 10, f"expected 10 chunks (limit), got {len(results)}"
    assert len(statements) <= 2, (
        f"BE-6003 N+1 regression: search_chunks issued {len(statements)} round-trips "
        f"for a 10-result search (expected <= 2). Statements: {statements}"
    )


async def test_search_chunks_preserves_fts_rank_order(
    db_session, db_manager, test_tenant_key, seeded_product_with_chunks
):
    repo = ContextRepository(db_manager)

    results = await repo.search_chunks(
        db_session,
        tenant_key=test_tenant_key,
        product_id=seeded_product_with_chunks.id,
        query="orchestration",
        limit=10,
    )

    orders = [chunk.chunk_order for chunk in results]
    assert orders == sorted(orders), f"FTS rank order not preserved: {orders}"
