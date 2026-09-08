# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Integration tests for ProductService — multi-tenant isolation and active product constraints.

Split from test_product_service_integration.py (Handover 0603, updated 0731b).

These tests verify:
- Multi-tenant isolation (zero cross-tenant leakage)
- Single active product constraint (database-level)
"""

from uuid import uuid4

import pytest

from giljo_mcp.models.products import Product
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
class TestMultiTenantIsolation:
    """Integration tests for multi-tenant isolation"""

    async def test_create_product_tenant_isolation(self, db_manager):
        """Test that products are isolated by tenant"""
        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        # Create products in different tenants (0731b: returns Product ORM model)
        result1 = await service1.create_product(name="Tenant1 Product", description="Product for tenant 1")
        result2 = await service2.create_product(name="Tenant2 Product", description="Product for tenant 2")

        # Verify creation returned Product ORM models
        assert isinstance(result1, Product)
        assert isinstance(result2, Product)
        assert result1.id is not None
        assert result2.id is not None

        # Verify tenant1 can only see their product (0731b: returns list[Product])
        list1 = await service1.list_products(include_inactive=True)
        assert isinstance(list1, list)
        assert len(list1) == 1
        assert list1[0].name == "Tenant1 Product"

        # Verify tenant2 can only see their product
        list2 = await service2.list_products(include_inactive=True)
        assert isinstance(list2, list)
        assert len(list2) == 1
        assert list2[0].name == "Tenant2 Product"

    async def test_get_product_cross_tenant_forbidden(self, db_manager):
        """Test that tenant cannot access another tenant's product"""
        from giljo_mcp.exceptions import ResourceNotFoundError

        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        # Create product in tenant1 (0731b: returns Product ORM model)
        create_result = await service1.create_product(name="Tenant1 Secret Product")
        product_id = str(create_result.id)

        # Try to access from tenant2 - should raise exception
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service2.get_product(product_id)
        assert "not found" in str(exc_info.value).lower()

    async def test_update_product_cross_tenant_forbidden(self, db_manager):
        """Test that tenant cannot update another tenant's product"""
        from giljo_mcp.exceptions import ResourceNotFoundError

        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        create_result = await service1.create_product(name="Protected Product")
        product_id = str(create_result.id)

        # Try to update from tenant2 - should raise exception
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service2.update_product(product_id=product_id, name="Hacked Name")
        assert "not found" in str(exc_info.value).lower()

        # Verify name unchanged (0731b: returns Product ORM model)
        get_result = await service1.get_product(product_id)
        assert get_result.name == "Protected Product"

    async def test_delete_product_cross_tenant_forbidden(self, db_manager):
        """Test that tenant cannot delete another tenant's product"""
        from giljo_mcp.exceptions import ResourceNotFoundError

        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        create_result = await service1.create_product(name="Protected Product")
        product_id = str(create_result.id)

        # Try to delete from tenant2 - should raise exception
        with pytest.raises(ResourceNotFoundError):
            await service2.lifecycle.delete_product(product_id)

        # Verify product still exists in tenant1 (0731b: returns Product ORM model)
        get_result = await service1.get_product(product_id)
        assert get_result.name == "Protected Product"

    async def test_set_default_product_tenant_isolation(self, db_manager):
        """FE-9524: setting one tenant's DEFAULT product must not affect another
        tenant's default. Rewritten from the pre-split test, which exercised
        activate_product (shown/hidden) and asserted it moved the single
        active-product pointer -- that pointer is now set_default_product's
        job, decoupled from shown/hidden."""
        tenant1_key = str(uuid4())
        tenant2_key = str(uuid4())

        service1 = ProductService(db_manager, tenant1_key)
        service2 = ProductService(db_manager, tenant2_key)

        # Create products in both tenants (0731b: returns Product ORM model)
        create1 = await service1.create_product(name="Tenant1 Product A")
        create2 = await service1.create_product(name="Tenant1 Product B")
        create3 = await service2.create_product(name="Tenant2 Product")

        # Set default in both tenants
        await service1.set_default_product(str(create1.id))
        await service2.set_default_product(str(create3.id))

        # Verify tenant1's default
        default1 = await service1.get_default_product()
        assert default1 is not None
        assert default1.name == "Tenant1 Product A"

        # Verify tenant2's default
        default2 = await service2.get_default_product()
        assert default2 is not None
        assert default2.name == "Tenant2 Product"

        # Set a different default in tenant1
        await service1.set_default_product(str(create2.id))

        # Verify tenant2's default is unaffected
        default2_check = await service2.get_default_product()
        assert default2_check is not None
        assert default2_check.name == "Tenant2 Product"


@pytest.mark.asyncio
class TestSingleActiveProductConstraint:
    """Integration tests for single active product enforcement"""

    async def test_several_products_can_be_shown_at_once(self, db_manager):
        """FE-9524/D1: is_active is REUSED as 'shown as a tab' -- showing one
        product never hides another. Rewrite of the old
        'only one active product per tenant' pin, which asserted exactly the
        DB + service enforcement D1 retires (idx_product_single_active_per_tenant
        dropped in ce_0099; ProductLifecycleService no longer deactivates
        siblings)."""
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        # Create three products (0731b: returns Product ORM model).
        create1 = await service.create_product(name="Product A")
        create2 = await service.create_product(name="Product B")
        create3 = await service.create_product(name="Product C")

        # A new product is shown by default (D1).
        assert create1.is_active is True
        assert create2.is_active is True
        assert create3.is_active is True

        # Explicitly activating (showing) B must not hide A or C.
        activate2 = await service.activate_product(str(create2.id))
        assert activate2.is_active is True

        get_a = await service.get_product(str(create1.id))
        get_b = await service.get_product(str(create2.id))
        get_c = await service.get_product(str(create3.id))
        assert get_a.is_active is True
        assert get_b.is_active is True
        assert get_c.is_active is True

        # Explicitly hiding A must not touch B or C.
        deactivate1 = await service.deactivate_product(str(create1.id))
        assert deactivate1.is_active is False

        get_a = await service.get_product(str(create1.id))
        get_b = await service.get_product(str(create2.id))
        get_c = await service.get_product(str(create3.id))
        assert get_a.is_active is False
        assert get_b.is_active is True
        assert get_c.is_active is True

    async def test_activate_already_active_product(self, db_manager):
        """Test activating an already active product is idempotent"""
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(name="Single Product")
        product_id = str(create_result.id)

        # Activate once (0731b: returns Product ORM model)
        activate1 = await service.activate_product(product_id)
        assert activate1.is_active is True

        # Activate again
        activate2 = await service.activate_product(product_id)
        assert activate2.is_active is True

    async def test_deactivate_product_no_active_product(self, db_manager):
        """Test that deactivating leaves no active product"""
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        create_result = await service.create_product(name="Temporary Active")
        product_id = str(create_result.id)

        # Activate then deactivate (0731b: returns Product ORM model)
        await service.activate_product(product_id)
        deactivate_result = await service.deactivate_product(product_id)
        assert deactivate_result.is_active is False

        # Verify no active product (0731b: returns None)
        active = await service.get_default_product()
        assert active is None
