# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.models.products import Product
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
class TestMultiTenantIsolation:

    async def test_create_product_tenant_isolation(self, db_manager):
        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        result1 = await service1.create_product(name="Tenant1 Product", description="Product for tenant 1")
        result2 = await service2.create_product(name="Tenant2 Product", description="Product for tenant 2")

        assert isinstance(result1, Product)
        assert isinstance(result2, Product)
        assert result1.id is not None
        assert result2.id is not None

        list1 = await service1.list_products(include_inactive=True)
        assert isinstance(list1, list)
        assert len(list1) == 1
        assert list1[0].name == "Tenant1 Product"

        list2 = await service2.list_products(include_inactive=True)
        assert isinstance(list2, list)
        assert len(list2) == 1
        assert list2[0].name == "Tenant2 Product"

    async def test_get_product_cross_tenant_forbidden(self, db_manager):
        from giljo_mcp.exceptions import ResourceNotFoundError

        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        create_result = await service1.create_product(name="Tenant1 Secret Product")
        product_id = str(create_result.id)

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service2.get_product(product_id)
        assert "not found" in str(exc_info.value).lower()

    async def test_update_product_cross_tenant_forbidden(self, db_manager):
        from giljo_mcp.exceptions import ResourceNotFoundError

        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        create_result = await service1.create_product(name="Protected Product")
        product_id = str(create_result.id)

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service2.update_product(product_id=product_id, name="Hacked Name")
        assert "not found" in str(exc_info.value).lower()

        get_result = await service1.get_product(product_id)
        assert get_result.name == "Protected Product"

    async def test_delete_product_cross_tenant_forbidden(self, db_manager):
        from giljo_mcp.exceptions import ResourceNotFoundError

        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        create_result = await service1.create_product(name="Protected Product")
        product_id = str(create_result.id)

        with pytest.raises(ResourceNotFoundError):
            await service2.lifecycle.delete_product(product_id)

        get_result = await service1.get_product(product_id)
        assert get_result.name == "Protected Product"

    async def test_set_default_product_tenant_isolation(self, db_manager):
        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        create1 = await service1.create_product(name="Tenant1 Product A")
        create2 = await service1.create_product(name="Tenant1 Product B")
        create3 = await service2.create_product(name="Tenant2 Product")

        await service1.set_default_product(str(create1.id))
        await service2.set_default_product(str(create3.id))

        default1 = await service1.get_default_product()
        assert default1 is not None
        assert default1.name == "Tenant1 Product A"

        default2 = await service2.get_default_product()
        assert default2 is not None
        assert default2.name == "Tenant2 Product"

        await service1.set_default_product(str(create2.id))

        default2_check = await service2.get_default_product()
        assert default2_check is not None
        assert default2_check.name == "Tenant2 Product"


@pytest.mark.asyncio
class TestSingleActiveProductConstraint:

    async def test_several_products_can_be_shown_at_once(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create1 = await service.create_product(name="Product A")
        create2 = await service.create_product(name="Product B")
        create3 = await service.create_product(name="Product C")

        assert create1.is_active is True
        assert create2.is_active is True
        assert create3.is_active is True

        activate2 = await service.activate_product(str(create2.id))
        assert activate2.is_active is True

        get_a = await service.get_product(str(create1.id))
        get_b = await service.get_product(str(create2.id))
        get_c = await service.get_product(str(create3.id))
        assert get_a.is_active is True
        assert get_b.is_active is True
        assert get_c.is_active is True

        deactivate1 = await service.deactivate_product(str(create1.id))
        assert deactivate1.is_active is False

        get_a = await service.get_product(str(create1.id))
        get_b = await service.get_product(str(create2.id))
        get_c = await service.get_product(str(create3.id))
        assert get_a.is_active is False
        assert get_b.is_active is True
        assert get_c.is_active is True

    async def test_activate_already_active_product(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(name="Single Product")
        product_id = str(create_result.id)

        activate1 = await service.activate_product(product_id)
        assert activate1.is_active is True

        activate2 = await service.activate_product(product_id)
        assert activate2.is_active is True

    async def test_deactivate_product_no_active_product(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(name="Temporary Active")
        product_id = str(create_result.id)

        await service.activate_product(product_id)
        deactivate_result = await service.deactivate_product(product_id)
        assert deactivate_result.is_active is False

        active = await service.get_default_product()
        assert active is None
