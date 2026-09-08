# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
WebSocket broadcaster protocol.

Defines the interface that src/giljo_mcp/ code (e.g. AgentHealthMonitor)
needs from the WebSocket layer.  The concrete implementation lives in
api/websocket.WebSocketManager and satisfies this protocol implicitly
(structural subtyping).

Created: 2026-04-18 (Sprint 003a) to break the backward import from
src/giljo_mcp/monitoring/agent_health_monitor.py into api/websocket.

BE-9518: ``broadcast_agent_auto_failed`` / ``broadcast_health_alert`` moved off
this protocol when they were extracted to ``agent_health_ws_broadcast.py`` as
module-level functions (agent_health_monitor.py now imports them directly and
passes the ``WebSocketBroadcaster`` in as their ``websocket_manager`` arg) --
the only method this protocol's sole consumer still calls directly is
``broadcast_event_to_tenant``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WebSocketBroadcaster(Protocol):
    """Minimal broadcast interface consumed by lower-layer monitoring code."""

    async def broadcast_event_to_tenant(
        self,
        tenant_key: str,
        event: dict[str, Any],
        exclude_client: str | None = None,
        *,
        publish_to_broker: bool = True,
    ) -> int: ...
