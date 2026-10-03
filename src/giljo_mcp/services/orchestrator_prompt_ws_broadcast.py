# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any


_module_logger = logging.getLogger(__name__)

EVENT_TYPE = "orchestrator:prompt_generated"


async def broadcast_orchestrator_prompt_generated(
    websocket_manager: Any,
    *,
    tenant_key: str,
    project_id: str,
    orchestrator_id: str,
    agent_id: str | None = None,
    execution_id: str | None = None,
    estimated_tokens: int | None = None,
    tool: str | None = None,
    timestamp: str | None = None,
    product_id: str | None = None,
) -> None:
    if not websocket_manager:
        return

    data: dict[str, Any] = {
        "project_id": project_id,
        "orchestrator_id": orchestrator_id,
        "thin_client": True,
    }
    optional = {
        "agent_id": agent_id,
        "execution_id": execution_id,
        "estimated_tokens": estimated_tokens,
        "tool": tool,
        "timestamp": timestamp,
        "product_id": product_id,
    }
    data.update({key: value for key, value in optional.items() if value is not None})

    await websocket_manager.broadcast_to_tenant(
        tenant_key=tenant_key,
        event_type=EVENT_TYPE,
        data=data,
    )
