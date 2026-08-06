# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for ProductService reading from product_memory_entries table.

Verifies that services use ProductMemoryRepository for reads instead of JSONB.
Handover 0390b Phase 3.
"""

from datetime import UTC, datetime

import pytest

from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository
from giljo_mcp.services.dto import MemoryEntryCreateParams
from giljo_mcp.services.product_memory_service import ProductMemoryService
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
async def test_product_memory_entries_available_via_repository(db_session, test_tenant_key, test_product):
    """
    Test that memory entries can be fetched via repository and match expected structure.
    This validates the repository interface for service layer integration.
    """
    # Arrange - Create memory entries
    repo = ProductMemoryRepository()

    entries_data = [
        {
            "sequence": 1,
            "entry_type": "project_closeout",
            "source": "close_project_tool",
            "project_name": "Project Alpha",
            "summary": "Completed authentication system",
            "key_outcomes": ["Auth implemented", "Tests passing"],
            "decisions_made": ["Use JWT tokens"],
        },
        {
            "sequence": 2,
            "entry_type": "project_closeout",
            "source": "close_project_tool",
            "project_name": "Project Beta",
            "summary": "Implemented payment processing",
            "key_outcomes": ["Billing integration", "Webhook handling"],
            "decisions_made": ["Use hosted checkout for payments"],
        },
    ]

    for data in entries_data:
        await repo.create_entry(
            session=db_session,
            params=MemoryEntryCreateParams(
                tenant_key=test_tenant_key,
                product_id=test_product.id,
                timestamp=datetime.now(tz=UTC),
                **data,
            ),
        )

    await db_session.commit()

    # Act - Fetch via repository
    entries = await repo.get_entries_by_product(
        session=db_session,
        product_id=test_product.id,
        tenant_key=test_tenant_key,
        include_deleted=False,
    )

    # Assert - Verify structure
    assert len(entries) == 2
    assert entries[0].sequence == 2  # Descending order
    assert entries[1].sequence == 1

    # Verify to_dict() returns compatible structure
    # Note: to_dict() returns "type" (not "entry_type") for backwards compatibility with JSONB format
    entry_dict = entries[0].to_dict()
    assert "sequence" in entry_dict
    assert "type" in entry_dict  # JSONB format compatibility
    assert "project_name" in entry_dict
    assert "summary" in entry_dict
    assert "key_outcomes" in entry_dict
    assert "decisions_made" in entry_dict


@pytest.mark.asyncio
async def test_get_entries_for_context_returns_lightweight_dicts(db_session, test_tenant_key, test_product):
    """
    Test that get_entries_for_context returns lightweight dicts suitable for context injection.
    This is the primary interface services will use for orchestrator context.
    """
    # Arrange
    repo = ProductMemoryRepository()

    for i in range(3):
        await repo.create_entry(
            session=db_session,
            params=MemoryEntryCreateParams(
                tenant_key=test_tenant_key,
                product_id=test_product.id,
                sequence=i + 1,
                entry_type="project_closeout",
                source="test",
                timestamp=datetime.now(tz=UTC),
                project_name=f"Project {i + 1}",
                summary=f"Summary {i + 1}",
                key_outcomes=[f"Outcome {i + 1}"],
            ),
        )

    await db_session.commit()

    # Act - Use context method
    context_entries = await repo.get_entries_for_context(
        session=db_session,
        product_id=test_product.id,
        tenant_key=test_tenant_key,
        limit=5,
    )

    # Assert
    assert len(context_entries) == 3
    assert all(isinstance(e, dict) for e in context_entries)
    assert context_entries[0]["sequence"] == 3  # Descending order


@pytest.mark.asyncio
async def test_repository_respects_include_deleted_flag(db_session, test_tenant_key, test_product):
    """
    Test that repository correctly filters deleted entries.
    """
    # Arrange
    repo = ProductMemoryRepository()

    # Create 2 entries, one with project_id, one without
    # We use an entry WITHOUT project_id first, then mark it as deleted by setting the flag directly
    entry1 = await repo.create_entry(
        session=db_session,
        params=MemoryEntryCreateParams(
            tenant_key=test_tenant_key,
            product_id=test_product.id,
            project_id=None,  # No project_id to avoid FK constraint
            sequence=1,
            entry_type="project_closeout",
            source="test",
            timestamp=datetime.now(tz=UTC),
            summary="Entry 1",
        ),
    )

    await repo.create_entry(
        session=db_session,
        params=MemoryEntryCreateParams(
            tenant_key=test_tenant_key,
            product_id=test_product.id,
            sequence=2,
            entry_type="project_closeout",
            source="test",
            timestamp=datetime.now(tz=UTC),
            summary="Entry 2",
        ),
    )

    await db_session.commit()

    # Mark entry1 as deleted directly (no project_id-based deletion since we don't have a project)
    entry1.deleted_by_user = True
    entry1.user_deleted_at = datetime.now(tz=UTC)
    await db_session.commit()

    # Act - Fetch without deleted
    active_entries = await repo.get_entries_by_product(
        session=db_session,
        product_id=test_product.id,
        tenant_key=test_tenant_key,
        include_deleted=False,
    )

    # Act - Fetch with deleted
    all_entries = await repo.get_entries_by_product(
        session=db_session,
        product_id=test_product.id,
        tenant_key=test_tenant_key,
        include_deleted=True,
    )

    # Assert
    assert len(active_entries) == 1
    assert active_entries[0].sequence == 2

    assert len(all_entries) == 2


# ============================================================================
# BE-9261: product_memory seed key renamed github -> git_integration
# ============================================================================


@pytest.mark.asyncio
async def test_legacy_github_key_still_loads_via_response_builder(
    db_manager, db_session, test_tenant_key, test_product
):
    """A row written before BE-9261 only carries "github". The real reader
    (_build_product_memory_response, called from ProductService.update_product's
    websocket-event path) must still surface that data under git_integration --
    this is the must-leave regression the seed-key rename is coordinated against."""
    test_product.product_memory = {
        "github": {"enabled": True, "commit_limit": 25},
        "context": {},
    }
    await db_session.commit()

    memory_service = ProductMemoryService(db_manager, test_tenant_key, test_session=db_session)
    response = await memory_service._build_product_memory_response(db_session, test_product)

    assert response["git_integration"] == {"enabled": True, "commit_limit": 25}


@pytest.mark.asyncio
async def test_git_integration_key_takes_precedence_over_legacy_github(
    db_manager, db_session, test_tenant_key, test_product
):
    """If a row somehow carries both keys (mid-migration), the canonical
    git_integration key wins over the legacy github fallback."""
    test_product.product_memory = {
        "git_integration": {"enabled": True},
        "github": {"enabled": False, "stale": True},
        "context": {},
    }
    await db_session.commit()

    memory_service = ProductMemoryService(db_manager, test_tenant_key, test_session=db_session)
    response = await memory_service._build_product_memory_response(db_session, test_product)

    assert response["git_integration"] == {"enabled": True}


@pytest.mark.asyncio
async def test_new_product_seeds_git_integration_key(db_manager, db_session, test_tenant_key):
    """New product creation paths write the renamed git_integration seed key,
    not the legacy github key."""
    service = ProductService(db_manager, tenant_key=test_tenant_key, test_session=db_session)

    product = await service.create_product(name="BE-9261 seed check")

    assert product.product_memory["git_integration"] == {}
    assert "github" not in product.product_memory
