# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.products import Product
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.context_tools.fetch_context import (
    _CATEGORIES_NOT_REQUIRING_PRODUCT_ID,
    CATEGORY_TOOLS,
    fetch_context,
)
from giljo_mcp.tools.context_tools.get_products import get_products


@pytest_asyncio.fixture
async def cleanup_tenants(db_manager):
    tenants: list[str] = []
    yield tenants
    for tk in tenants:
        async with db_manager.get_session_async(tenant_key=tk) as session:
            await session.execute(delete(Product).where(Product.tenant_key == tk))
            await session.commit()


async def _create_product(db_manager, tenant_key: str, name: str, *, is_active: bool = False) -> str:
    product_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, tenant_key=tenant_key, name=name, is_active=is_active))
        await session.commit()
    return product_id


def test_products_category_is_registered() -> None:
    assert "products" in CATEGORY_TOOLS


def test_listing_profile_did_not_grow() -> None:
    from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

    assert "list_products" not in _LISTING_PROFILE_TOOLS
    assert "get_products" not in _LISTING_PROFILE_TOOLS


@pytest.mark.asyncio
async def test_products_category_is_tenant_scoped(db_manager, cleanup_tenants: list[str]) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant_a)
    cleanup_tenants.append(tenant_b)

    product_a1 = await _create_product(db_manager, tenant_a, "Alpha Product", is_active=True)
    product_a2 = await _create_product(db_manager, tenant_a, "Beta Product", is_active=False)
    product_b1 = await _create_product(db_manager, tenant_b, "Gamma Product", is_active=True)

    response = await fetch_context(
        product_id=product_a1,
        tenant_key=tenant_a,
        categories=["products"],
        db_manager=db_manager,
    )

    assert "products" in response["categories_returned"]
    assert "products" not in response.get("categories_empty", [])
    assert "errors" not in response

    by_id = {p["id"]: p for p in response["data"]["products"]}
    assert set(by_id) == {product_a1, product_a2}
    assert product_b1 not in by_id

    assert by_id[product_a1] == {"id": product_a1, "name": "Alpha Product", "is_active": True}
    assert by_id[product_a2] == {"id": product_a2, "name": "Beta Product", "is_active": False}


@pytest.mark.asyncio
async def test_products_category_zero_products_is_empty_not_an_error(db_manager, cleanup_tenants: list[str]) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    response = await fetch_context(
        product_id="",
        tenant_key=tenant,
        categories=["products"],
        db_manager=db_manager,
    )

    assert response["data"]["products"] == []
    assert "products" in response["categories_returned"]
    assert "products" in response.get("categories_empty", [])
    assert "errors" not in response


@pytest.mark.asyncio
async def test_products_category_works_with_no_active_product(db_manager, cleanup_tenants: list[str]) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    product_1 = await _create_product(db_manager, tenant, "Inactive One", is_active=False)
    product_2 = await _create_product(db_manager, tenant, "Inactive Two", is_active=False)

    response = await fetch_context(
        product_id="",
        tenant_key=tenant,
        categories=["products"],
        db_manager=db_manager,
    )

    assert "errors" not in response
    returned_ids = {p["id"] for p in response["data"]["products"]}
    assert returned_ids == {product_1, product_2}
    assert all(p["is_active"] is False for p in response["data"]["products"])


@pytest.mark.asyncio
async def test_products_category_includes_inactive_products(db_manager, cleanup_tenants: list[str]) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    inactive_id = await _create_product(db_manager, tenant, "Only Inactive", is_active=False)

    direct = await get_products(tenant_key=tenant, db_manager=db_manager)

    returned_ids = {p["id"] for p in direct["data"]}
    assert inactive_id in returned_ids


@pytest.mark.asyncio
async def test_product_names_are_not_unique_per_tenant(db_manager, cleanup_tenants: list[str]) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    id_1 = await _create_product(db_manager, tenant, "Duplicate Name")
    id_2 = await _create_product(db_manager, tenant, "Duplicate Name")

    direct = await get_products(tenant_key=tenant, db_manager=db_manager)
    names = [p["name"] for p in direct["data"] if p["id"] in (id_1, id_2)]
    assert names == ["Duplicate Name", "Duplicate Name"]


@pytest.mark.asyncio
async def test_product_scoped_category_still_requires_active_product(db_manager, cleanup_tenants: list[str]) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    await _create_product(db_manager, tenant, "Inactive Only", is_active=False)

    with pytest.raises(ValidationError, match="No default product set"):
        await fetch_context(
            product_id="",
            tenant_key=tenant,
            categories=["tech_stack"],
            db_manager=db_manager,
        )


@pytest.mark.asyncio
async def test_mixed_products_and_product_scoped_category_still_requires_active_product(
    db_manager, cleanup_tenants: list[str]
) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    await _create_product(db_manager, tenant, "Inactive Only", is_active=False)

    with pytest.raises(ValidationError, match="No default product set"):
        await fetch_context(
            product_id="",
            tenant_key=tenant,
            categories=["products", "tech_stack"],
            db_manager=db_manager,
        )


_EXTRA_KWARGS_BY_CATEGORY = {
    "self_identity": {"agent_name": "does-not-exist"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("category", sorted(_CATEGORIES_NOT_REQUIRING_PRODUCT_ID))
async def test_category_not_requiring_product_id_succeeds_with_no_active_product(
    category: str, db_manager, cleanup_tenants: list[str]
) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    kwargs: dict = dict(_EXTRA_KWARGS_BY_CATEGORY.get(category, {}))
    if category == "todos":
        kwargs["job_id"] = str(uuid.uuid4())

    TenantManager.set_current_tenant(tenant)
    try:
        response = await fetch_context(
            product_id="",
            tenant_key=tenant,
            categories=[category],
            db_manager=db_manager,
            **kwargs,
        )
    finally:
        TenantManager.clear_current_tenant()

    assert "errors" not in response
    assert category in response["categories_returned"]
