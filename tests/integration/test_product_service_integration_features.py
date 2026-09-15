# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.products import Product, VisionDocument
from giljo_mcp.schemas.service_responses import (
    ProductStatistics,
    VisionUploadResult,
)
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.product_vision_service import ProductVisionService


@pytest.mark.asyncio
class TestProductStatisticsIntegration:

    async def test_get_product_statistics_with_data(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        product_result = await service.create_product(name="Stats Product")
        product_id = str(product_result.id)

        stats_result = await service.memory.get_product_statistics(product_id)
        assert isinstance(stats_result, ProductStatistics)
        assert stats_result.project_count >= 0
        assert stats_result.vision_documents_count >= 0
        assert stats_result.product_id == product_id

    async def test_get_product_with_metrics_flag(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        product_result = await service.create_product(name="Metrics Product")
        product_id = str(product_result.id)

        get_result = await service.get_product(product_id)
        assert isinstance(get_result, Product)
        assert get_result.name == "Metrics Product"

    async def test_list_products_with_metrics(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        await service.create_product(name="Product A")
        await service.create_product(name="Product B")

        list_result = await service.list_products(include_inactive=True)
        assert isinstance(list_result, list)
        assert len(list_result) == 2

        for product in list_result:
            assert isinstance(product, Product)
            assert product.id is not None
            assert product.name is not None


@pytest.mark.asyncio
class TestConfigDataPersistence:

    async def test_config_data_creates_normalized_relations(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(
            name="Config Test Product",
            tech_stack={
                "programming_languages": "Python 3.12",
                "backend_frameworks": "FastAPI",
            },
            architecture={
                "primary_pattern": "Layered",
                "api_style": "REST",
            },
            core_features="Agent orchestration",
        )
        product_id = str(create_result.id)

        get_result = await service.get_product(product_id)
        assert get_result.tech_stack is not None
        assert get_result.tech_stack.programming_languages == "Python 3.12"
        assert get_result.architecture is not None
        assert get_result.architecture.primary_pattern == "Layered"
        assert get_result.core_features == "Agent orchestration"

    async def test_config_data_survives_non_config_updates(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(
            name="Config Persist Product",
            tech_stack={"programming_languages": "Python 3.12"},
        )
        product_id = str(create_result.id)

        await service.update_product(product_id=product_id, description="Updated description")

        get_result = await service.get_product(product_id)
        assert get_result.tech_stack is not None
        assert get_result.tech_stack.programming_languages == "Python 3.12"

    async def test_config_data_update_modifies_relations(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(
            name="Config Update Product",
            tech_stack={"programming_languages": "Python 3.11"},
        )
        product_id = str(create_result.id)

        update_result = await service.update_product(
            product_id=product_id,
            tech_stack={"programming_languages": "Python 3.12", "backend_frameworks": "FastAPI"},
            force=True,
        )
        assert isinstance(update_result, Product)

        get_result = await service.get_product(product_id)
        assert get_result.tech_stack.programming_languages == "Python 3.12"
        assert get_result.tech_stack.backend_frameworks == "FastAPI"


@pytest.mark.asyncio
class TestVisionDocumentIntegration:

    async def test_upload_vision_document_integration(self, db_manager):
        tenant_key = str(uuid4())
        product_service = ProductService(db_manager, tenant_key)
        vision_service = ProductVisionService(db_manager, tenant_key)

        product_result = await product_service.create_product(name="Vision Product")
        product_id = str(product_result.id)

        upload_result = await vision_service.upload_vision_document(
            product_id=product_id,
            content="# Product Vision\n\nThis is our product vision statement.",
            filename="product_vision.md",
        )

        assert isinstance(upload_result, VisionUploadResult)
        assert upload_result.document_id is not None

        async with db_manager.get_session_async() as session:
            from sqlalchemy import select

            from giljo_mcp.database import tenant_session_context

            with tenant_session_context(session, tenant_key):
                stmt = select(VisionDocument).where(
                    VisionDocument.product_id == product_id,
                    VisionDocument.tenant_key == tenant_key,
                )
                result = await session.execute(stmt)
                vision_docs = result.scalars().all()
            assert len(vision_docs) >= 1

    async def test_upload_vision_to_nonexistent_product(self, db_manager):
        from giljo_mcp.exceptions import ResourceNotFoundError

        tenant_key = str(uuid4())
        service = ProductVisionService(db_manager, tenant_key)

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.upload_vision_document(product_id=str(uuid4()), content="# Vision", filename="vision.md")
        assert "not found" in str(exc_info.value).lower()


@pytest.mark.asyncio
class TestDatabaseTransactions:

    async def test_create_product_transaction_commit(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(name="Transaction Test")
        product_id = str(create_result.id)

        async with db_manager.get_session_async() as session:
            from sqlalchemy import select

            with tenant_session_context(session, tenant_key):
                stmt = select(Product).where(Product.id == product_id)
                result = await session.execute(stmt)
                product = result.scalar_one_or_none()
            assert product is not None
            assert product.name == "Transaction Test"

    async def test_update_product_transaction_commit(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(name="Original Name")
        product_id = str(create_result.id)

        await service.update_product(product_id=product_id, name="Updated Name")

        async with db_manager.get_session_async() as session:
            from sqlalchemy import select

            with tenant_session_context(session, tenant_key):
                stmt = select(Product).where(Product.id == product_id)
                result = await session.execute(stmt)
                product = result.scalar_one_or_none()
            assert product.name == "Updated Name"

    async def test_delete_product_transaction_commit(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(name="To Delete")
        product_id = str(create_result.id)
        await service.lifecycle.delete_product(product_id)

        async with db_manager.get_session_async() as session:
            from sqlalchemy import select

            with tenant_session_context(session, tenant_key):
                stmt = select(Product).where(Product.id == product_id)
                result = await session.execute(stmt)
                product = result.scalar_one_or_none()
            assert product is not None
            assert product.deleted_at is not None
