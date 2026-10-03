# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models.products import Product
from giljo_mcp.tools.context_tools._response_ceiling import estimate_tokens


logger = logging.getLogger(__name__)


async def _query(
    session: AsyncSession,
    *,
    product_id: str,
    tenant_key: str,
    sections: str,
) -> dict[str, Any] | None:
    stmt = (
        select(Product)
        .options(joinedload(Product.tech_stack))
        .where(Product.id == product_id, Product.tenant_key == tenant_key)
    )
    result = await session.execute(stmt)
    product = result.unique().scalar_one_or_none()

    if not product:
        return None

    ts = product.tech_stack
    data = {
        "programming_languages": (ts.programming_languages if ts else "") or "",
        "frontend_frameworks": (ts.frontend_frameworks if ts else "") or "",
        "backend_frameworks": (ts.backend_frameworks if ts else "") or "",
        "databases": (ts.databases_storage if ts else "") or "",
        "infrastructure": (ts.infrastructure if ts else "") or "",
        "dev_tools": (ts.dev_tools if ts else "") or "",
        "target_platforms": product.target_platforms or ["all"],
    }

    if ts and sections != "required":
        data["target_windows"] = ts.target_windows
        data["target_linux"] = ts.target_linux
        data["target_macos"] = ts.target_macos
        data["target_android"] = ts.target_android
        data["target_ios"] = ts.target_ios
        data["target_cross_platform"] = ts.target_cross_platform

    return data


async def get_tech_stack(
    product_id: str,
    tenant_key: str,
    offset: int = 0,
    limit: int = None,
    sections: str = "all",
    db_manager: DatabaseManager | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    logger.info("fetching_tech_stack_context product_id=%s tenant_key=%s sections=%s", product_id, tenant_key, sections)

    if session is None and db_manager is None:
        logger.error("db_manager is required operation=get_tech_stack")
        raise ValueError("either session or db_manager is required")

    if session is not None:
        data = await _query(session, product_id=product_id, tenant_key=tenant_key, sections=sections)
    else:
        async with db_manager.get_session_async() as new_session:
            data = await _query(new_session, product_id=product_id, tenant_key=tenant_key, sections=sections)

    if data is None:
        logger.warning(
            "product_not_found product_id=%s tenant_key=%s operation=get_tech_stack",
            product_id,
            tenant_key,
        )
        return {
            "source": "tech_stack",
            "data": {},
            "metadata": {"product_id": product_id, "tenant_key": tenant_key, "error": "product_not_found"},
        }

    total_tokens = estimate_tokens(data)

    logger.info(
        "tech_stack_fetched product_id=%s tenant_key=%s sections=%s estimated_tokens=%s",
        product_id,
        tenant_key,
        sections,
        total_tokens,
    )

    return {
        "source": "tech_stack",
        "data": data,
        "metadata": {
            "product_id": product_id,
            "tenant_key": tenant_key,
            "pagination_supported": False,
            "sections": sections,
        },
    }
