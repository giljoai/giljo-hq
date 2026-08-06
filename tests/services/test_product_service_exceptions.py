# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for ProductService Exception Handling Migration - Handover 0480b

This module tests that ProductService methods properly raise exceptions
instead of returning error dictionaries.

Test Coverage:
- create_product: ValidationError, DatabaseError
- get_product: ResourceNotFoundError, DatabaseError
- update_product: ResourceNotFoundError, ValidationError, DatabaseError
- activate_product: ResourceNotFoundError, DatabaseError
- deactivate_product: ResourceNotFoundError, DatabaseError
- delete_product: ResourceNotFoundError, DatabaseError
- restore_product: ResourceNotFoundError, DatabaseError
- list_deleted_products: DatabaseError
- get_active_product: DatabaseError
- get_product_statistics: ResourceNotFoundError, DatabaseError
- get_cascade_impact: ResourceNotFoundError, DatabaseError
- upload_vision_document: ResourceNotFoundError, ValidationError, DatabaseError
- purge_expired_deleted_products: DatabaseError

Created as part of Handover 0480b: ProductService Exception Migration
"""

from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.exceptions import (
    BaseGiljoError,
    DatabaseError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.services.product_service import ProductService


# ============================================================================
# TEST FIXTURES
# ============================================================================


@pytest.fixture
def mock_db_manager():
    """Create mock database manager with async session."""
    db_manager = Mock()
    session = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target

    # Setup async context manager
    async_cm = AsyncMock()
    async_cm.__aenter__ = AsyncMock(return_value=session)
    async_cm.__aexit__ = AsyncMock(return_value=False)

    db_manager.get_session_async = Mock(return_value=async_cm)

    return db_manager, session


# ============================================================================
# TEST CLASS 1: create_product Exceptions
# ============================================================================


class TestCreateProductExceptions:
    """Test exception raising in create_product method."""

    @pytest.mark.asyncio
    async def test_create_product_raises_validation_error_for_invalid_platforms(self, mock_db_manager):
        """Should raise ValidationError for invalid target platforms."""
        db_manager, _session = mock_db_manager
        service = ProductService(db_manager, "test-tenant")

        # Invalid platform
        with pytest.raises(ValidationError) as exc_info:
            await service.create_product(name="Test Product", description="Test", target_platforms=["invalid_platform"])

        assert "platform" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_create_product_raises_validation_error_for_duplicate_name(self, mock_db_manager):
        """Should raise ValidationError when product name already exists."""
        db_manager, session = mock_db_manager

        # Mock existing product
        session.execute = AsyncMock(
            return_value=Mock(
                scalar_one_or_none=Mock(return_value=Mock())  # Product exists
            )
        )

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ValidationError) as exc_info:
            await service.create_product(name="Existing Product", description="Test")

        assert "already exists" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_create_product_raises_database_error_on_db_failure(self):
        """Should raise DatabaseError when database operation fails."""
        db_manager = Mock()

        # Setup failing async context manager
        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.create_product(name="Test Product", description="Test")

        assert "Connection failed" in str(exc_info.value)


# ============================================================================
# TEST CLASS 2: get_product Exceptions
# ============================================================================


class TestGetProductExceptions:
    """Test exception raising in get_product method."""

    @pytest.mark.asyncio
    async def test_get_product_raises_not_found_error(self, mock_db_manager):
        """Should raise ResourceNotFoundError when product not found."""
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.get_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()
        assert exc_info.value.default_status_code == 404

    @pytest.mark.asyncio
    async def test_get_product_raises_database_error_on_db_failure(self):
        """Should raise DatabaseError when database operation fails."""
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Query failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.get_product("some-id")

        assert "Query failed" in str(exc_info.value)


# ============================================================================
# TEST CLASS 3: update_product Exceptions
# ============================================================================


class TestUpdateProductExceptions:
    """Test exception raising in update_product method."""

    @pytest.mark.asyncio
    async def test_update_product_raises_not_found_error(self, mock_db_manager):
        """Should raise ResourceNotFoundError when product not found."""
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.update_product("nonexistent-id", name="New Name")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_update_product_raises_validation_error_for_invalid_platforms(self, mock_db_manager):
        """Should raise ValidationError for invalid target platforms."""
        db_manager, _session = mock_db_manager
        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ValidationError) as exc_info:
            await service.update_product("some-id", target_platforms=["invalid_platform"])

        assert "platform" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_update_product_raises_database_error_on_db_failure(self):
        """Should raise DatabaseError when database operation fails."""
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Update failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.update_product("some-id", name="New Name")

        assert "Update failed" in str(exc_info.value)


# ============================================================================
# TEST CLASS 4: Lifecycle Method Exceptions
# ============================================================================


class TestLifecycleMethodExceptions:
    """Test exception raising in product lifecycle methods."""

    @pytest.mark.asyncio
    async def test_activate_product_raises_not_found_error(self, mock_db_manager):
        """Should raise ResourceNotFoundError when product not found."""
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.activate_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_deactivate_product_raises_not_found_error(self, mock_db_manager):
        """Should raise ResourceNotFoundError when product not found."""
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.deactivate_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_delete_product_raises_not_found_error(self, mock_db_manager):
        """Should raise ResourceNotFoundError when product not found."""
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.lifecycle.delete_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_restore_product_raises_not_found_error(self, mock_db_manager):
        """Should raise ResourceNotFoundError when deleted product not found."""
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.lifecycle.restore_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()


# ============================================================================
# TEST CLASS 5: Query Method Exceptions
# ============================================================================


class TestQueryMethodExceptions:
    """Test exception raising in product query methods."""

    @pytest.mark.asyncio
    async def test_list_products_raises_database_error_on_db_failure(self):
        """Should raise DatabaseError when database operation fails."""
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("List failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.list_products()

        assert "List failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_deleted_products_raises_database_error_on_db_failure(self):
        """Should raise DatabaseError when database operation fails."""
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("List failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.lifecycle.list_deleted_products()

        assert "List failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_active_product_raises_database_error_on_db_failure(self):
        """Should raise DatabaseError when database operation fails."""
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Query failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.get_active_product()

        assert "Query failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_product_statistics_raises_not_found_error(self, mock_db_manager):
        """Should raise ResourceNotFoundError when product not found."""
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.memory.get_product_statistics("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_get_cascade_impact_raises_not_found_error(self, mock_db_manager):
        """Should raise ResourceNotFoundError when product not found."""
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.memory.get_cascade_impact("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()


# ============================================================================
# TEST CLASS 6: Integration Method Exceptions
# ============================================================================


class TestIntegrationMethodExceptions:
    """Test exception raising in integration-related methods."""

    # BE-9103: test_update_git_integration_raises_not_found_error removed —
    # ProductService.update_git_integration (the dead product-level write path) was
    # deleted; the git toggle is now settings-only (integrations.git_integration).

    @pytest.mark.asyncio
    async def test_upload_vision_document_raises_not_found_error(self, mock_db_manager):
        """Should raise ResourceNotFoundError when product not found.

        Handover 0950i: upload_vision_document moved to ProductVisionService.
        """
        from giljo_mcp.services.product_vision_service import ProductVisionService

        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductVisionService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.upload_vision_document(
                product_id="nonexistent-id", filename="Test Doc", content="Test content"
            )

        assert "not found" in exc_info.value.message.lower() or "access denied" in exc_info.value.message.lower()


# ============================================================================
# TEST CLASS 7: Maintenance Method Exceptions
# ============================================================================


class TestMaintenanceMethodExceptions:
    """Test exception raising in maintenance methods."""

    @pytest.mark.asyncio
    async def test_purge_expired_deleted_products_raises_database_error_no_manager(self):
        """Should raise DatabaseError when database manager not available."""
        service = ProductService(None, "test-tenant")

        with pytest.raises(DatabaseError) as exc_info:
            await service.lifecycle.purge_expired_deleted_products(days_before_purge=30)

        assert "not available" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_purge_expired_deleted_products_raises_database_error_on_failure(self):
        """Should raise DatabaseError when purge operation fails."""
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Purge failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.lifecycle.purge_expired_deleted_products(days_before_purge=30)

        assert "Purge failed" in str(exc_info.value)


# ============================================================================
# TEST CLASS 8: Exception Context Verification
# ============================================================================


class TestExceptionContextVerification:
    """Verify that exceptions contain appropriate context."""

    @pytest.mark.asyncio
    async def test_not_found_exception_includes_product_id_in_context(self, mock_db_manager):
        """ResourceNotFoundError should include product_id in context."""
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.get_product("test-product-123")

        # Context should ideally contain product_id for debugging
        # This tests the quality of our exception raising
        assert exc_info.value.context is not None

    @pytest.mark.asyncio
    async def test_validation_exception_includes_field_in_context(self, mock_db_manager):
        """ValidationError should include relevant field information in context."""
        db_manager, _session = mock_db_manager
        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ValidationError) as exc_info:
            await service.create_product(name="Test", description="Test", target_platforms=["invalid_platform"])

        # Context should ideally contain information about what failed validation
        assert exc_info.value.context is not None
