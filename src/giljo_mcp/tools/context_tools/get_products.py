# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Products Context Tool (BE-9523a).

Backs the 'products' get_context category: the name-to-id resolver an agent
needs when a user says "work on Yapper" but every other MCP tool takes a
product_id UUID. No agent tool could previously enumerate products at all.

A get_context CATEGORY, not a new MCP tool (feedback_prefer_get_context_
category_over_new_mcp_tool) -- the roster-lock name-list and count stay
unchanged.

Resolver shape only: id, name, is_active per product -- NOT a detail dump
(that is product_core's job, one product at a time). Names are NOT the
interface: this lets an agent translate name->id itself; no tool accepts a
bare name.

Product names are NOT guaranteed unique per tenant (BE-9523a finding):
Product.name carries a plain non-unique index (idx_product_name), unlike the
partial-unique slug (idx_product_slug_unique_per_tenant). A tenant can hold
two products with the same name; an agent resolving by name must handle more
than one match (surface both ids and let the user disambiguate) rather than
assume a single hit.
"""
# Read-only tool -- routes through ProductService.list_products (SELECT only).

from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.database import DatabaseManager
from giljo_mcp.services.product_service import ProductService


logger = logging.getLogger(__name__)


async def get_products(
    tenant_key: str,
    db_manager: DatabaseManager,
) -> dict[str, Any]:
    """Fetch the tenant's products for the 'products' get_context category.

    Deliberately TENANT-scoped only, never product-scoped -- the whole point
    is to let an agent resolve a name to a product_id before it has one.
    Returns every product (active and inactive), lean (no eager-loaded
    detail relations -- id/name/is_active only needs the columns).

    Args:
        tenant_key: Tenant isolation key (server-injected, never agent-supplied).
        db_manager: Database manager instance.

    Returns:
        {
            "source": "products",
            "data": [{"id": ..., "name": ..., "is_active": ...}, ...],
            "metadata": {"count": <int>, "tenant_key": <str>},
        }
        "data" is a LIST (matching the threads/memory_360 siblings): a dict
        would be truthy and never land in fetch_context's categories_empty
        signal.
    """
    if not tenant_key:
        raise ValueError("tenant_key is required")

    service = ProductService(db_manager=db_manager, tenant_key=tenant_key)
    products = await service.list_products(include_inactive=True, lean=True)

    data = [{"id": p.id, "name": p.name, "is_active": p.is_active} for p in products]

    logger.info("products_context_fetched tenant_key=%s count=%d", tenant_key, len(data))

    return {
        "source": "products",
        "data": data,
        "metadata": {"count": len(data), "tenant_key": tenant_key},
    }
