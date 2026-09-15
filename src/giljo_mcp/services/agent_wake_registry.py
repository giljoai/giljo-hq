# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable


logger = logging.getLogger(__name__)

MAX_WAITERS_PER_TENANT = 64


class AgentWakeRegistry:

    def __init__(self) -> None:
        self._waiters: dict[tuple[str, str], set[asyncio.Event]] = {}
        self._relay: Callable[[str, list[str]], None] | None = None


    def waiter_count(self, tenant_key: str) -> int:
        return sum(len(events) for (tk, _), events in self._waiters.items() if tk == tenant_key)

    def register(self, tenant_key: str, agent_id: str) -> asyncio.Event:
        event = asyncio.Event()
        self._waiters.setdefault((tenant_key, agent_id), set()).add(event)
        return event

    def unregister(self, tenant_key: str, agent_id: str, event: asyncio.Event) -> None:
        key = (tenant_key, agent_id)
        events = self._waiters.get(key)
        if events is None:
            return
        events.discard(event)
        if not events:
            del self._waiters[key]


    def signal(self, tenant_key: str, agent_ids: list[str], *, relay: bool = True) -> int:
        woken = 0
        for agent_id in agent_ids:
            if not agent_id:
                continue
            for event in self._waiters.get((tenant_key, agent_id), set()):
                event.set()
                woken += 1

        if relay and self._relay is not None:
            try:
                self._relay(tenant_key, [a for a in agent_ids if a])
            except Exception:  # noqa: BLE001 - relay is best-effort; local wake already happened
                logger.debug("agent wake relay publish failed (non-fatal)", exc_info=True)
        return woken


    def set_relay(self, relay: Callable[[str, list[str]], None] | None) -> None:
        self._relay = relay

    def reset(self) -> None:
        self._waiters.clear()
        self._relay = None


_registry = AgentWakeRegistry()


def get_wake_registry() -> AgentWakeRegistry:
    return _registry
