# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    product_id: str | None = None,
    project_id: str | None = None,
) -> None:
    message_data: dict[str, Any] = {
        "tenant_key": tenant_key,
        "job_id": job_id,
        "agent_display_name": agent_display_name,
        "reason": reason,
        "auto_failed": True,
    }
    if product_id is not None:
        message_data["product_id"] = product_id
    if project_id is not None:
        message_data["project_id"] = project_id

    event = EventFactory.tenant_envelope(
        event_type="agent:auto_failed",
        tenant_key=tenant_key,
        data=message_data,
        schema_version="1.0",
    )

    await websocket_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)

    _module_logger.warning(
        "broadcast_auto_failed job_id=%s reason=%s",
        job_id,
        reason,
    )
