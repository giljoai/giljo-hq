# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.repositories.progress_repository import ProgressRepository


logger = logging.getLogger(__name__)


def _estimate_tokens(data: Any) -> int:
    import json

    return len(json.dumps(data, default=str)) // 4


async def _query(
    session: AsyncSession,
    *,
    job_id: str,
    tenant_key: str,
) -> list[dict[str, Any]]:
    repo = ProgressRepository()
    rows = await repo.get_todo_items(session, tenant_key, job_id)
    return [
        {
            "sequence": item.sequence,
            "content": item.content,
            "status": item.status,
        }
        for item in rows
    ]


async def get_todos(
    job_id: str,
    tenant_key: str,
    db_manager: DatabaseManager | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    if not tenant_key:
        raise ValueError("tenant_key is required")
    if not job_id:
        raise ValueError("job_id is required")
    if session is None and db_manager is None:
        raise ValueError("either session or db_manager is required")

    if session is not None:
        rows = await _query(session, job_id=job_id, tenant_key=tenant_key)
    else:
        async with db_manager.get_session_async() as new_session:
            rows = await _query(new_session, job_id=job_id, tenant_key=tenant_key)

    data = {"todos": rows, "total": len(rows)}
    logger.info(
        "todos_context_fetched job_id=%s tenant_key=%s count=%d",
        job_id,
        tenant_key,
        len(rows),
    )
    return {
        "source": "todos",
        "data": data,
        "metadata": {
            "job_id": job_id,
            "tenant_key": tenant_key,
            "estimated_tokens": _estimate_tokens(data),
        },
    }
