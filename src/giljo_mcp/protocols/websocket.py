# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WebSocketBroadcaster(Protocol):

    async def broadcast_event_to_tenant(
        self,
        tenant_key: str,
        event: dict[str, Any],
        exclude_client: str | None = None,
        *,
        publish_to_broker: bool = True,
    ) -> int: ...
