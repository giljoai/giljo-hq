# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tasks Context Tool - Phase E of agent-parity (2026-05).

Fetch the open-task summary for the current tenant + active product so an
agent calling ``fetch_context(categories=["tasks"])`` sees what's still
pending. Read-only; routes through TaskService.list_tasks_for_mcp() in
summary mode for a compact projection.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.models import Task, TaxonomyType


logger = logging.getLogger(__name__)

OPEN_STATUSES = ("pending", "in_progress", "blocked")


def _estimate_tokens(data: Any) -> int:
    """Rough token estimate for this row's identifier-dense JSON shape.

    NOT the naive chars÷4 heuristic: measured on the real wire serializer
    (pydantic_core.to_json) against tiktoken o200k_base for rows shaped like
    this tool's output, chars/token is 2.92-3.00 at n=1/10/50 rows -- ÷4
    understates by 19.8-21.7% on this identifier-dense shape (UUIDs, ISO
    timestamps). ÷3 lands within a percent of the measured token count at
    n=50 (5189 vs 5196).
    """
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
            Task.deleted_at.is_(None),  # BE-6130b: exclude trashed tasks
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
                # FE-5046: parity with list_tasks summary projection.
                "taxonomy_alias": task.taxonomy_alias or "",
                "series_number": task.series_number,
                "subseries": task.subseries,
                "hidden": bool(task.hidden),
                "due_date": task.due_date.isoformat() if task.due_date else None,
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
    """BE-9467: the TRUE open-task count, not the length of a capped page.

    Same predicates as ``_query`` (minus ``limit``/``order_by``), so this
    always agrees with what "open" means for the page above it. Indexed on
    tenant_key + product_id + status (idx_task_product, idx_task_status).
    """
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
    """Fetch open/in-progress tasks for the current tenant.

    Args:
        product_id: Active product ID (used to scope tasks to product).
        tenant_key: Tenant isolation key (mandatory).
        limit: Max tasks returned (default 50; cap on response size).
        db_manager: Database manager (required if ``session`` is None).
        session: Optional preexisting session (test injection / shared txn).

    Returns:
        Dict with:
        - source: "tasks"
        - data: {"tasks": [<page, bounded by limit>], "open_count": <TRUE open count>}
        - metadata: {tenant_key, product_id, estimated_tokens, limit,
          truncated: bool -- True when open_count exceeds len(tasks)}
    """
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

    # BE-9467: open_count is the TRUE count (a second indexed query), not
    # len(page) -- a tenant with more open tasks than `limit` was previously
    # told it had exactly `limit`, in a field whose name promised otherwise.
    data = {"tasks": summary_rows, "open_count": true_open_count}
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
