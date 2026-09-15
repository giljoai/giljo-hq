# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import text

from api.app_state import GILJO_MODE, state
from api.exception_handlers import register_exception_handlers
from giljo_mcp import branding
from giljo_mcp.utils.log_sanitizer import sanitize

from .websocket import authenticate_ws_connection, handle_ws_subscribe


logger = logging.getLogger("api.app")


def register_event_handlers(app: FastAPI) -> None:

    dist_dir = Path(state.config.get_nested("paths.static", "frontend/dist")) if state.config else Path("frontend/dist")
    has_frontend = dist_dir.exists() and (dist_dir / "index.html").exists()

    if not has_frontend:

        @app.get("/")
        async def root():
            """Root endpoint"""
            from giljo_mcp import __version__ as giljo_version

            edition = "community"
            if hasattr(app.state, "config") and app.state.config:
                edition = getattr(app.state.config, "edition", None) or "community"
            return {
                "name": branding.PRODUCT_NAME,
                "version": giljo_version,
                "edition": edition,
                "status": "operational",
                "endpoints": {"api": "/docs", "websocket": "/ws", "health": "/health"},
            }

    @app.get("/health")
    async def health_check():
        """Health check endpoint"""
        checks = {"api": "healthy", "database": "unknown", "websocket": "unknown"}

        if state.db_manager:
            try:
                async with state.db_manager.get_session_async() as session:
                    await session.execute(text("SELECT 1"))
                    checks["database"] = "healthy"
                    state.health_detail.pop("database", None)
            except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
                checks["database"] = "unhealthy: database"
                state.health_detail["database"] = str(e)
                logger.warning("Health check: database unhealthy: %s", sanitize(str(e)))

        if state.websocket_manager:
            checks["websocket"] = "healthy"
            checks["active_connections"] = len(state.connections)

        if GILJO_MODE == "saas":
            if state.redis_mode == "connected" and state.redis_client is not None:
                from redis.exceptions import RedisError

                try:
                    pong = await state.redis_client.ping()
                    checks["redis"] = "healthy" if pong else "unhealthy: ping returned falsy"
                    if pong:
                        state.health_detail.pop("redis", None)
                except (RedisError, ConnectionError, TimeoutError, OSError) as e:
                    checks["redis"] = "unhealthy: redis"
                    state.health_detail["redis"] = str(e)
                    logger.warning("Health check: redis unhealthy: %s", sanitize(str(e)))
            else:
                checks["redis"] = "in-process"

        status = (
            "healthy"
            if all(v in ("healthy", "in-process") or isinstance(v, int) for v in checks.values())
            else "degraded"
        )

        if state.degraded_services:
            checks["degraded_services"] = list(state.degraded_services)
            status = "degraded"

        return {"status": status, "checks": checks}

    from giljo_mcp.auth.dependencies import get_current_active_user
    from giljo_mcp.models.auth import User

    @app.get("/api/system/status")
    async def system_status(current_user: User = Depends(get_current_active_user)):
        """System status for admin dashboard notifications.

        Returns pending migration flag and update availability. Requires
        a valid authenticated session.
        """
        return {
            "pending_migration": state.pending_migration,
            "update_available": state.update_available,
            "health_detail": dict(state.health_detail),
        }

    @app.websocket("/ws/{client_id}")
    async def websocket_endpoint(
        websocket: WebSocket, client_id: str, api_key: str | None = Query(None), token: str | None = Query(None)
    ):
        """WebSocket endpoint for real-time updates with authentication"""
        auth_context = await authenticate_ws_connection(
            websocket=websocket,
            client_id=client_id,
            api_key=api_key,
            token=token,
        )
        if auth_context is None:
            return

        try:
            while True:
                data = await websocket.receive_json()

                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

                elif data.get("type") == "subscribe":
                    await handle_ws_subscribe(
                        websocket=websocket,
                        client_id=client_id,
                        data=data,
                        auth_context=auth_context,
                    )

                elif data.get("type") == "unsubscribe":
                    entity_type = data.get("entity_type")
                    entity_id = data.get("entity_id")
                    await state.websocket_manager.unsubscribe(client_id, entity_type, entity_id)
                    await websocket.send_json(
                        {"type": "unsubscribed", "entity_type": entity_type, "entity_id": entity_id}
                    )

        except WebSocketDisconnect:
            state.websocket_manager.disconnect(client_id, websocket)
            if client_id in state.connections:
                del state.connections[client_id]
            logger.info("WebSocket disconnected: %s", sanitize(client_id))
        except (RuntimeError, ValueError, KeyError):
            logger.exception("WebSocket error for {client_id}")
            state.websocket_manager.disconnect(client_id, websocket)
            if client_id in state.connections:
                del state.connections[client_id]

    register_exception_handlers(app)
    app.state.api_state = state

