# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9518: shared WebSocket-broadcast unit for agent health-monitor events.

Extracted VERBATIM (file-size compliance, behavior identical -- ``api/websocket.py``
sat at its shrink-only ``scripts/size_budgets.txt`` ceiling) from ``WebSocketManager``,
mirroring the existing ``closeout_ws_broadcast.py`` / ``orchestrator_prompt_ws_broadcast.py``
extractions in the same file for the same reason. Module-level functions (not methods)
so ``monitoring/agent_health_monitor.py`` -- the sole caller -- passes its
``websocket_manager`` explicitly, exactly as it already does for every other
dependency.

Contract (unchanged from the pre-extraction methods): no exception handling was
added or removed. A broadcast failure propagates to the caller exactly as it did
as a ``WebSocketManager`` method.
"""

import logging
from typing import Any

from giljo_mcp.events.schemas import EventFactory


_module_logger = logging.getLogger(__name__)


async def broadcast_health_alert(
    websocket_manager: Any,
    *,
    tenant_key: str,
    job_id: str,
    agent_display_name: str,
    health_status: Any,
) -> None:
    """Broadcast agent health alert."""
    message_data: dict[str, Any] = {
        "tenant_key": tenant_key,
        "job_id": job_id,
        "agent_display_name": agent_display_name,
        "health_state": health_status.health_state,
        "issue_description": health_status.issue_description,
        "minutes_since_update": health_status.minutes_since_update,
        "recommended_action": health_status.recommended_action,
        "execution_id": health_status.execution_id,
        "project_id": health_status.project_id,
        "project_name": health_status.project_name,
        "product_id": health_status.product_id,
    }

    event = EventFactory.tenant_envelope(
        event_type="agent:health_alert",
        tenant_key=tenant_key,
        data=message_data,
        schema_version="1.0",
    )

    await websocket_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)

    _module_logger.warning(
        "broadcast_health_alert job_id=%s health_state=%s minutes_since_update=%s",
        job_id,
        health_status.health_state,
        round(health_status.minutes_since_update, 1),
    )


async def broadcast_agent_auto_failed(
    websocket_manager: Any,
    *,
    tenant_key: str,
    job_id: str,
    agent_display_name: str,
    reason: str,
    product_id: str | None = None,  # BE-9518
    project_id: str | None = None,  # BE-9525c
) -> None:
    """Broadcast agent auto-fail event."""
    message_data: dict[str, Any] = {
        "tenant_key": tenant_key,
        "job_id": job_id,
        "agent_display_name": agent_display_name,
        "reason": reason,
        "auto_failed": True,
    }
    if product_id is not None:
        message_data["product_id"] = product_id
    # BE-9525c: the inverse gap -- this event carried product_id (BE-9518) but
    # no project_id, even though the sibling agent:health_alert broadcast right
    # above uses the same health_status object and already carries it. Not
    # deliberate: the caller (agent_health_monitor.py) already has
    # health_status.project_id in hand for every call site.
    if project_id is not None:
        message_data["project_id"] = project_id

    event = EventFactory.tenant_envelope(
        event_type="agent:auto_failed",
        tenant_key=tenant_key,
        data=message_data,
        schema_version="1.0",
    )

    await websocket_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)

    _module_logger.error(
        "broadcast_auto_failed job_id=%s reason=%s",
        job_id,
        reason,
    )
