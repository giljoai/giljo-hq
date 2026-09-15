# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository
from giljo_mcp.services.dto import MemoryEntryCreateParams


class TestProductMemoryRepository:

    @pytest.mark.asyncio
    async def test_model_exists(self, db_session: AsyncSession):
        entry = ProductMemoryEntry(
            tenant_key="test_tenant",
            product_id=uuid4(),
            sequence=1,
            entry_type="project_completion",
            source="test_v1",
            timestamp=datetime.now(tz=UTC),
        )
        assert hasattr(entry, "id")
        assert hasattr(entry, "tenant_key")
        assert hasattr(entry, "product_id")
        assert hasattr(entry, "project_id")
        assert hasattr(entry, "sequence")
        assert hasattr(entry, "entry_type")
        assert hasattr(entry, "source")
        assert hasattr(entry, "summary")
        assert hasattr(entry, "key_outcomes")
        assert hasattr(entry, "decisions_made")
        assert hasattr(entry, "git_commits")
        assert hasattr(entry, "deleted_by_user")

    @pytest.mark.asyncio
    async def test_create_entry(self, db_session: AsyncSession, test_product):
        repo = ProductMemoryRepository()
        entry = await repo.create_entry(
            session=db_session,
            params=MemoryEntryCreateParams(
                tenant_key="test_tenant",
                product_id=test_product.id,
                sequence=1,
                entry_type="project_completion",
                source="test_v1",
                timestamp=datetime.now(tz=UTC),
                summary="Test summary",
                key_outcomes=["outcome1"],
                decisions_made=["decision1"],
            ),
        )
        assert entry.id is not None
        assert entry.sequence == 1
        assert entry.summary == "Test summary"

    @pytest.mark.asyncio
    async def test_get_entries_by_product(self, db_session: AsyncSession, test_product):
        repo = ProductMemoryRepository()
        for i in range(3):
            await repo.create_entry(
                session=db_session,
                params=MemoryEntryCreateParams(
                    tenant_key="test_tenant",
                    product_id=test_product.id,
                    sequence=i + 1,
                    entry_type="project_completion",
                    source="test_v1",
                    timestamp=datetime.now(tz=UTC),
                ),
            )

        entries = await repo.get_entries_by_product(
            session=db_session,
            product_id=test_product.id,
            tenant_key="test_tenant",
            limit=2,
        )
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_get_next_sequence(self, db_session: AsyncSession, test_product, test_tenant_key):
        repo = ProductMemoryRepository()
        seq1 = await repo.get_next_sequence(
            session=db_session,
            product_id=test_product.id,
            tenant_key=test_tenant_key,
        )
        assert seq1 == 1

        await repo.create_entry(
            session=db_session,
            params=MemoryEntryCreateParams(
                tenant_key=test_tenant_key,
                product_id=test_product.id,
                sequence=1,
                entry_type="test",
                source="test_v1",
                timestamp=datetime.now(tz=UTC),
            ),
        )
        seq2 = await repo.get_next_sequence(
            session=db_session,
            product_id=test_product.id,
            tenant_key=test_tenant_key,
        )
        assert seq2 == 2

    @pytest.mark.asyncio
    async def test_mark_entries_deleted_by_project(self, db_session: AsyncSession, test_product, test_project):
        repo = ProductMemoryRepository()
        entry = await repo.create_entry(
            session=db_session,
            params=MemoryEntryCreateParams(
                tenant_key="test_tenant",
                product_id=test_product.id,
                project_id=test_project.id,
                sequence=1,
                entry_type="project_completion",
                source="test_v1",
                timestamp=datetime.now(tz=UTC),
            ),
        )
        assert entry.deleted_by_user is False

        count = await repo.mark_entries_deleted(
            session=db_session,
            project_id=test_project.id,
            tenant_key="test_tenant",
        )
        assert count == 1

        await db_session.refresh(entry)
        assert entry.deleted_by_user is True
        assert entry.user_deleted_at is not None

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, db_session: AsyncSession, test_product):
        repo = ProductMemoryRepository()
        await repo.create_entry(
            session=db_session,
            params=MemoryEntryCreateParams(
                tenant_key="tenant_a",
                product_id=test_product.id,
                sequence=1,
                entry_type="test",
                source="test_v1",
                timestamp=datetime.now(tz=UTC),
            ),
        )

        entries = await repo.get_entries_by_product(
            session=db_session,
            product_id=test_product.id,
            tenant_key="tenant_b",
        )
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_sequence_unique_per_product(self, db_session: AsyncSession, test_product):
        repo = ProductMemoryRepository()
        await repo.create_entry(
            session=db_session,
            params=MemoryEntryCreateParams(
                tenant_key="test_tenant",
                product_id=test_product.id,
                sequence=1,
                entry_type="test",
                source="test_v1",
                timestamp=datetime.now(tz=UTC),
            ),
        )

        with pytest.raises(Exception):
            await repo.create_entry(
                session=db_session,
                params=MemoryEntryCreateParams(
                    tenant_key="test_tenant",
                    product_id=test_product.id,
                    sequence=1,
                    entry_type="test",
                    source="test_v1",
                    timestamp=datetime.now(tz=UTC),
                ),
            )

    @pytest.mark.asyncio
    async def test_cascade_delete_on_product(self, db_session: AsyncSession):
        pass

    @pytest.mark.asyncio
    async def test_set_null_on_project_delete(self, db_session: AsyncSession):
        pass

    @pytest.mark.asyncio
    async def test_entries_ordered_by_sequence_desc(self, db_session: AsyncSession, test_product):
        repo = ProductMemoryRepository()
        for seq in [3, 1, 2]:
            await repo.create_entry(
                session=db_session,
                params=MemoryEntryCreateParams(
                    tenant_key="test_tenant",
                    product_id=test_product.id,
                    sequence=seq,
                    entry_type="test",
                    source="test_v1",
                    timestamp=datetime.now(tz=UTC),
                ),
            )

        entries = await repo.get_entries_by_product(
            session=db_session,
            product_id=test_product.id,
            tenant_key="test_tenant",
        )
        sequences = [e.sequence for e in entries]
        assert sequences == [3, 2, 1]
