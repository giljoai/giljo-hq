# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
async def test_get_session_without_test_injection():
    mock_db_manager = MagicMock()
    mock_session = AsyncMock(spec=AsyncSession)

    mock_db_manager.get_session_async.return_value.__aenter__.return_value = mock_session
    mock_db_manager.get_session_async.return_value.__aexit__.return_value = None

    product_service = ProductService(db_manager=mock_db_manager, tenant_key="tk_test_tenant")

    async with product_service._get_session() as session:
        assert session is mock_session

    mock_db_manager.get_session_async.assert_called_once()


@pytest.mark.asyncio
async def test_get_session_with_test_injection():
    mock_db_manager = MagicMock()
    test_session = AsyncMock(spec=AsyncSession)

    product_service = ProductService(db_manager=mock_db_manager, tenant_key="tk_test_tenant", test_session=test_session)

    async with product_service._get_session() as session:
        assert session is test_session

    mock_db_manager.get_session_async.assert_not_called()


@pytest.mark.asyncio
async def test_list_products_does_not_recurse():
    mock_db_manager = MagicMock()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_ws_manager = AsyncMock()

    mock_db_manager.get_session_async.return_value.__aenter__.return_value = mock_session
    mock_db_manager.get_session_async.return_value.__aexit__.return_value = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    product_service = ProductService(
        db_manager=mock_db_manager, tenant_key="tk_test_tenant", websocket_manager=mock_ws_manager
    )

    tenant_key = "tk_test_tenant"

    try:
        await product_service.list_products(tenant_key)

        success = True
    except RecursionError as e:
        success = False
        pytest.fail(f"RecursionError detected in list_products: {e}")

    assert success, "list_products should not cause infinite recursion"

    mock_db_manager.get_session_async.assert_called()


@pytest.mark.asyncio
async def test_multiple_operations_do_not_recurse():
    mock_db_manager = MagicMock()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_ws_manager = AsyncMock()

    mock_db_manager.get_session_async.return_value.__aenter__.return_value = mock_session
    mock_db_manager.get_session_async.return_value.__aexit__.return_value = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    product_service = ProductService(
        db_manager=mock_db_manager, tenant_key="tk_test_tenant", websocket_manager=mock_ws_manager
    )

    tenant_key = "tk_test_tenant"

    try:
        await product_service.list_products(tenant_key)

        await product_service.get_default_product()

        await product_service.list_products(tenant_key)

        success = True
    except RecursionError as e:
        success = False
        pytest.fail(f"RecursionError detected in multiple operations: {e}")

    assert success, "Multiple operations should not cause infinite recursion"

    assert mock_db_manager.get_session_async.call_count >= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
