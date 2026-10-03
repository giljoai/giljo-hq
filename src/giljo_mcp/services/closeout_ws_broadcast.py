# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from collections.abc import Iterable
from typing import Any

from giljo_mcp.models import AgentExecution
from giljo_mcp.schemas.service_responses import AgentStatusChangeEvent


_module_logger = logging.getLogger(__name__)


def build_agent_status_change_events(
    executions: Iterable[AgentExecution],
    new_status: str,
) -> list[AgentStatusChangeEvent]:
    return [
        AgentStatusChangeEvent(
            job_id=execution.job_id,
            agent_id=execution.agent_id,
            agent_display_name=execution.agent_display_name,
            agent_name=execution.agent_name,
            old_status=execution.status,
            new_status=new_status,
        )
        for execution in executions
    ]


async def broadcast_agent_status_changed(
    websocket_manager: Any,
    *,
    tenant_key: str,
    project_id: str | None,
    event: AgentStatusChangeEvent,
    product_id: str | None = None,
) -> None:
    if not websocket_manager:
        return
    await websocket_manager.broadcast_to_tenant(
        tenant_key=tenant_key,
        event_type="agent:status_changed",
        data={
            "job_id": event.job_id,
            "project_id": project_id,
            "product_id": product_id,
            "agent_display_name": event.agent_display_name,
            "agent_name": event.agent_name,
            "old_status": event.old_status,
            "status": event.new_status,
        },
    )


async def broadcast_agent_status_events(
    websocket_manager: Any,
    *,
    tenant_key: str,
    project_id: str | None,
    events: Iterable[AgentStatusChangeEvent],
    product_id: str | None = None,
) -> None:
    for event in events:
        await broadcast_agent_status_changed(
            websocket_manager,
            tenant_key=tenant_key,
            project_id=project_id,
            event=event,
            product_id=product_id,
        )
