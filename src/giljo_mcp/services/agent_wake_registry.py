# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""In-process wake signalling for agents blocked on ``await_my_turn`` (BE-9296a).

An agent that is waiting for its turn used to have only one option: sleep, poll,
sleep again. Turn-based harnesses cannot hold a timer across turns, so the poll
interval WAS the coordination latency — the BE-9289 chain lost four hand-offs to
exactly that gap.

This registry is the wait primitive. A waiter parks on an ``asyncio.Event``; the
message/baton write path sets it the moment something lands for that agent.

WHY IN-PROCESS AND NOT THE BROKER
---------------------------------
The original design said to block on the PostgresNotifyBroker. That does not work
on a default install, for two mutually-reinforcing reasons:

* ``api/websocket.py:246`` only publishes to the broker when
  ``_publish_to_broker_enabled``, which is ``_worker_count() > 1`` — and
  ``WEB_CONCURRENCY`` defaults to 1. On one worker the publish never happens.
* ``api/broker/__init__.py`` defaults the broker to ``in_memory``, and
  ``GILJO_WS_BROKER`` is set in no shipping config in this tree.

So a default CE self-hoster would have had a wake tool that returned empty at
every timeout, silently, with every test green. The registry is therefore
signalled DIRECTLY at the write boundary, and the broker is subscribed
ADDITIONALLY as a cross-worker relay (see ``agent_wake_relay``) — never as the
primary path.

Edition Scope: Both.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable


logger = logging.getLogger(__name__)

# Ceiling on parked waiters per tenant. A tenant is one user (ADR-009), so this
# bounds one operator's fleet, not a shared pool. Over the cap the tool declines
# to park and tells the caller to poll instead — polling is the documented
# fallback and is PRIMARY for chat surfaces, permanently.
MAX_WAITERS_PER_TENANT = 64


class AgentWakeRegistry:
    """Maps ``(tenant_key, agent_id)`` to the events of everyone waiting on it.

    A SET of events per key, not one event: the same ``agent_id`` can legitimately
    have two live MCP sessions (a CLI and a web harness), and each of them needs
    its own wake rather than racing to consume a shared one.
    """

    def __init__(self) -> None:
        self._waiters: dict[tuple[str, str], set[asyncio.Event]] = {}
        self._relay: Callable[[str, list[str]], None] | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def waiter_count(self, tenant_key: str) -> int:
        """How many waiters this tenant currently has parked, across all agents."""
        return sum(len(events) for (tk, _), events in self._waiters.items() if tk == tenant_key)

    def register(self, tenant_key: str, agent_id: str) -> asyncio.Event:
        """Enrol a waiter and return the event it should await.

        MUST be called BEFORE the caller reads the database for already-pending
        work. Registering after the read opens a lost-wakeup window: a message
        committed between the read and the registration sets nothing, and the
        waiter then blocks for the full timeout over work that already exists.
        Registering first means such a signal lands on an event that is already
        armed, so the subsequent await returns immediately.
        """
        event = asyncio.Event()
        self._waiters.setdefault((tenant_key, agent_id), set()).add(event)
        return event

    def unregister(self, tenant_key: str, agent_id: str, event: asyncio.Event) -> None:
        """Remove a waiter's event. Safe to call twice.

        Callers MUST run this from a ``finally`` — a waiter that is cancelled
        (client vanished, server shutting down) would otherwise leave its event
        in the map forever, and the map is process-lifetime.
        """
        key = (tenant_key, agent_id)
        events = self._waiters.get(key)
        if events is None:
            return
        events.discard(event)
        if not events:
            del self._waiters[key]

    # ------------------------------------------------------------------
    # Signalling
    # ------------------------------------------------------------------

    def signal(self, tenant_key: str, agent_ids: list[str], *, relay: bool = True) -> int:
        """Wake every waiter parked on any of ``agent_ids``. Returns waiters woken.

        MUST be called only AFTER the writer's database transaction has committed.
        Signalling from inside the write's session wakes a reader that opens its
        own session, cannot see the uncommitted row, finds nothing, and re-parks —
        which presents exactly as the coordination gap this closes.

        Never raises: a wake is an optimisation over polling, and the write that
        triggered it is already durable. Failing the writer's call because a
        waiter could not be notified would trade a real write for a missed hint.
        """
        woken = 0
        for agent_id in agent_ids:
            if not agent_id:
                continue
            for event in self._waiters.get((tenant_key, agent_id), set()):
                event.set()
                woken += 1

        # Cross-worker fan-out (SaaS multi-worker). Gated + published inside the
        # relay hook, which is absent on a single-worker box.
        if relay and self._relay is not None:
            try:
                self._relay(tenant_key, [a for a in agent_ids if a])
            except Exception:  # noqa: BLE001 - relay is best-effort; local wake already happened
                logger.debug("agent wake relay publish failed (non-fatal)", exc_info=True)
        return woken

    # ------------------------------------------------------------------
    # Cross-worker relay hook
    # ------------------------------------------------------------------

    def set_relay(self, relay: Callable[[str, list[str]], None] | None) -> None:
        """Install (or clear) the cross-worker publish hook.

        Wired at startup only when the process runs multiple workers. Kept as an
        injected callable so this module stays free of any ``api.`` import — the
        service layer must not depend on the transport layer.
        """
        self._relay = relay

    def reset(self) -> None:
        """Drop all waiters and the relay. Test-only."""
        self._waiters.clear()
        self._relay = None


# Process-global instance. The registry is deliberately per-process state: it
# maps in-memory asyncio primitives, which cannot be shared across workers by any
# means other than the relay above.
_registry = AgentWakeRegistry()


def get_wake_registry() -> AgentWakeRegistry:
    """The process-wide wake registry."""
    return _registry
