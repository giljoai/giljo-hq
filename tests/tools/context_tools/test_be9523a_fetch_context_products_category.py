# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression test for the 'products' get_context category (BE-9523a).

Product identity a: agents need to resolve a product NAME to a product_id --
today no MCP tool can enumerate products at all. A get_context CATEGORY, not
a new MCP tool (roster-lock name-list and count stay unchanged -- see
test_be9452_standard_profile_roster_lock.py).

Exercises the fix at the fetch_context dispatch layer: categories=['products']
routes through ProductService.list_products (SELECT-only), tenant-scoped,
returns every product (active AND inactive) as {id, name, is_active}.

Also locks in the category's whole reason for existing: it must work with NO
product_id and NO active product set -- every freshly created product starts
inactive (ProductService.create_product always writes is_active=False), so a
multi-product tenant commonly has zero active products. Before this fix,
fetch_context's mandatory product_id resolution (_resolve_active_product_id)
would raise ValidationError before the 'products' category's own dispatch
ever ran, defeating the category's purpose.

Also locks in the BE-9523a finding: Product.name is NOT unique per tenant
(only idx_product_name, a plain non-unique index -- unlike the partial-unique
slug). Two products in the same tenant CAN share a name.

Parallel-safety: DB-touching; function-scoped tenant-key cleanup fixture,
mirrors test_be9352_fetch_context_threads_category.py. No module-level
mutable state, no test ordering dependency.

Edition Scope: Both.
"""

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
    """Collect tenant_keys created by a test; delete their rows at teardown."""
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
    """RED-first lock: before implementation 'products' was absent from
    CATEGORY_TOOLS, so fetch_context(categories=['products']) raised
    ValidationError('Invalid categories...'). Locks the fix in place."""
    assert "products" in CATEGORY_TOOLS


def test_listing_profile_did_not_grow() -> None:
    """The category exists AND the advertised 'listing' marketplace-connector
    profile roster count/name-list is untouched -- no standalone products
    tool was added to reach it (this project adds zero new @mcp.tool
    functions)."""
    from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

    assert "list_products" not in _LISTING_PROFILE_TOOLS
    assert "get_products" not in _LISTING_PROFILE_TOOLS


@pytest.mark.asyncio
async def test_products_category_is_tenant_scoped(db_manager, cleanup_tenants: list[str]) -> None:
    """Seed TWO tenants -- the only setup that can catch a dropped tenant_key
    filter. Tenant A gets 2 products (one active, one inactive); tenant B gets
    1. fetch_context(categories=['products']) on A must return exactly A's
    two product ids/names/is_active flags, never B's."""
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
    """A tenant with zero products gets a clean empty list -- not an error --
    so an empty category never reads as a failure. Also proves the category
    works with NO product_id and NO active product (the category's entire
    reason for existing): a fresh tenant with nothing yet."""
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
    """RED-first lock for the fix in fetch_context's mandatory product_id
    resolution: a tenant with products but NONE active (the normal state --
    ProductService.create_product always writes is_active=False) must still
    resolve categories=['products'] without product_id. Before the fix,
    _resolve_active_product_id raised ValidationError('No active product set')
    before 'products' dispatch ever ran."""
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
    """The category is a resolver over the WHOLE tenant, not just the active
    product -- ProductService.list_products defaults to include_inactive=False,
    so get_products must pass include_inactive=True explicitly or inactive
    products silently vanish from the list an agent is trying to resolve
    against."""
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    inactive_id = await _create_product(db_manager, tenant, "Only Inactive", is_active=False)

    direct = await get_products(tenant_key=tenant, db_manager=db_manager)

    returned_ids = {p["id"] for p in direct["data"]}
    assert inactive_id in returned_ids


@pytest.mark.asyncio
async def test_product_names_are_not_unique_per_tenant(db_manager, cleanup_tenants: list[str]) -> None:
    """BE-9523a finding: Product.name carries only a plain non-unique index
    (idx_product_name), unlike the partial-unique slug
    (idx_product_slug_unique_per_tenant). Two products in the SAME tenant CAN
    share a name at the model/DB layer (ProductService.create_product does
    reject a duplicate name via its own get_by_name pre-check, but that is a
    service-layer guard, not a DB constraint -- a direct insert, a migration
    backfill, or a future bypass of that service method is not stopped by the
    schema). An agent resolving a name to an id must therefore be prepared for
    more than one match and disambiguate by id, never assume the first hit."""
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)

    id_1 = await _create_product(db_manager, tenant, "Duplicate Name")
    id_2 = await _create_product(db_manager, tenant, "Duplicate Name")

    direct = await get_products(tenant_key=tenant, db_manager=db_manager)
    names = [p["name"] for p in direct["data"] if p["id"] in (id_1, id_2)]
    assert names == ["Duplicate Name", "Duplicate Name"]


@pytest.mark.asyncio
async def test_product_scoped_category_still_requires_active_product(db_manager, cleanup_tenants: list[str]) -> None:
    """Guardrail: the fix that lets 'products' skip the active-product
    fallback must NOT widen to a product-SCOPED category. A tenant with zero
    active products asking for 'tech_stack' (which reads product_id) must
    still raise the SAME ValidationError('No active product set...') it
    raised before this PR touched shared resolution -- byte-identical
    behaviour, same code path (_resolve_active_product_id). If the skip
    condition were even slightly too broad, this would start returning an
    empty tech_stack instead of refusing -- which reads as "no data" rather
    than "you did not tell me which product"."""
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
    """Guardrail, the mixed case: one tenant-scoped category
    ('products') in the request must NOT excuse a product-scoped category
    ('tech_stack') requested alongside it. Any category outside
    _CATEGORIES_NOT_REQUIRING_PRODUCT_ID in the list forces the same
    active-product resolution (and the same raise) as if 'products' were
    never asked for at all."""
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


# _CATEGORIES_NOT_REQUIRING_PRODUCT_ID widens the
# skip to FIVE other pre-existing categories beyond 'products' itself --
# 'threads', 'self_identity', 'todos', 'project', 'chain'. Before this PR,
# calling any of these with no product_id/project_id/active product raised
# ValidationError('No active product set...') the moment fetch_context tried
# to resolve one, even though none of them reads product_id at all (each has
# its own, different requirement -- agent_name, job_id, project_id, or
# nothing). That is a real, observable behaviour change to five shipped
# categories.
#
# Parametrized over the SET ITSELF (imported, not retyped) per the
# correction: five separately-authored tests each pin today's membership, but
# none of them defend the INVARIANT -- drop a category from the set later and
# every test in the file still passes, because none of them ask for it. This
# one test fails the moment the set stops matching reality: add a category
# to it and this test demands it work with no active product; remove one and
# the removal is visible in the parametrize diff.
_EXTRA_KWARGS_BY_CATEGORY = {
    "self_identity": {"agent_name": "does-not-exist"},
    # job_id is per-call (a fresh uuid), filled in by the test itself.
}


@pytest.mark.asyncio
@pytest.mark.parametrize("category", sorted(_CATEGORIES_NOT_REQUIRING_PRODUCT_ID))
async def test_category_not_requiring_product_id_succeeds_with_no_active_product(
    category: str, db_manager, cleanup_tenants: list[str]
) -> None:
    """Every category in _CATEGORIES_NOT_REQUIRING_PRODUCT_ID must resolve
    (never raise ValidationError('No active product set...')) for a tenant
    with zero active products and no project_id. 'project'/'chain' still
    return their own missing-project_id error *dict* (unrelated to product
    resolution) -- the pin is specifically that it is a returned dict, not a
    raised exception.

    Some of the underlying tools (get_self_identity, get_todos, and the
    shared depth-config loader run for every category) open their own
    db_manager session with no tenant_key kwarg, relying on TenantManager's
    ambient contextvar (set by request middleware in production) -- set/reset
    it here like a real request would, harmless for the categories that
    don't need it."""
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
