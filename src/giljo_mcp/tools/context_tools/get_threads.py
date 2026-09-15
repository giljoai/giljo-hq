# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.database import DatabaseManager
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)

THREADS_CATEGORY_CAP = 25


async def get_threads(
    tenant_key: str,
    db_manager: DatabaseManager,
) -> dict[str, Any]:
    if not tenant_key:
        raise ValueError("tenant_key is required")

    svc = CommThreadService(db_manager, TenantManager())
    result = await svc.list_threads(limit=THREADS_CATEGORY_CAP + 1, tenant_key=tenant_key)
    rows = result.get("threads", [])

    more_available = len(rows) > THREADS_CATEGORY_CAP
    data = rows[:THREADS_CATEGORY_CAP]

    logger.info(
        "threads_context_fetched tenant_key=%s count=%d more_available=%s",
        tenant_key,
        len(data),
        more_available,
    )

    return {
        "source": "threads",
        "data": data,
        "metadata": {
            "count": len(data),
            "limit_applied": THREADS_CATEGORY_CAP,
            "more_available": more_available,
            "tenant_key": tenant_key,
        },
    }
