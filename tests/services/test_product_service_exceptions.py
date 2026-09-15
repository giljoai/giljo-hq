# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.exceptions import (
    BaseGiljoError,
    DatabaseError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.services.product_service import ProductService




@pytest.fixture
def mock_db_manager():
    db_manager = Mock()
    session = AsyncMock()
    session.info = {}

    async_cm = AsyncMock()
    async_cm.__aenter__ = AsyncMock(return_value=session)
    async_cm.__aexit__ = AsyncMock(return_value=False)

    db_manager.get_session_async = Mock(return_value=async_cm)

    return db_manager, session




class TestCreateProductExceptions:

    @pytest.mark.asyncio
    async def test_create_product_raises_validation_error_for_invalid_platforms(self, mock_db_manager):
        db_manager, _session = mock_db_manager
        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ValidationError) as exc_info:
            await service.create_product(name="Test Product", description="Test", target_platforms=["invalid_platform"])

        assert "platform" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_create_product_raises_validation_error_for_duplicate_name(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(
            return_value=Mock(
                scalar_one_or_none=Mock(return_value=Mock())
            )
        )

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ValidationError) as exc_info:
            await service.create_product(name="Existing Product", description="Test")

        assert "already exists" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_create_product_raises_database_error_on_db_failure(self):
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.create_product(name="Test Product", description="Test")

        assert "Connection failed" in str(exc_info.value)




class TestGetProductExceptions:

    @pytest.mark.asyncio
    async def test_get_product_raises_not_found_error(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.get_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()
        assert exc_info.value.default_status_code == 404

    @pytest.mark.asyncio
    async def test_get_product_raises_database_error_on_db_failure(self):
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Query failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.get_product("some-id")

        assert "Query failed" in str(exc_info.value)




class TestUpdateProductExceptions:

    @pytest.mark.asyncio
    async def test_update_product_raises_not_found_error(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.update_product("nonexistent-id", name="New Name")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_update_product_raises_validation_error_for_invalid_platforms(self, mock_db_manager):
        db_manager, _session = mock_db_manager
        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ValidationError) as exc_info:
            await service.update_product("some-id", target_platforms=["invalid_platform"])

        assert "platform" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_update_product_raises_database_error_on_db_failure(self):
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Update failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.update_product("some-id", name="New Name")

        assert "Update failed" in str(exc_info.value)




class TestLifecycleMethodExceptions:

    @pytest.mark.asyncio
    async def test_activate_product_raises_not_found_error(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.activate_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_deactivate_product_raises_not_found_error(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.deactivate_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_delete_product_raises_not_found_error(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.lifecycle.delete_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_restore_product_raises_not_found_error(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.lifecycle.restore_product("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()




class TestQueryMethodExceptions:

    @pytest.mark.asyncio
    async def test_list_products_raises_database_error_on_db_failure(self):
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
    async def test_get_default_product_raises_database_error_on_db_failure(self):
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Query failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.get_default_product()

        assert "Query failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_product_statistics_raises_not_found_error(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.memory.get_product_statistics("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_get_cascade_impact_raises_not_found_error(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.memory.get_cascade_impact("nonexistent-id")

        assert "not found" in exc_info.value.message.lower()




class TestIntegrationMethodExceptions:


    @pytest.mark.asyncio
    async def test_upload_vision_document_raises_not_found_error(self, mock_db_manager):
        from giljo_mcp.services.product_vision_service import ProductVisionService

        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductVisionService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.upload_vision_document(
                product_id="nonexistent-id", filename="Test Doc", content="Test content"
            )

        assert "not found" in exc_info.value.message.lower() or "access denied" in exc_info.value.message.lower()




class TestMaintenanceMethodExceptions:

    @pytest.mark.asyncio
    async def test_purge_expired_deleted_products_raises_database_error_no_manager(self):
        service = ProductService(None, "test-tenant")

        with pytest.raises(DatabaseError) as exc_info:
            await service.lifecycle.purge_expired_deleted_products(days_before_purge=30)

        assert "not available" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_purge_expired_deleted_products_raises_database_error_on_failure(self):
        db_manager = Mock()

        async_cm = AsyncMock()
        async_cm.__aenter__ = AsyncMock(side_effect=Exception("Purge failed"))
        async_cm.__aexit__ = AsyncMock(return_value=False)
        db_manager.get_session_async = Mock(return_value=async_cm)

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.lifecycle.purge_expired_deleted_products(days_before_purge=30)

        assert "Purge failed" in str(exc_info.value)




class TestExceptionContextVerification:

    @pytest.mark.asyncio
    async def test_not_found_exception_includes_product_id_in_context(self, mock_db_manager):
        db_manager, session = mock_db_manager

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.get_product("test-product-123")

        assert exc_info.value.context is not None

    @pytest.mark.asyncio
    async def test_validation_exception_includes_field_in_context(self, mock_db_manager):
        db_manager, _session = mock_db_manager
        service = ProductService(db_manager, "test-tenant")

        with pytest.raises(ValidationError) as exc_info:
            await service.create_product(name="Test", description="Test", target_platforms=["invalid_platform"])

        assert exc_info.value.context is not None
