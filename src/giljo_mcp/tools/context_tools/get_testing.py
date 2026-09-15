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

    text = json.dumps(data)
    return len(text) // 4


async def get_testing(product_id: str, tenant_key: str, db_manager: DatabaseManager | None = None) -> dict[str, Any]:
    logger.info("fetching_testing_context product_id=%s tenant_key=%s", product_id, tenant_key)

    if db_manager is None:
        logger.error("db_manager is required operation=get_testing")
        raise ValueError("db_manager parameter is required")

    async with db_manager.get_session_async() as session:
        stmt = (
            select(Product)
            .options(joinedload(Product.test_config))
            .where(Product.id == product_id, Product.tenant_key == tenant_key)
        )
        result = await session.execute(stmt)
        product = result.unique().scalar_one_or_none()

        if not product:
            logger.warning(
                "product_not_found product_id=%s tenant_key=%s operation=get_testing", product_id, tenant_key
            )
            return {
                "source": "testing",
                "data": {},
                "metadata": {"product_id": product_id, "tenant_key": tenant_key, "error": "product_not_found"},
            }

        tc = product.test_config
        data = {
            "quality_standards": (tc.quality_standards if tc else "") or "",
            "testing_strategy": (tc.test_strategy if tc else "") or "",
            "coverage_target": (tc.coverage_target if tc else 80) or 80,
            "testing_frameworks": (tc.testing_frameworks if tc else "") or "",
        }

        total_tokens = estimate_tokens(data)

        logger.info(
            "testing_context_fetched product_id=%s tenant_key=%s has_test_config=%s estimated_tokens=%s",
            product_id,
            tenant_key,
            tc is not None,
            total_tokens,
        )

        return {"source": "testing", "data": data, "metadata": {"product_id": product_id, "tenant_key": tenant_key}}
