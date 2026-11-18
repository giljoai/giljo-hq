# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import time

from fastapi import WebSocket
from fastapi.exceptions import WebSocketException

from api.app_state import state
from api.auth_utils import (
    authenticate_websocket,
    extract_ws_credentials,
    registered_middleware_kwargs,
    websocket_setup_mode,
)
from api.middleware._proxy_aware_ip import ProxyAwareIpResolver
from api.middleware.rate_limiter import RateLimiter, RateLimitMiddleware, is_test_bypass_enabled
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger("api.app")

_HANDSHAKE_SCOPE = "ws_handshake"


async def _admit_handshake(websocket: WebSocket) -> bool:
    if is_test_bypass_enabled():
        return True
    configured = registered_middleware_kwargs(websocket.scope.get("app"), RateLimitMiddleware)
    if configured is None:
        return True
    limiter = RateLimiter(configured.get("requests_per_minute", 100), scope=_HANDSHAKE_SCOPE)
    return await limiter.is_allowed(ProxyAwareIpResolver().resolve(websocket))


async def authenticate_ws_connection(
    websocket: WebSocket,
    client_id: str,
    api_key: str | None,
    token: str | None,
) -> dict | None:
    validation_started = time.monotonic()
    try:
        if not await _admit_handshake(websocket):
            raise WebSocketException(code=1008, reason="Too many requests")
        if state.ws_setup_complete and extract_ws_credentials(websocket) is None:
            raise WebSocketException(code=1008, reason="Authentication required")

        session = None
        session_cm = None
        if state.db_manager:
            session_cm = state.db_manager.get_session_async()
            session = await session_cm.__aenter__()

        try:
            setup_mode = False if state.ws_setup_complete else await websocket_setup_mode(session)
            if session is not None and not setup_mode:
                state.ws_setup_complete = True
            auth_result = await authenticate_websocket(websocket, db=session, setup_mode=setup_mode)

            await websocket.accept()

            user_info = auth_result.get("user", {})
            is_setup = auth_result.get("context") == "setup"
            tenant_key_from_user = user_info.get("tenant_key")

            if not tenant_key_from_user and not is_setup:
                logger.error("WebSocket rejected for %s: missing tenant_key in auth context", sanitize(client_id))
                await websocket.close(code=1008, reason="Missing tenant key")
                return None

            auth_context = {
                "user": user_info,
                "context": auth_result.get("context", "normal"),
                "tenant_key": tenant_key_from_user,
                "authenticated_at": validation_started,
                "expires_at": auth_result.get("expires_at"),
            }
            if token:
                auth_context["auth_type"] = "jwt"
            elif api_key:
                auth_context["auth_type"] = "api_key"
            else:
                auth_context["auth_type"] = "setup"

            await state.websocket_manager.connect(websocket, client_id, auth_context=auth_context)
            state.connections[client_id] = websocket

            auth_type = auth_context.get("auth_type", "setup")
            logger.info(
                "WebSocket connected: %s (context: %s, auth_type: %s)",
                sanitize(client_id),
                sanitize(str(auth_result.get("context", "normal"))),
                sanitize(auth_type),
            )
            return auth_context

        finally:
            if session_cm is not None:
                await session_cm.__aexit__(None, None, None)

    except WebSocketException as e:
        logger.warning("WebSocket authentication failed for %s: %s", sanitize(client_id), sanitize(str(e.reason)))
        await websocket.close(code=1008, reason=e.reason or "Unauthorized")
        return None
