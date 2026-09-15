# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from dataclasses import dataclass
from typing import Any

from api.websocket import WebSocketManager


__all__ = ["ConnectionInfo", "WebSocketManager"]


@dataclass
class ConnectionInfo:
    websocket: Any
    user_id: str | None
    tenant_key: str
    username: str | None = None

    async def send_json(self, data: dict):
        if not hasattr(self.websocket, "send_json"):
            raise RuntimeError("Underlying websocket does not support send_json")
        return await self.websocket.send_json(data)
