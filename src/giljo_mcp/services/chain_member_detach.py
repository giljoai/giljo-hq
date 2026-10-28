# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from giljo_mcp.models.sequence_runs import CHAIN_TERMINAL_PROJECT_STATUSES
from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository
from giljo_mcp.services.project_helpers import mark_chain_member_status


async def detach_chain_member(
    *,
    db_manager: Any,
    tenant_manager: Any,
    project_id: str,
    tenant_key: str,
    test_session: Any | None = None,
    websocket_manager: Any | None = None,
) -> bool:
    from giljo_mcp.services.sequence_run_service import SequenceRunService

    svc = SequenceRunService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        session=test_session,
        websocket_manager=websocket_manager,
    )
    run = await svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)
    if run is None or run.get("status") not in ("running", "stalled"):
        return False
    detached = await mark_chain_member_status(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        project_id=project_id,
        tenant_key=tenant_key,
        status="detached",
        test_session=test_session,
        websocket_manager=websocket_manager,
        not_from=CHAIN_TERMINAL_PROJECT_STATUSES - {"detached"},
    )
    if not detached:
        return False
    async with (
        nullcontext(test_session)
        if test_session is not None
        else db_manager.get_session_async(tenant_key=tenant_key) as stand_down_session
    ):
        await ProjectLifecycleRepository().stand_down_project_agents(stand_down_session, tenant_key, project_id)
    return True
