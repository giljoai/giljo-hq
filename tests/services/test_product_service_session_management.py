# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Test ProductService session management to prevent infinite recursion bugs.

This test suite was created following TDD methodology to demonstrate and fix
the infinite recursion bug in ProductService._get_session() (line 86).

Bug: _get_session() calls itself instead of self.db_manager.get_session_async()
Impact: ALL product operations fail with RecursionError
Root Cause: Copy-paste error from refactoring (commit 1fc3ce3, Nov 26, 2025)

Expected Test Results:
- RED (BEFORE FIX): Tests fail with RecursionError
- GREEN (AFTER FIX): Tests pass, verifying correct session management
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
async def test_get_session_without_test_injection():
    """
    Test that _get_session() can create a database session without recursing.

    EXPECTED RESULT (BEFORE FIX): RecursionError: maximum recursion depth exceeded
    EXPECTED RESULT (AFTER FIX): Session created successfully
    """
    # Arrange: Create ProductService with mocked db_manager
    mock_db_manager = MagicMock()
    mock_session = AsyncMock(spec=AsyncSession)

    # Mock the async context manager properly
    mock_db_manager.get_session_async.return_value.__aenter__.return_value = mock_session
    mock_db_manager.get_session_async.return_value.__aexit__.return_value = None

    product_service = ProductService(db_manager=mock_db_manager, tenant_key="tk_test_tenant")

    # Act: Try to get a session (should call db_manager, not itself)
    async with product_service._get_session() as session:
        # Assert: Session should be the one from db_manager
        assert session is mock_session

    # Verify db_manager.get_session_async was called (not infinite recursion)
    mock_db_manager.get_session_async.assert_called_once()


@pytest.mark.asyncio
async def test_get_session_with_test_injection():
    """
    Test that _get_session() uses injected test session when provided.

    This ensures test session injection works correctly (shouldn't recurse either).

    EXPECTED RESULT (BEFORE FIX): Should work (early return bypasses bug)
    EXPECTED RESULT (AFTER FIX): Should still work (no regression)
    """
    # Arrange: Create ProductService with test session injected
    mock_db_manager = MagicMock()
    test_session = AsyncMock(spec=AsyncSession)

    product_service = ProductService(db_manager=mock_db_manager, tenant_key="tk_test_tenant", test_session=test_session)

    # Act: Get session with injection
    async with product_service._get_session() as session:
        # Assert: Should return injected test session
        assert session is test_session

    # Verify db_manager was NOT called (injected session used instead)
    mock_db_manager.get_session_async.assert_not_called()


@pytest.mark.asyncio
async def test_list_products_does_not_recurse():
    """
    Test that list_products() can execute without infinite recursion.

    This tests a real service method that depends on _get_session().

    EXPECTED RESULT (BEFORE FIX): RecursionError in _get_session()
    EXPECTED RESULT (AFTER FIX): Products listed successfully
    """
    # Arrange: Create ProductService with mocked dependencies
    mock_db_manager = MagicMock()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_ws_manager = AsyncMock()

    # Mock session context manager
    mock_db_manager.get_session_async.return_value.__aenter__.return_value = mock_session
    mock_db_manager.get_session_async.return_value.__aexit__.return_value = None

    # Mock session operations
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    product_service = ProductService(
        db_manager=mock_db_manager, tenant_key="tk_test_tenant", websocket_manager=mock_ws_manager
    )

    tenant_key = "tk_test_tenant"

    # Act: Attempt to list products (will hit _get_session())
    try:
        # This should NOT raise RecursionError after fix
        await product_service.list_products(tenant_key)

        # If we get here, _get_session() worked (no infinite recursion)
        success = True
    except RecursionError as e:
        # BEFORE FIX: This will happen
        success = False
        pytest.fail(f"RecursionError detected in list_products: {e}")

    # Assert: Should succeed without recursion
    assert success, "list_products should not cause infinite recursion"

    # Verify db_manager.get_session_async was called
    mock_db_manager.get_session_async.assert_called()


@pytest.mark.asyncio
async def test_multiple_operations_do_not_recurse():
    """
    Test that multiple ProductService operations can execute sequentially.

    This ensures _get_session() works correctly across multiple calls.

    EXPECTED RESULT (BEFORE FIX): First operation fails with RecursionError
    EXPECTED RESULT (AFTER FIX): All operations succeed
    """
    # Arrange: Create ProductService with mocked dependencies
    mock_db_manager = MagicMock()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_ws_manager = AsyncMock()

    # Mock session context manager
    mock_db_manager.get_session_async.return_value.__aenter__.return_value = mock_session
    mock_db_manager.get_session_async.return_value.__aexit__.return_value = None

    # Mock session operations
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None  # No active product
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    product_service = ProductService(
        db_manager=mock_db_manager, tenant_key="tk_test_tenant", websocket_manager=mock_ws_manager
    )

    tenant_key = "tk_test_tenant"

    # Act: Perform multiple operations that each call _get_session()
    try:
        # Operation 1: List products
        await product_service.list_products(tenant_key)

        # Operation 2: Get active product (no tenant_key param - uses self.tenant_key)
        await product_service.get_default_product()

        # Operation 3: List products again
        await product_service.list_products(tenant_key)

        success = True
    except RecursionError as e:
        success = False
        pytest.fail(f"RecursionError detected in multiple operations: {e}")

    # Assert: All operations should succeed
    assert success, "Multiple operations should not cause infinite recursion"

    # Verify _get_session() was called multiple times (once per operation)
    assert mock_db_manager.get_session_async.call_count >= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
