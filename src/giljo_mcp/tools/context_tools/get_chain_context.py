# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Chain Context Tool (BE-6196 follow-up).

Fetch the live chain mission for a sub-orchestrator's active sequential
multi-project run. Backs the 'chain' get_context category referenced by the
CH_SUB_ORCHESTRATOR chapter prose (chapters_chain.py) -- that prose has told
sub-orchestrators to "fetch the full chain mission via get_context" since
BE-6196, but no category ever served it (dead pointer).
"""
# Read-only tool -- uses SequenceRunService.find_active_run_for_project (no writes)

import logging
from typing import Any

from giljo_mcp.database import DatabaseManager
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


async def get_chain_context(
    project_id: str, tenant_key: str, db_manager: DatabaseManager | None = None
) -> dict[str, Any]:
    """
    Fetch the caller's active chain run context, tenant-scoped by project_id.

    Args:
        project_id: The caller's own project UUID (used to find the active
            SequenceRun that contains it -- the caller's chain, not any chain).
        tenant_key: Tenant isolation key
        db_manager: Database manager instance

    Returns:
        Dict with chain context info:
        {
            "source": "chain_context",
            "data": {
                "run_id": "uuid",
                "chain_mission": "...",
                "resolved_order": ["p1", "p2", ...],
                "hub_thread_id": "uuid" | None,
                "hub_chat_id": "CHT-####" | None,
            },
            "metadata": {"project_id": "uuid", "tenant_key": "..."}
        }
        On no active run (common outside a chain), "data" is {} and
        "metadata.error" is set to "no_active_chain_run" -- a clean structured
        signal, not an exception.

    Multi-Tenant Isolation:
        find_active_run_for_project filters by tenant_key.
    """
    logger.info("fetching_chain_context project_id=%s tenant_key=%s", project_id, tenant_key)

    if db_manager is None:
        logger.error("db_manager is required operation=get_chain_context")
        raise ValueError("db_manager parameter is required")

    if not project_id:
        logger.warning("chain_context_missing_project_id tenant_key=%s", tenant_key)
        return {
            "source": "chain_context",
            "data": {},
            "metadata": {"tenant_key": tenant_key, "error": "project_id_required"},
        }

    svc = SequenceRunService(db_manager=db_manager)
    run = await svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)

    if run is None:
        logger.info("chain_context_no_active_run project_id=%s tenant_key=%s", project_id, tenant_key)
        return {
            "source": "chain_context",
            "data": {},
            "metadata": {"project_id": project_id, "tenant_key": tenant_key, "error": "no_active_chain_run"},
        }

    # BE-9291: hand the caller its hub instead of making it go looking. This is what
    # replaced search_threads(query="{run_id}") -- resolution is on
    # comm_threads.sequence_run_id now, so the hub is found whatever its subject says.
    # None means the conductor has not stood the hub up yet, which is a legitimate
    # early state and reads as an absent key rather than an error.
    hub = await CommThreadService(db_manager, TenantManager()).resolve_chain_hub_thread(
        sequence_run_id=run["id"], tenant_key=tenant_key
    )

    data = {
        "run_id": run["id"],
        "chain_mission": run.get("chain_mission"),
        "resolved_order": run.get("resolved_order") or [],
        "hub_thread_id": hub["thread_id"] if hub else None,
        "hub_chat_id": hub["chat_id"] if hub else None,
    }

    logger.info(
        "chain_context_fetched project_id=%s tenant_key=%s run_id=%s has_mission=%s",
        project_id,
        tenant_key,
        run["id"],
        run.get("chain_mission") is not None,
    )

    return {
        "source": "chain_context",
        "data": data,
        "metadata": {"project_id": project_id, "tenant_key": tenant_key},
    }
