# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import Product
from giljo_mcp.services.product_memory_service import ProductMemoryService
from giljo_mcp.services.settings_service import SettingsService


logger = logging.getLogger(__name__)


def estimate_tokens(data: Any) -> int:
    import json

    text = json.dumps(data) if not isinstance(data, str) else data
    return len(text) // 4


_DEPTH_TOKENS = {"summary": 10}


def parse_git_history_depth(depth: Any) -> int | None:
    if not depth:
        return None
    try:
        return int(depth)
    except (TypeError, ValueError):
        pass
    if isinstance(depth, str):
        token = _DEPTH_TOKENS.get(depth.strip().lower())
        if token is not None:
            return token
    logger.warning("git_history_depth_unrecognized depth=%r fallback=default", depth)
    return None


async def get_git_history(
    product_id: str,
    tenant_key: str,
    commits: int = 25,
    offset: int = 0,
    limit: int = None,
    db_manager: DatabaseManager | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    logger.info("fetching_git_history_context product_id=%s tenant_key=%s depth=%s", product_id, tenant_key, commits)

    if db_manager is None and session is None:
        logger.error("db_manager or session is required operation=get_git_history")
        raise ValueError("db_manager or session parameter is required")

    if session is not None:
        return await _get_git_history_impl(session, product_id, tenant_key, commits)

    async with db_manager.get_session_async() as new_session:
        return await _get_git_history_impl(new_session, product_id, tenant_key, commits)


async def _get_git_history_impl(
    session: AsyncSession,
    product_id: str,
    tenant_key: str,
    commits: int,
) -> dict[str, Any]:
    stmt = select(Product).where(Product.id == product_id, Product.tenant_key == tenant_key)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()

    if not product:
        logger.warning(
            "product_not_found product_id=%s tenant_key=%s operation=get_git_history", product_id, tenant_key
        )
        return {
            "source": "git_history",
            "depth": commits,
            "data": [],
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_commits": 0,
                "returned_commits": 0,
                "git_integration_enabled": False,
                "error": "product_not_found",
            },
        }

    git_enabled = await SettingsService(session, tenant_key).git_integration_enabled()

    if not git_enabled:
        logger.debug("git_integration_disabled product_id=%s operation=get_git_history", product_id)
        return {
            "source": "git_history",
            "depth": commits,
            "data": [],
            "directive": {
                "action": "fetch_from_local_repo",
                "command": f"git log --oneline -{commits}",
                "note": "Git history is not stored on the server. Run this command in the project directory.",
            },
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_commits": 0,
                "returned_commits": 0,
                "git_integration_enabled": False,
                "reason": "git_integration_disabled",
            },
        }

    memory_service = ProductMemoryService(
        db_manager=None,
        tenant_key=tenant_key,
    )
    all_commits = await memory_service.get_git_history(
        product_id=product_id,
        limit=commits,
        session=session,
    )

    if not all_commits:
        logger.debug("no_git_commits_found product_id=%s operation=get_git_history", product_id)
        return {
            "source": "git_history",
            "depth": commits,
            "data": [],
            "directive": {
                "action": "fetch_from_local_repo",
                "command": f"git log --oneline -{commits}",
                "note": "Git history is not stored on the server. Run this command in the project directory.",
            },
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_commits": 0,
                "returned_commits": 0,
                "git_integration_enabled": True,
            },
        }

    filtered_commits = all_commits

    total_tokens = estimate_tokens(filtered_commits)

    logger.info(
        "git_history_fetched product_id=%s tenant_key=%s depth=%s total=%d returned=%d tokens=%d",
        product_id,
        tenant_key,
        commits,
        len(all_commits),
        len(filtered_commits),
        total_tokens,
    )

    return {
        "source": "git_history",
        "depth": commits,
        "data": filtered_commits,
        "metadata": {
            "product_id": product_id,
            "tenant_key": tenant_key,
            "total_commits": len(all_commits),
            "returned_commits": len(filtered_commits),
            "git_integration_enabled": True,
            "pagination_supported": False,
        },
    }
