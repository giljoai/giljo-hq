# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import logging
from collections.abc import Callable
from typing import Any


logger = logging.getLogger(__name__)


class EventBus:

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._event_counts: dict[str, int] = {}

    async def publish(self, event_type: str, data: dict[str, Any]) -> int:
        if not event_type:
            raise ValueError("event_type cannot be empty")

        if not isinstance(data, dict):
            raise TypeError("data must be a dictionary")

        async with self._lock:
            listeners = self._listeners.get(event_type, []).copy()

        if not listeners:
            self.logger.debug(
                f"No listeners registered for event type: {event_type}",
                extra={"event_type": event_type, "data_keys": list(data.keys())},
            )
            return 0

        self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1

        success_count = 0
        failed_count = 0

        self.logger.info(
            f"Publishing event: {event_type} to {len(listeners)} listener(s)",
            extra={
                "event_type": event_type,
                "listener_count": len(listeners),
                "tenant_key": data.get("tenant_key"),
            },
        )

        for handler in listeners:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, handler, data)

                success_count += 1

            except Exception as e:
                failed_count += 1
                self.logger.error(
                    f"Event handler failed for {event_type}: {e}",
                    extra={
                        "event_type": event_type,
                        "handler": handler.__name__,
                        "error": str(e),
                    },
                    exc_info=True,
                )

        self.logger.info(
            f"Event dispatched: {event_type} ({success_count} success, {failed_count} failed)",
            extra={
                "event_type": event_type,
                "success_count": success_count,
                "failed_count": failed_count,
            },
        )

        return success_count

    async def subscribe(self, event_type: str, handler: Callable) -> None:
        if not event_type:
            raise ValueError("event_type cannot be empty")

        if not callable(handler):
            raise TypeError("handler must be callable")

        async with self._lock:
            if event_type not in self._listeners:
                self._listeners[event_type] = []

            if handler not in self._listeners[event_type]:
                self._listeners[event_type].append(handler)

                self.logger.info(
                    f"Registered handler for event: {event_type}",
                    extra={
                        "event_type": event_type,
                        "handler": handler.__name__,
                        "total_handlers": len(self._listeners[event_type]),
                    },
                )

    def unsubscribe(self, event_type: str, handler: Callable) -> bool:
        if not event_type or event_type not in self._listeners:
            return False

        if handler in self._listeners[event_type]:
            self._listeners[event_type].remove(handler)
            self.logger.info(
                f"Unregistered handler for event: {event_type}",
                extra={
                    "event_type": event_type,
                    "handler": handler.__name__,
                },
            )
            return True

        return False

    def get_listener_count(self, event_type: str = None) -> int:
        if event_type:
            return len(self._listeners.get(event_type, []))
        return sum(len(handlers) for handlers in self._listeners.values())

    def clear(self) -> None:
        self._listeners.clear()
        self._event_counts.clear()
        self.logger.info("Event bus cleared")
