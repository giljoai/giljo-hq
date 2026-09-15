# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
