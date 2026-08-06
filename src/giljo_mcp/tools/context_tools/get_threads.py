# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Threads Context Tool (Q-08 / BE-9352).

Backs the 'threads' get_context category: lets a session read the tenant's
Hub threads without the roster cost of advertising list_threads /
get_thread_history / search_threads as standalone tools (CTO ruling Q-08 --
the product already advertises 46 MCP tools; a read-shaped feature arrives as
a category of the existing multiplexer, not new tools).
"""
# Read-only tool -- routes through CommThreadService.list_threads, which has
# no write path at all (see docstring below). No viewer_id is passed, so
# list_threads_enriched (a presentation-layer join) never runs either.

from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.database import DatabaseManager
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)

# Q-08: fixed, non-tunable cap -- NOT wired to depth_config (see the "threads"
# branch in fetch_context._fetch_category). Production measurement: 419
# threads / 138,825 chars against fetch_context's 30,000-char
# RESPONSE_CHAR_CEILING (_response_ceiling.py). Unbounded, the ceiling
# trimmer's PROTECTED_ENTRY_FIELDS matches none of thread_dict's keys, so it
# would strip subject/thread_id/chat_id into {"truncated": true} husks before
# ever reaching cap. 25 x ~439 chars/entry is ~37% of the ceiling, leaving
# room for co-requested categories.
THREADS_CATEGORY_CAP = 25


async def get_threads(
    tenant_key: str,
    db_manager: DatabaseManager,
) -> dict[str, Any]:
    """Fetch the tenant's Hub threads for the 'threads' get_context category.

    Deliberately TENANT-scoped only, never product-scoped. fetch_context
    always resolves a product_id, so filtering list_threads(product_id=...)
    is the tempting default -- and it is wrong here: on the production
    tenant, 38 of 419 threads have product_id=None (including the sprint
    coordination threads), so product-scoping would silently return [] on a
    tenant holding hundreds of threads -- manufacturing an "empty looks like
    a defect" failure on exactly the threads this category exists to surface.

    Structurally read-only: CommThreadService.list_threads calls
    touch_participant_last_seen nowhere and has no write path at all, unlike
    get_thread_history / get_my_turn, which write behind
    ``if as_participant:``. Passing no viewer_id also keeps
    list_threads_enriched (a presentation join, not needed here) from running.

    Args:
        tenant_key: Tenant isolation key (server-injected, never agent-supplied).
        db_manager: Database manager instance.

    Returns:
        {
            "source": "threads",
            "data": [<thread_dict>, ...],
            "metadata": {"count", "limit_applied", "more_available", "tenant_key"},
        }
        "data" is a LIST (matching the memory_360 sibling): a dict would be
        truthy and never land in fetch_context's categories_empty signal, and
        the response-ceiling trimmer only knows how to trim a non-empty list
        category -- anything else makes it ``break`` out of the whole loop.
    """
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
        # NOTE: fetch_context currently discards every category wrapper's
        # "metadata" dict when it assembles its own top-level response (it
        # only reads "data" and "directive") -- so more_available/count/
        # limit_applied are computed and logged here but NOT yet delivered to
        # a get_context caller. Kept anyway, deliberately: removing it would
        # hide the truncation signal entirely once fetch_context is changed
        # to surface category metadata (a separate, wider-blast-radius
        # effort across all thirteen categories, not this change).
        "metadata": {
            "count": len(data),
            "limit_applied": THREADS_CATEGORY_CAP,
            "more_available": more_available,
            "tenant_key": tenant_key,
        },
    }
