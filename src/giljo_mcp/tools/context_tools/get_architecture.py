# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models.products import Product


logger = logging.getLogger(__name__)


def estimate_tokens(data: Any) -> int:
    import json

    text = json.dumps(data) if not isinstance(data, str) else data
    return len(text) // 4


async def get_architecture(
    product_id: str, tenant_key: str, db_manager: DatabaseManager | None = None
) -> dict[str, Any]:
    logger.info("fetching_architecture_context product_id=%s tenant_key=%s", product_id, tenant_key)

    if db_manager is None:
        logger.error("db_manager is required operation=get_architecture")
        raise ValueError("db_manager parameter is required")

    async with db_manager.get_session_async() as session:
        stmt = (
            select(Product)
            .options(joinedload(Product.architecture))
            .where(Product.id == product_id, Product.tenant_key == tenant_key)
        )
        result = await session.execute(stmt)
        product = result.unique().scalar_one_or_none()

        if not product:
            logger.warning(
                "product_not_found product_id=%s tenant_key=%s operation=get_architecture",
                product_id,
                tenant_key,
            )
            return {
                "source": "architecture",
                "data": {},
                "metadata": {"product_id": product_id, "tenant_key": tenant_key, "error": "product_not_found"},
            }

        arch = product.architecture
        if not arch:
            return {
                "source": "architecture",
                "data": {
                    "primary_pattern": "",
                    "design_patterns": "",
                    "api_style": "",
                    "architecture_notes": "",
                    "coding_conventions": "",
                },
                "metadata": {"product_id": product_id, "tenant_key": tenant_key},
            }

        data = {
            "primary_pattern": arch.primary_pattern or "",
            "design_patterns": arch.design_patterns or "",
            "api_style": arch.api_style or "",
            "architecture_notes": arch.architecture_notes or "",
            "coding_conventions": arch.coding_conventions or "",
        }

        total_tokens = estimate_tokens(data)

        logger.info(
            "architecture_fetched product_id=%s tenant_key=%s has_architecture=True estimated_tokens=%s",
            product_id,
            tenant_key,
            total_tokens,
        )

        return {
            "source": "architecture",
            "data": data,
            "metadata": {"product_id": product_id, "tenant_key": tenant_key},
        }
