# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from uuid import uuid4

import pytest

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.schemas.service_responses import (
    CascadeImpact,
    DeleteResult,
)
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
class TestProductCRUDWorkflows:

    async def test_full_product_lifecycle(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(
            name="Lifecycle Product",
            description="Testing full lifecycle",
            project_path="/projects/lifecycle",
            tech_stack={"programming_languages": "Python"},
        )
        assert isinstance(create_result, Product)
        product_id = str(create_result.id)

        update_result = await service.update_product(
            product_id=product_id,
            description="Updated description",
            tech_stack={"programming_languages": "Python 3.12", "backend_frameworks": "FastAPI"},
            force=True,
        )
        assert update_result.description == "Updated description"

        activate_result = await service.activate_product(product_id)
        assert activate_result.is_active is True

        deactivate_result = await service.deactivate_product(product_id)
        assert deactivate_result.is_active is False

        delete_result = await service.lifecycle.delete_product(product_id)
        assert isinstance(delete_result, DeleteResult)
        assert delete_result.deleted is True
        assert delete_result.deleted_at is not None

        list_result = await service.list_products(include_inactive=True)
        assert len(list_result) == 0

        deleted_list = await service.lifecycle.list_deleted_products()
        assert len(deleted_list) >= 1
        assert any(str(p.id) == product_id for p in deleted_list)

        restore_result = await service.lifecycle.restore_product(product_id)
        assert isinstance(restore_result, Product)

        list_result = await service.list_products(include_inactive=True)
        assert len(list_result) == 1
        assert list_result[0].name == "Lifecycle Product"

    async def test_create_multiple_products_and_list(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        products = []
        for i in range(5):
            result = await service.create_product(name=f"Product {i + 1}", description=f"Description {i + 1}")
            assert isinstance(result, Product)
            products.append(str(result.id))

        list_result = await service.list_products(include_inactive=True)
        assert isinstance(list_result, list)
        assert len(list_result) == 5

        names = [p.name for p in list_result]
        for i in range(5):
            assert f"Product {i + 1}" in names

    async def test_duplicate_name_prevention(self, db_manager):
        from giljo_mcp.exceptions import ValidationError

        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create1 = await service.create_product(name="Unique Product")
        assert isinstance(create1, Product)

        with pytest.raises(ValidationError) as exc_info:
            await service.create_product(name="Unique Product")
        assert "already exists" in str(exc_info.value)

        list_result = await service.list_products(include_inactive=True)
        assert len(list_result) == 1

    async def test_soft_delete_allows_name_reuse(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create1 = await service.create_product(name="Reusable Name")
        assert isinstance(create1, Product)
        product1_id = str(create1.id)

        await service.lifecycle.delete_product(product1_id)

        create2 = await service.create_product(name="Reusable Name")
        assert isinstance(create2, Product)
        assert str(create2.id) != product1_id


@pytest.mark.asyncio
class TestProductProjectCascade:

    async def test_product_with_projects_cascade_impact(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        product_result = await service.create_product(name="Product with Projects")
        product_id = str(product_result.id)

        async with db_manager.get_session_async() as session:
            for i in range(3):
                project = Project(
                    id=str(uuid4()),
                    name=f"Project {i + 1}",
                    description=f"Project {i + 1} description",
                    mission=f"Mission {i + 1}",
                    status="inactive",
                    product_id=product_id,
                    tenant_key=tenant_key,
                    series_number=i + 1,
                )
                session.add(project)
            await session.commit()

        impact_result = await service.memory.get_cascade_impact(product_id)
        assert isinstance(impact_result, CascadeImpact)
        assert impact_result.total_projects == 3

    async def test_delete_product_with_projects(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        product_result = await service.create_product(name="Product to Delete")
        product_id = str(product_result.id)

        async with db_manager.get_session_async() as session:
            project = Project(
                id=str(uuid4()),
                name="Related Project",
                description="Project description",
                mission="Project mission",
                status="inactive",
                product_id=product_id,
                tenant_key=tenant_key,
                series_number=random.randint(1, 9000),
            )
            session.add(project)
            await session.commit()

        delete_result = await service.lifecycle.delete_product(product_id)
        assert isinstance(delete_result, DeleteResult)
        assert delete_result.deleted is True
        assert delete_result.deleted_at is not None

        from giljo_mcp.exceptions import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError):
            await service.get_product(product_id)


    async def test_list_deleted_products_uses_bulk_stats_path(self, db_manager):
        from unittest.mock import MagicMock

        from api.endpoints.products.crud import list_deleted_products

        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        product_result = await service.create_product(name="Deleted-Stats Product")
        product_id = str(product_result.id)

        async with db_manager.get_session_async() as session:
            session.add(
                Project(
                    id=str(uuid4()),
                    name="Child Project",
                    description="child",
                    mission="m",
                    status="inactive",
                    product_id=product_id,
                    tenant_key=tenant_key,
                    series_number=random.randint(1, 9000),
                )
            )
            await session.commit()

        await service.lifecycle.delete_product(product_id)

        responses = await list_deleted_products(current_user=MagicMock(), service=service)

        ours = next((r for r in responses if r.id == product_id), None)
        assert ours is not None, "deleted product missing from list_deleted_products response"

        bulk = await service.memory.get_product_statistics_bulk([product_id])
        assert product_id in bulk, "bulk stats must zero-fill every supplied product_id"
        assert ours.project_count == bulk[product_id]["project_count"]
        assert ours.vision_documents_count == bulk[product_id]["vision_documents_count"]
