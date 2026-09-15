# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from api.broker.base import WebSocketBrokerMessage
from giljo_mcp.services.agent_wake_registry import AgentWakeRegistry, get_wake_registry


logger = logging.getLogger(__name__)

WAKE_CONTROL = "agent_wake"

AGENT_IDS_KEY = "agent_ids"


def install_wake_relay(
    *,
    broker: Any,
    websocket_manager: Any,
    worker_count: int,
    registry: AgentWakeRegistry | None = None,
) -> bool:
    if worker_count <= 1:
        return False

    registry = registry or get_wake_registry()
    origin = uuid4().hex

    async def _receive(message: WebSocketBrokerMessage) -> None:
        if message.control != WAKE_CONTROL:
            return
        if message.origin == origin:
            return
        agent_ids = (message.event or {}).get(AGENT_IDS_KEY) or []
        registry.signal(message.tenant_key, list(agent_ids), relay=False)

    broker.subscribe(_receive)

    def _publish(tenant_key: str, agent_ids: list[str]) -> None:
        websocket_manager.schedule(
            broker.publish(
                WebSocketBrokerMessage(
                    tenant_key=tenant_key,
                    event={AGENT_IDS_KEY: agent_ids},
                    origin=origin,
                    control=WAKE_CONTROL,
                )
            )
        )

    registry.set_relay(_publish)
    logger.info("Agent wake relay installed across %d workers (%s)", worker_count, broker.__class__.__name__)
    return True
