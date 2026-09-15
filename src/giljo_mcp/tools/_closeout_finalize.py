# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.services.project_helpers import mark_chain_member_status
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


def _resolve_closeout_websocket_manager(explicit: Any | None) -> Any | None:
    if explicit is not None:
        return explicit
    try:
        from giljo_mcp.app_registry.service_registry import get_websocket_manager

        return get_websocket_manager()
    except Exception:  # noqa: BLE001 — WS resolution is best-effort; closeout must not depend on it
        return None


async def _finalize_chain_member_closeout(
    *,
    session: AsyncSession,
    project: Any,
    project_id: str,
    tenant_key: str,
    db_manager: DatabaseManager | None,
    websocket_manager: Any | None,
) -> tuple[Any | None, bool]:
    project.closeout_executed_at = datetime.now(UTC)
    ws = _resolve_closeout_websocket_manager(websocket_manager)
    is_chain_member = await mark_chain_member_status(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        project_id=project_id,
        tenant_key=tenant_key,
        status="completed",
        test_session=session,
        websocket_manager=ws,
    )

    if is_chain_member:
        project.status = ProjectStatus.TERMINATED if project.early_termination else ProjectStatus.COMPLETED
        project.completed_at = datetime.now(UTC)
        await session.flush()

        if ws is not None:
            try:
                await ws.broadcast_project_update(
                    project_id=project_id,
                    update_type="status_changed",
                    project_data={
                        "name": project.name,
                        "status": project.status.value if hasattr(project.status, "value") else project.status,
                        "mission": project.mission,
                        "product_id": project.product_id,
                    },
                    tenant_key=tenant_key,
                )
            except Exception as ws_error:  # noqa: BLE001 — WS resilience: never fail the closeout
                logger.warning("project_update broadcast failed during chain closeout: %s", ws_error)

    elif project.completed_at is None:
        project.completed_at = datetime.now(UTC)

    return ws, is_chain_member
