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
from giljo_mcp.schemas.service_responses import ConsolidationResult
from tests.helpers.model_factories import make_product, make_vision_document


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
    return make_product(
        id="test-product-id",
        tenant_key="test-tenant",
        vision_documents=docs,
        consolidated_vision_hash=hash_value,
        consolidated_vision_light="agent-written light",
        consolidated_vision_light_tokens=3,
        consolidated_vision_medium="agent-written medium",
        consolidated_vision_medium_tokens=3,
    )


def _make_doc(name, body, *, is_active=True, display_order=0, deleted_at=None, doc_id=None):
    """Build a real transient VisionDocument for the aggregate builder.

    INF-9417: this was a spec'd VisionDocument mock that had to set ``deleted_at``
    by hand on every call -- a spec'd mock auto-vivifies the BE-6130b
    ``deleted_at`` column to a truthy child, and
    ``vision_hash._active_sorted_docs`` then drops the doc from the aggregate,
    which is the empty-output failure these fixtures were written to guard
    against. A real instance answers ``None`` for an unset nullable column, so
    that hand-pin is no longer load-bearing. ``deleted_at`` remains a parameter
    only because several tests deliberately pass a soft-delete stamp.
    """
    return make_vision_document(
        id=doc_id,
        document_name=name,
        vision_document=body,
        is_active=is_active,
        display_order=display_order,
        deleted_at=deleted_at,
    )


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

    Guards the soft-delete read filter in vision_hash._active_sorted_docs, which
    excludes deleted_at-stamped docs. (This docstring used to guard a second half --
    every fixture pinning deleted_at by hand so a spec'd mock could not auto-vivify
    it truthy. INF-9417 removed the need: the fixtures now build real
    VisionDocument instances, which answer None for an unset nullable column.)
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
