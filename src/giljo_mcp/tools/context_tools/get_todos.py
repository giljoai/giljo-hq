# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TODO read-back context tool (INF-5077).

Returns the full content + status of every AgentTodoItem for a given job_id
so an orchestrator can construct a faithful full-replacement payload when it
needs to force-complete a stuck agent's pending TODO. Before this tool
existed, the only available read surface was `get_workflow_status`, which
returns counts (completed=N, pending=N, …) but not the item strings —
forcing orchestrators to reconstruct the list from session memory and
degrading audit fidelity.

Surfaced during INF-5070 closeout (2026-05-14): orchestrator rebuilt a
16-item TODO list from session memory because no read-back tool existed.
Read-only; routes through ProgressRepository.get_todo_items().
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.repositories.progress_repository import ProgressRepository


logger = logging.getLogger(__name__)


def _estimate_tokens(data: Any) -> int:
    """chars÷4 measured and found SAFE here, unlike get_tasks.py's identifier-dense
    rows. TODO content is prose (natural-language sentences),
    not identifier-dense JSON -- measured on the real wire serializer
    (pydantic_core.to_json) against tiktoken o200k_base across short/long/mixed-50
    realistic TODO content: 4.10-5.65 chars/token, i.e. ÷4 OVERestimates token cost
    here (the safe direction) rather than understating it. Left unchanged.
    """
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
    """Fetch the full TODO list (sequence, content, status) for a job.

    Args:
        job_id: Job UUID whose TODOs to read.
        tenant_key: Tenant isolation key (mandatory).
        db_manager: Database manager (required if `session` is None).
        session: Optional preexisting session (test injection / shared txn).

    Returns:
        Dict with:
        - source: "todos"
        - data: {"todos": [<rows>], "total": N}
        - metadata: {tenant_key, job_id, estimated_tokens}
    """
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
