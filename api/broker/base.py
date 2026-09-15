# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WebSocketBrokerMessage:
    tenant_key: str
    event: dict[str, Any]
    exclude_client: str | None = None
    origin: str | None = None
    control: str | None = None


BrokerHandler = Callable[[WebSocketBrokerMessage], Awaitable[None]]


class WebSocketEventBroker(ABC):

    async def start(self) -> None:  # pragma: no cover
        return None

    async def stop(self) -> None:  # pragma: no cover
        return None

    @abstractmethod
    def subscribe(self, handler: BrokerHandler) -> Callable[[], None]:
        raise NotImplementedError

    @abstractmethod
    async def publish(self, message: WebSocketBrokerMessage) -> None:
        raise NotImplementedError
