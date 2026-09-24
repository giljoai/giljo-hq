# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.models import Task, TaxonomyType
from giljo_mcp.services.next_action import task_list_next_action


logger = logging.getLogger(__name__)

OPEN_STATUSES = ("pending", "in_progress", "blocked")


def _estimate_tokens(data: Any) -> int:
    import json

    return len(json.dumps(data, default=str)) // 3


async def _query(
    session: AsyncSession,
    *,
    product_id: str,
    tenant_key: str,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(Task, TaxonomyType.abbreviation)
        .join(
            TaxonomyType,
            and_(Task.task_type_id == TaxonomyType.id, TaxonomyType.tenant_key == tenant_key),
            isouter=True,
        )
        .where(
            Task.tenant_key == tenant_key,
            Task.product_id == product_id,
            Task.deleted_at.is_(None),
            Task.status.in_(OPEN_STATUSES),
        )
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    with tenant_session_context(session, tenant_key):
        rows = (await session.execute(stmt)).all()
    summary: list[dict[str, Any]] = []
    for task, type_abbr in rows:
        summary.append(
            {
                "task_id": str(task.id),
                "title": task.title,
                "status": task.status,
                "priority": task.priority,
                "task_type": type_abbr,
                "taxonomy_alias": task.taxonomy_alias or "",
                "series_number": task.series_number,
                "subseries": task.subseries,
                "hidden": bool(task.hidden),
                "created_at": task.created_at.isoformat() if task.created_at else None,
            }
        )
    return summary


async def _count_open(
    session: AsyncSession,
    *,
    product_id: str,
    tenant_key: str,
) -> int:
    stmt = select(func.count(Task.id)).where(
        Task.tenant_key == tenant_key,
        Task.product_id == product_id,
        Task.deleted_at.is_(None),
        Task.status.in_(OPEN_STATUSES),
    )
    with tenant_session_context(session, tenant_key):
        return (await session.execute(stmt)).scalar_one()


async def get_tasks(
    product_id: str,
    tenant_key: str,
    limit: int = 50,
    db_manager: DatabaseManager | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    if not tenant_key:
        raise ValueError("tenant_key is required")
    if session is None and db_manager is None:
        raise ValueError("either session or db_manager is required")

    if session is not None:
        summary_rows = await _query(session, product_id=product_id, tenant_key=tenant_key, limit=limit)
        true_open_count = await _count_open(session, product_id=product_id, tenant_key=tenant_key)
    else:
        async with db_manager.get_session_async(tenant_key=tenant_key) as new_session:
            summary_rows = await _query(new_session, product_id=product_id, tenant_key=tenant_key, limit=limit)
            true_open_count = await _count_open(new_session, product_id=product_id, tenant_key=tenant_key)

    data: dict[str, Any] = {"tasks": summary_rows, "open_count": true_open_count}
    task_hint = task_list_next_action(row["status"] for row in summary_rows)
    if task_hint is not None:
        data["next_action"] = task_hint
    truncated = true_open_count > len(summary_rows)
    logger.info(
        "tasks_context_fetched product_id=%s tenant_key=%s returned=%d open_count=%d truncated=%s",
        product_id,
        tenant_key,
        len(summary_rows),
        true_open_count,
        truncated,
    )
    return {
        "source": "tasks",
        "data": data,
        "metadata": {
            "product_id": product_id,
            "tenant_key": tenant_key,
            "estimated_tokens": _estimate_tokens(data),
            "limit": limit,
            "truncated": truncated,
        },
    }
