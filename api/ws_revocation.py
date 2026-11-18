# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import asyncpg

from api.broker.base import WebSocketBrokerMessage
from giljo_mcp.logging import ErrorCode


if TYPE_CHECKING:
    from api.websocket import WebSocketManager


logger = logging.getLogger(__name__)

_REVOCATION_STAMP_TTL_SECONDS = 300.0


def revoked_since_handshake(manager: WebSocketManager, auth_context: dict) -> bool:
    revoked_at = manager.tenant_revoked_at.get(auth_context.get("tenant_key"))
    started = auth_context.get("authenticated_at")
    return revoked_at is not None and started is not None and started <= revoked_at


async def _close_and_deregister(manager: WebSocketManager, client_id: str, *, reason: str) -> bool:
    import api.websocket as ws_mod

    closed = False
    connection = manager.active_connections.get(client_id)
    if connection is not None:
        websocket = manager._unwrap_websocket_connection(connection)
        try:
            await asyncio.wait_for(websocket.close(code=1008, reason=reason), timeout=ws_mod._WS_SEND_TIMEOUT_SECONDS)
            closed = True
        except (RuntimeError, ValueError, KeyError, TimeoutError, OSError) as e:
            logger.debug("WebSocket close failed for client_id=%s: %s", client_id, e)
    manager.disconnect(client_id)
    return closed


async def close_expired_sockets(manager: WebSocketManager) -> int:
    stale_before = time.monotonic() - _REVOCATION_STAMP_TTL_SECONDS
    for tenant_key, stamp in list(manager.tenant_revoked_at.items()):
        if stamp < stale_before:
            del manager.tenant_revoked_at[tenant_key]

    now = time.time()
    expired = [
        client_id
        for client_id, context in list(manager.auth_contexts.items())
        if context.get("expires_at") is not None and context["expires_at"] <= now
    ]
    closed = 0
    for client_id in expired:
        closed += await _close_and_deregister(manager, client_id, reason="Session expired")
    if expired:
        logger.info("WebSocket heartbeat closed %s socket(s) with an expired credential", closed)
    return closed


async def close_tenant_sockets(
    manager: WebSocketManager,
    tenant_key: str,
    *,
    reason: str,
    publish_to_broker: bool,
) -> int:
    if not tenant_key:
        raise ValueError("tenant_key cannot be empty")

    manager.tenant_revoked_at[tenant_key] = time.monotonic()

    closed_count = 0
    for client_id in list(manager.tenant_connections.get(tenant_key, set())):
        closed_count += await _close_and_deregister(manager, client_id, reason=reason)

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
