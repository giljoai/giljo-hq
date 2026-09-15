# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.exceptions import BaseGiljoError
from tests.helpers.model_factories import make_product, make_vision_document


@pytest.fixture
def mock_db_manager():
    db_manager = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.info = {}

    @asynccontextmanager
    async def mock_get_session(*_args, **_kwargs):
        yield session

    db_manager.get_session_async = mock_get_session
    return db_manager, session


@pytest.mark.asyncio
async def test_get_default_product_returns_vision_path_without_lazy_load_error(mock_db_manager):
    from giljo_mcp.services.product_service import ProductService

    db_manager, session = mock_db_manager

    mock_vision_doc = make_vision_document(
        is_active=True,
        vision_path="/path/to/vision.md",
        vision_document=None,
    )
    mock_product = make_product(
        id="test-product-id",
        name="Test Product",
        description="A test product",
        tenant_key="test-tenant",
        is_active=True,
        project_path="/path/to/project",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        vision_documents=[mock_vision_doc],
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_product
    session.execute.return_value = mock_result

    service = ProductService(db_manager, tenant_key="test-tenant")

    service._get_product_metrics = AsyncMock(return_value={})

    result = await service.get_default_product()

    assert result is not None
    assert result.id == "test-product-id"
    assert result.name == "Test Product"
    assert result.primary_vision_path == "/path/to/vision.md"


@pytest.mark.asyncio
async def test_get_default_product_no_active_product(mock_db_manager):
    from giljo_mcp.services.product_service import ProductService

    db_manager, session = mock_db_manager

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    service = ProductService(db_manager, tenant_key="test-tenant")

    result = await service.get_default_product()

    assert result is None


@pytest.mark.asyncio
async def test_get_default_product_multi_tenant_isolation(mock_db_manager):
    from giljo_mcp.services.product_service import ProductService

    db_manager, session = mock_db_manager

    service = ProductService(db_manager, tenant_key="tenant-a")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    result = await service.get_default_product()

    assert session.execute.called

    assert result is None


@pytest.mark.asyncio
async def test_get_default_product_handles_exception(mock_db_manager):
    from giljo_mcp.services.product_service import ProductService

    db_manager, session = mock_db_manager

    session.execute.side_effect = Exception("Database connection failed")

    service = ProductService(db_manager, tenant_key="test-tenant")

    with pytest.raises(BaseGiljoError) as exc_info:
        await service.get_default_product()

    assert "Database connection failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_default_product_with_empty_vision_documents(mock_db_manager):
    from giljo_mcp.services.product_service import ProductService

    db_manager, session = mock_db_manager

    mock_product = make_product(
        id="test-product-id",
        name="Test Product",
        description="A test product",
        tenant_key="test-tenant",
        is_active=True,
        project_path="/path/to/project",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        vision_documents=[],
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_product
    session.execute.return_value = mock_result

    service = ProductService(db_manager, tenant_key="test-tenant")
    service._get_product_metrics = AsyncMock(return_value={})

    result = await service.get_default_product()

    assert result.primary_vision_path == ""
