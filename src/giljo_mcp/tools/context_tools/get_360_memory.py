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


logger = logging.getLogger(__name__)


def estimate_tokens(data: Any) -> int:
    import json

    text = json.dumps(data) if not isinstance(data, str) else data
    return len(text) // 4


DEPTH_HEADLINES = "headlines"
DEPTH_FULL = "full"

LEGACY_TAG_MAPPING: dict[str, str | None] = {
    "frontend": "frontend",
    "backend": "backend",
    "service": "backend",
    "endpoint": "api",
    "tool": "backend",
    "agent": "backend",
    "orchestrator": "backend",
    "documenter": "backend",
    "analyzer": "backend",
    "tools": "backend",
    "memory": "backend",
    "protocol": "api",
    "template": "backend",
    "database": "database",
    "migration": "migration",
    "URL": "infrastructure",
    "server-side": "backend",
    "page": "frontend",
    "users": "backend",
    "flow": "feature",
    "added": "feature",
    "built": "feature",
    "shipped": "feature",
    "fixed": "bug-fix",
    "Fixed": "bug-fix",
    "removed": "refactor",
    "eliminated": "refactor",
    "cleanup": "refactor",
    "standardization": "refactor",
    "discipline": "refactor",
    "audit": "security",
    "security": "security",
    "edition": "feature",
    "writes": "refactor",
    "complete": "feature",
    "closed": "chore",
    "written": "docs",
    "entry": "docs",
    "project": "chore",
    "from": None,
    "across": None,
    "files": None,
    "commits": None,
    "with": None,
    "via": None,
    "lines": None,
    "write": None,
    "direct": None,
    "giljoai": None,
    "saas": None,
    "demo/saas": None,
    "v1.1.6": None,
}


def _apply_legacy_tag_mapping(raw_tags: list[str]) -> list[str]:
    mapped: list[str] = []
    seen: set[str] = set()
    for t in raw_tags or []:
        if t in LEGACY_TAG_MAPPING:
            replacement = LEGACY_TAG_MAPPING[t]
            if replacement is None or replacement in seen:
                continue
            seen.add(replacement)
            mapped.append(replacement)
        else:
            if t in seen:
                continue
            seen.add(t)
            mapped.append(t)
    return mapped


def _serialize_headline(entry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "sequence": entry.sequence,
        "project_name": entry.project_name,
        "type": entry.entry_type,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "summary": entry.summary or "",
        "tags": _apply_legacy_tag_mapping(entry.tags or []),
        "has_full_body": True,
    }


def _serialize_full(entry) -> dict[str, Any]:
    data = entry.to_dict()
    data["tags"] = _apply_legacy_tag_mapping(data.get("tags") or [])
    data["has_full_body"] = False
    return data


async def get_360_memory(
    product_id: str,
    tenant_key: str,
    last_n_projects: int = 3,
    offset: int = 0,
    limit: int = None,
    depth: str = DEPTH_HEADLINES,
    db_manager: DatabaseManager | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    logger.info(
        "fetching_360_memory_context product_id=%s tenant_key=%s depth=%s offset=%s limit=%s",
        product_id,
        tenant_key,
        last_n_projects,
        offset,
        limit,
    )

    if db_manager is None and session is None:
        logger.error("db_manager or session is required operation=get_360_memory")
        raise ValueError("db_manager or session parameter is required")

    if depth not in (DEPTH_HEADLINES, DEPTH_FULL):
        depth = DEPTH_HEADLINES

    if session is not None:
        return await _get_360_memory_impl(session, product_id, tenant_key, last_n_projects, offset, limit, depth)

    async with db_manager.get_session_async() as new_session:
        return await _get_360_memory_impl(new_session, product_id, tenant_key, last_n_projects, offset, limit, depth)


async def _get_360_memory_impl(
    session: AsyncSession,
    product_id: str,
    tenant_key: str,
    last_n_projects: int,
    offset: int,
    limit: int | None,
    depth: str,
) -> dict[str, Any]:
    stmt = select(Product).where(Product.id == product_id, Product.tenant_key == tenant_key)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()

    if not product:
        logger.warning("product_not_found product_id=%s tenant_key=%s operation=get_360_memory", product_id, tenant_key)
        return {
            "source": "360_memory",
            "depth": last_n_projects,
            "data": [],
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_projects": 0,
                "last_n_projects": last_n_projects,
                "offset": offset,
                "limit": limit or 0,
                "returned_projects": 0,
                "has_more": False,
                "next_offset": None,
                "error": "product_not_found",
            },
        }

    memory_service = ProductMemoryService(
        db_manager=None,
        tenant_key=tenant_key,
    )

    entries, total_projects = await memory_service.get_entries_by_last_n_projects(
        product_id=product_id,
        last_n_projects=last_n_projects,
        offset=offset,
        include_deleted=False,
        session=session,
    )

    if total_projects == 0:
        logger.debug("no_memory_entries product_id=%s operation=get_360_memory", product_id)
        return {
            "source": "360_memory",
            "depth": last_n_projects,
            "data": [],
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_projects": 0,
                "last_n_projects": last_n_projects,
                "offset": offset,
                "returned_projects": 0,
                "has_more": False,
                "next_offset": None,
            },
        }

    serializer = _serialize_full if depth == DEPTH_FULL else _serialize_headline
    paginated_history = [serializer(entry) for entry in entries]

    returned_project_ids = {e.project_id for e in entries if e.project_id}
    returned_projects = len(returned_project_ids)

    has_more = (offset + returned_projects) < total_projects
    next_offset = offset + returned_projects if has_more else None


    total_tokens = estimate_tokens(paginated_history)

    logger.info(
        "360_memory_fetched product_id=%s tenant_key=%s depth=%s offset=%s total_projects=%s returned_projects=%s returned_entries=%s has_more=%s estimated_tokens=%s",
        product_id,
        tenant_key,
        last_n_projects,
        offset,
        total_projects,
        returned_projects,
        len(paginated_history),
        has_more,
        total_tokens,
    )

    return {
        "source": "360_memory",
        "depth": last_n_projects,
        "data": paginated_history,
        "metadata": {
            "product_id": product_id,
            "tenant_key": tenant_key,
            "total_projects": total_projects,
            "last_n_projects": last_n_projects,
            "offset": offset,
            "returned_projects": returned_projects,
            "returned_entries": len(paginated_history),
            "has_more": has_more,
            "next_offset": next_offset,
        },
    }
