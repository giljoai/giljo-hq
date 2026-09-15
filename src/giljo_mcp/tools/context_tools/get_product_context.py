# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy import select

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models.products import Product


logger = logging.getLogger(__name__)


def estimate_tokens(data: Any) -> int:
    import json

    text = json.dumps(data)
    return len(text) // 4


async def get_product_context(
    product_id: str, tenant_key: str, db_manager: DatabaseManager | None = None
) -> dict[str, Any]:
    logger.info("fetching_product_context product_id=%s tenant_key=%s", product_id, tenant_key)

    if db_manager is None:
        logger.error("db_manager is required operation=get_product_context")
        raise ValueError("db_manager parameter is required")

    async with db_manager.get_session_async() as session:
        stmt = select(Product).where(Product.id == product_id, Product.tenant_key == tenant_key)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()

        if not product:
            logger.warning(
                "product_not_found product_id=%s tenant_key=%s operation=get_product_context",
                product_id,
                tenant_key,
            )
            return {
                "source": "product_context",
                "data": {},
                "metadata": {"product_id": product_id, "tenant_key": tenant_key, "error": "product_not_found"},
            }

        core_features = product.core_features or ""

        data = {
            "product_name": product.name,
            "product_description": product.description or "",
            "project_path": product.project_path or "",
            "core_features": core_features,
            "brand_guidelines": product.brand_guidelines or "",
            "is_active": product.is_active,
            "created_at": product.created_at.isoformat() if product.created_at else None,
        }

        total_tokens = estimate_tokens(data)

        logger.info(
            "product_context_fetched product_id=%s tenant_key=%s has_core_features=%s estimated_tokens=%s",
            product_id,
            tenant_key,
            bool(core_features),
            total_tokens,
        )

        return {
            "source": "product_context",
            "data": data,
            "metadata": {"product_id": product_id, "tenant_key": tenant_key},
        }
