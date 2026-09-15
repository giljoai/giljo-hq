# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
