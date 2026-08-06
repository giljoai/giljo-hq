# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP tool for fetching tech stack information.

Handover 0840c: Reads from ProductTechStack table (normalized from config_data JSONB).

BE-9322: Added the ``sections`` depth parameter. Previously this tool always
returned every field regardless of the user's ``depth_tech_stack_sections``
setting -- the setting was persisted to the DB but never reached this
function, so 'required' and 'all' produced byte-identical output (measured
by a QA harness 2026-07-31). 'required' now omits the six per-platform
boolean flags (target_windows..target_cross_platform), which duplicate what
``target_platforms`` (a list) already conveys; 'all' (and any unrecognized
value -- tolerant default, matches the pre-existing column default) keeps
them. This is a genuine field subset, not a cosmetic relabeling: the token
budget documented in fetch_context.py ("tech_stack: 200-400 tokens,
sections: required/all") already implied a modest, not drastic, reduction --
consistent with dropping 6 booleans, not gutting the payload.
"""
# Read-only tool -- uses direct session.execute() for SELECT queries (no writes)

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models.products import Product


logger = logging.getLogger(__name__)


def estimate_tokens(data: Any) -> int:
    """Rough token estimation (1 token ~ 4 chars)."""
    import json

    text = json.dumps(data) if not isinstance(data, str) else data
    return len(text) // 4


async def _query(
    session: AsyncSession,
    *,
    product_id: str,
    tenant_key: str,
    sections: str,
) -> dict[str, Any] | None:
    """Fetch and shape tech stack data. Returns None when the product doesn't exist."""
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

    # BE-9322: 'required' omits the six per-platform boolean flags -- any value
    # other than exactly "required" behaves as "all" (tolerant default), so
    # existing stored rows and unrecognized future values keep the pre-fix
    # full-field behavior.
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
    """
    Fetch tech stack information for given product.

    Handover 0840c: Reads from product_tech_stacks table (normalized).

    Args:
        product_id: Product UUID
        tenant_key: Tenant isolation key
        offset: Skip first N items (reserved for future pagination)
        limit: Max items to return (reserved for future pagination)
        sections: "required" (core fields only) or "all" (adds the per-platform
            boolean flags). BE-9322.
        db_manager: Database manager instance (required if ``session`` is None).
        session: Optional preexisting session (test injection / shared txn).

    Returns:
        Dict with tech stack data from product_tech_stacks table.

    Multi-Tenant Isolation:
        All queries filter by tenant_key and product_id.
    """
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
