# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from fastapi import Depends, Request

from api.websocket import WebSocketManager


logger = logging.getLogger(__name__)


async def get_websocket_manager(request: Request) -> WebSocketManager | None:
    ws_manager = getattr(request.app.state, "websocket_manager", None)

    if ws_manager is None:
        logger.debug(
            "WebSocket manager not available in app state",
            extra={"endpoint": request.url.path, "method": request.method},
        )

    return ws_manager


class WebSocketDependency:

    def __init__(
        self,
        manager: WebSocketManager | None = None,
        websocket_manager: WebSocketManager | None = None,
    ):
        self.manager = manager or websocket_manager
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def broadcast_to_tenant(
        self,
        tenant_key: str,
        event_type: str,
        data: dict[str, Any],
        schema_version: str = "1.0",
        exclude_client: str | None = None,
    ) -> int:
        if not tenant_key:
            raise ValueError("tenant_key cannot be empty")

        if not event_type:
            raise ValueError("event_type cannot be empty")

        if not self.manager:
            self.logger.warning(
                "WebSocket manager not available for broadcast",
                extra={"tenant_key": tenant_key, "event_type": event_type},
            )
            return 0

        return await self.manager.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type=event_type,
            data=data,
            schema_version=schema_version,
            exclude_client=exclude_client,
        )

    def is_available(self) -> bool:
        return self.manager is not None


async def get_websocket_dependency(
    manager: WebSocketManager | None = Depends(get_websocket_manager),
) -> WebSocketDependency:
    return WebSocketDependency(manager)


__all__ = ["WebSocketDependency", "get_websocket_dependency", "get_websocket_manager"]
