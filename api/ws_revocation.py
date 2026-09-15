# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import asyncpg

from api.broker.base import WebSocketBrokerMessage
from giljo_mcp.logging import ErrorCode


if TYPE_CHECKING:
    from api.websocket import WebSocketManager


logger = logging.getLogger(__name__)


async def close_tenant_sockets(
    manager: WebSocketManager,
    tenant_key: str,
    *,
    reason: str,
    publish_to_broker: bool,
) -> int:
    if not tenant_key:
        raise ValueError("tenant_key cannot be empty")

    import api.websocket as ws_mod

    timeout = ws_mod._WS_SEND_TIMEOUT_SECONDS

    closed_count = 0
    for client_id in list(manager.tenant_connections.get(tenant_key, set())):
        connection = manager.active_connections.get(client_id)
        if connection is not None:
            websocket = manager._unwrap_websocket_connection(connection)
            try:
                await asyncio.wait_for(websocket.close(code=1008, reason=reason), timeout=timeout)
                closed_count += 1
            except (RuntimeError, ValueError, KeyError, TimeoutError, OSError) as e:
                logger.debug("disconnect_tenant close failed for client_id=%s: %s", client_id, e)
        manager.disconnect(client_id)

    if publish_to_broker and manager._event_broker and manager._publish_to_broker_enabled:
        try:
            await manager._event_broker.publish(
                WebSocketBrokerMessage(
                    tenant_key=tenant_key, event={}, origin=manager._broker_origin, control="disconnect_tenant"
                )
            )
        except (RuntimeError, ValueError, KeyError, asyncpg.PostgresError) as e:
            logger.warning(
                "websocket_disconnect_tenant_publish_failed error_code=%s tenant_key=%s error_message=%s",
                ErrorCode.WS_BROADCAST_FAILED.value,
                tenant_key,
                str(e),
            )

    logger.info(
        "WebSocket disconnect_tenant: %s local socket(s) closed",
        closed_count,
        extra={"tenant_key": tenant_key, "closed_count": closed_count},
    )
    return closed_count
