# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for ConsolidatedVisionService.

The service performs aggregate-hash + timestamp bookkeeping only. Per-doc
and aggregate summary text is written by the AI agent via the
``update_product_context`` MCP tool. These tests assert that contract.
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.products import Product, VisionDocument
from giljo_mcp.schemas.service_responses import ConsolidationResult


@pytest.fixture
def mock_db_manager():
    """Mock database manager with async session support."""
    db_manager = MagicMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    db_manager.get_session_async = MagicMock(return_value=session)
    return db_manager, session


def _make_product(docs, *, hash_value=None):
    product = MagicMock(spec=Product)
    product.id = "test-product-id"
    product.tenant_key = "test-tenant"
    product.vision_documents = docs
    product.consolidated_vision_hash = hash_value
    product.consolidated_vision_light = "agent-written light"
    product.consolidated_vision_light_tokens = 3
    product.consolidated_vision_medium = "agent-written medium"
    product.consolidated_vision_medium_tokens = 3
    return product


def _make_doc(name, body, *, is_active=True, display_order=0, deleted_at=None, doc_id=None):
    """Build a spec'd VisionDocument mock for the aggregate builder.

    IMPORTANT: always sets ``deleted_at`` (default None = active). A
    ``MagicMock(spec=VisionDocument)`` auto-vivifies the BE-6130b ``deleted_at``
    column to a truthy child-mock unless it is set explicitly, and
    ``vision_hash._active_sorted_docs`` excludes any doc whose ``deleted_at`` is
    not None — so an unset ``deleted_at`` silently drops the doc from the
    aggregate (the empty-output failure mode these fixtures guard against).
    """
    doc = MagicMock(spec=VisionDocument)
    doc.id = doc_id
    doc.document_name = name
    doc.vision_document = body
    doc.is_active = is_active
    doc.display_order = display_order
    doc.deleted_at = deleted_at
    return doc


@pytest.mark.asyncio
async def test_consolidate_updates_hash_and_timestamp(mock_db_manager):
    """First-run consolidation writes hash+timestamp and returns current summaries."""
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    _db_manager, session = mock_db_manager

    doc = _make_doc("Product Vision", "Body text.", display_order=1, doc_id="doc-1")

    product = _make_product([doc], hash_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = product
    session.execute.return_value = mock_result

    service = ConsolidatedVisionService()
    result = await service.consolidate_vision_documents(
        product_id="test-product-id", session=session, tenant_key="test-tenant", force=False
    )

    assert isinstance(result, ConsolidationResult)
    assert result.hash != ""
    assert result.light.summary == "agent-written light"
    assert result.medium.summary == "agent-written medium"
    assert product.consolidated_vision_hash == result.hash
    assert product.consolidated_at is not None
    # commit goes through self._repo.commit; that call path is exercised
    # indirectly by the absence of any exception above.


@pytest.mark.asyncio
async def test_consolidate_respects_display_order(mock_db_manager):
    """Documents are ordered by display_order in the aggregate text."""
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    _db_manager, _session = mock_db_manager

    doc1 = _make_doc("Chapter 1", "First content", display_order=3)
    doc2 = _make_doc("Chapter 2", "Second content", display_order=1)
    doc3 = _make_doc("Chapter 3", "Third content", display_order=2)

    product = _make_product([doc1, doc2, doc3])

    service = ConsolidatedVisionService()
    aggregate_text, _source_ids, _agg_hash = service._build_aggregate(product)

    pos_ch2 = aggregate_text.index("Chapter 2")
    pos_ch3 = aggregate_text.index("Chapter 3")
    pos_ch1 = aggregate_text.index("Chapter 1")
    assert pos_ch2 < pos_ch3 < pos_ch1


@pytest.mark.asyncio
async def test_consolidate_skips_inactive_docs(mock_db_manager):
    """Inactive documents are excluded from the aggregate."""
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    doc1 = _make_doc("Active Doc 1", "Active content 1", display_order=1)
    doc2 = _make_doc("Inactive Doc", "Inactive content", is_active=False, display_order=2)
    doc3 = _make_doc("Active Doc 2", "Active content 2", display_order=3)

    product = _make_product([doc1, doc2, doc3])

    service = ConsolidatedVisionService()
    aggregate_text, source_ids, _agg_hash = service._build_aggregate(product)

    assert "Active Doc 1" in aggregate_text
    assert "Active Doc 2" in aggregate_text
    assert "Inactive Doc" not in aggregate_text
    assert len(source_ids) == 2


@pytest.mark.asyncio
async def test_consolidate_detects_no_changes(mock_db_manager):
    """Hash unchanged → raises ValidationError(NO_CHANGES) and does NOT commit."""
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    _db_manager, session = mock_db_manager

    doc = _make_doc("Vision", "Unchanged content", display_order=1)

    aggregate_text = f"# {doc.document_name}\n\n{doc.vision_document}"
    expected_hash = hashlib.sha256(aggregate_text.encode("utf-8")).hexdigest()

    product = _make_product([doc], hash_value=expected_hash)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = product
    session.execute.return_value = mock_result

    service = ConsolidatedVisionService()

    with pytest.raises(ValidationError) as exc_info:
        await service.consolidate_vision_documents(
            product_id="test-product-id", session=session, tenant_key="test-tenant", force=False
        )

    assert exc_info.value.error_code == "NO_CHANGES"


@pytest.mark.asyncio
async def test_consolidate_force_updates_even_when_unchanged(mock_db_manager):
    """force=True overrides the hash check and refreshes the timestamp."""
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    _db_manager, session = mock_db_manager

    doc = _make_doc("Vision", "Unchanged content", display_order=1, doc_id="doc-force")

    aggregate_text = f"# {doc.document_name}\n\n{doc.vision_document}"
    expected_hash = hashlib.sha256(aggregate_text.encode("utf-8")).hexdigest()

    product = _make_product([doc], hash_value=expected_hash)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = product
    session.execute.return_value = mock_result

    service = ConsolidatedVisionService()
    result = await service.consolidate_vision_documents(
        product_id="test-product-id", session=session, tenant_key="test-tenant", force=True
    )
    assert isinstance(result, ConsolidationResult)
    assert product.consolidated_at is not None


@pytest.mark.asyncio
async def test_consolidate_handles_product_not_found(mock_db_manager):
    """Non-existent product_id → raises ResourceNotFoundError(PRODUCT_NOT_FOUND)."""
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    _db_manager, session = mock_db_manager

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    service = ConsolidatedVisionService()

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await service.consolidate_vision_documents(
            product_id="nonexistent-id", session=session, tenant_key="test-tenant", force=False
        )

    assert exc_info.value.error_code == "PRODUCT_NOT_FOUND"
    assert "product_id" in exc_info.value.context


@pytest.mark.asyncio
async def test_consolidate_excludes_soft_deleted_sibling(mock_db_manager):
    """BE-6130b regression: a soft-deleted (trashed) doc is excluded from the
    aggregate while its active siblings are included.

    Guards both halves of the bug: (1) the soft-delete read filter in
    vision_hash._active_sorted_docs excludes deleted_at-stamped docs, and (2)
    every fixture mock sets deleted_at — a spec=VisionDocument mock that omits
    it auto-vivifies deleted_at to a truthy child-mock, which would silently
    empty the aggregate.
    """
    from datetime import UTC, datetime

    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    active = _make_doc("Active Vision", "Active body", display_order=1)
    trashed = _make_doc("Trashed Vision", "Trashed body", display_order=2, deleted_at=datetime.now(UTC))

    product = _make_product([active, trashed])

    service = ConsolidatedVisionService()
    aggregate_text, source_ids, agg_hash = service._build_aggregate(product)

    assert "Active Vision" in aggregate_text
    assert "Trashed Vision" not in aggregate_text
    assert len(source_ids) == 1
    assert agg_hash != ""
