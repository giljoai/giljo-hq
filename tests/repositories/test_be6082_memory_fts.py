# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository
from giljo_mcp.services.dto import MemoryEntryCreateParams


async def _make_entry(repo, session, product_id, tenant_key, *, sequence, **content):
    return await repo.create_entry(
        session=session,
        params=MemoryEntryCreateParams(
            tenant_key=tenant_key,
            product_id=product_id,
            sequence=sequence,
            entry_type="project_completion",
            source="test_v1",
            timestamp=datetime.now(tz=UTC),
            **content,
        ),
    )


@pytest.mark.asyncio
class TestMemoryFullTextSearch:

    async def test_tsquery_matches_summary(self, db_session: AsyncSession, test_product, test_tenant_key):
        repo = ProductMemoryRepository()
        await _make_entry(
            repo, db_session, test_product.id, test_tenant_key, sequence=1, summary="Refactored the tenant guard"
        )
        await _make_entry(
            repo, db_session, test_product.id, test_tenant_key, sequence=2, summary="Upgraded the websocket broker"
        )

        entries, total = await repo.get_memory_entries_paginated(
            session=db_session,
            product_id=test_product.id,
            tenant_key=test_tenant_key,
            search_query="tenant",
        )
        assert [e.sequence for e in entries] == [1]
        assert total == 2

    async def test_tsquery_matches_tags(self, db_session: AsyncSession, test_product, test_tenant_key):
        repo = ProductMemoryRepository()
        await _make_entry(
            repo, db_session, test_product.id, test_tenant_key, sequence=1, summary="x", tags=["security", "bug-fix"]
        )
        await _make_entry(
            repo, db_session, test_product.id, test_tenant_key, sequence=2, summary="y", tags=["performance"]
        )

        entries, _ = await repo.get_memory_entries_paginated(
            session=db_session,
            product_id=test_product.id,
            tenant_key=test_tenant_key,
            search_query="security",
        )
        assert [e.sequence for e in entries] == [1]

    async def test_tsquery_matches_outcomes_and_decisions(
        self, db_session: AsyncSession, test_product, test_tenant_key
    ):
        repo = ProductMemoryRepository()
        await _make_entry(
            repo,
            db_session,
            test_product.id,
            test_tenant_key,
            sequence=1,
            summary="x",
            key_outcomes=["Closed the csrf leak"],
        )
        await _make_entry(
            repo,
            db_session,
            test_product.id,
            test_tenant_key,
            sequence=2,
            summary="y",
            decisions_made=["Chose postgres notify"],
        )

        out, _ = await repo.get_memory_entries_paginated(
            session=db_session, product_id=test_product.id, tenant_key=test_tenant_key, search_query="csrf"
        )
        dec, _ = await repo.get_memory_entries_paginated(
            session=db_session, product_id=test_product.id, tenant_key=test_tenant_key, search_query="notify"
        )
        assert [e.sequence for e in out] == [1]
        assert [e.sequence for e in dec] == [2]

    async def test_ilike_fallback_partial_word(self, db_session: AsyncSession, test_product, test_tenant_key):
        repo = ProductMemoryRepository()
        await _make_entry(
            repo, db_session, test_product.id, test_tenant_key, sequence=1, summary="Hardened the tenant guard"
        )

        entries, _ = await repo.get_memory_entries_paginated(
            session=db_session, product_id=test_product.id, tenant_key=test_tenant_key, search_query="tena"
        )
        assert [e.sequence for e in entries] == [1]

    async def test_tenant_isolation(self, db_session: AsyncSession, test_product, test_tenant_key):
        repo = ProductMemoryRepository()
        await _make_entry(
            repo,
            db_session,
            test_product.id,
            "tenant_other",
            sequence=1,
            summary="Secret roadmap for tenant_other",
        )

        entries, total = await repo.get_memory_entries_paginated(
            session=db_session,
            product_id=test_product.id,
            tenant_key=test_tenant_key,
            search_query="roadmap",
        )
        assert entries == []
        assert total == 0

    async def test_pagination_under_search(self, db_session: AsyncSession, test_product, test_tenant_key):
        repo = ProductMemoryRepository()
        for i in range(5):
            await _make_entry(
                repo,
                db_session,
                test_product.id,
                test_tenant_key,
                sequence=i + 1,
                summary=f"shared keyword entry number {i}",
            )

        entries, total = await repo.get_memory_entries_paginated(
            session=db_session,
            product_id=test_product.id,
            tenant_key=test_tenant_key,
            search_query="keyword",
            limit=2,
        )
        assert len(entries) == 2
        assert total == 5

    async def test_no_search_preserves_sequence_ordering(self, db_session: AsyncSession, test_product, test_tenant_key):
        repo = ProductMemoryRepository()
        for seq in (3, 1, 2):
            await _make_entry(repo, db_session, test_product.id, test_tenant_key, sequence=seq, summary=f"entry {seq}")

        entries, _ = await repo.get_memory_entries_paginated(
            session=db_session, product_id=test_product.id, tenant_key=test_tenant_key
        )
        assert [e.sequence for e in entries] == [3, 2, 1]

    async def test_search_perf_smoke_10k(self, db_session: AsyncSession, test_product, test_tenant_key):
        now = datetime.now(tz=UTC)
        needle_seq = 7421
        rows = [
            {
                "id": str(uuid4()),
                "tenant_key": test_tenant_key,
                "product_id": str(test_product.id),
                "sequence": i + 1,
                "entry_type": "project_completion",
                "source": "perf_seed",
                "timestamp": now,
                "summary": (
                    "unique-needle-zxqv appears here once"
                    if i + 1 == needle_seq
                    else f"routine maintenance entry number {i}"
                ),
                "created_at": now,
                "updated_at": now,
            }
            for i in range(10_000)
        ]
        await db_session.execute(insert(ProductMemoryEntry), rows)
        await db_session.flush()

        start = time.perf_counter()
        entries, total = await repo_search(db_session, test_product.id, test_tenant_key, "unique-needle-zxqv")
        elapsed = time.perf_counter() - start

        assert [e.sequence for e in entries] == [needle_seq]
        assert total == 10_000
        assert elapsed < 20.0, f"10k FTS search took {elapsed:.2f}s (coarse smoke bound)"


async def repo_search(session, product_id, tenant_key, term, limit=10):
    return await ProductMemoryRepository().get_memory_entries_paginated(
        session=session, product_id=product_id, tenant_key=tenant_key, search_query=term, limit=limit
    )
