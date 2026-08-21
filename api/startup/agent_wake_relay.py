# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Cross-worker fan-out for the agent wake signal (BE-9296a).

The wake registry is per-process: it maps ``asyncio.Event`` objects, which cannot
be shared between OS processes by any means. That is complete for a single-worker
install — every CE self-hoster — because the writer and the waiter are always the
same process.

Hosted SaaS is not that. Deployments may run multiple server workers, so an agent
parked on one worker and the message that should wake it arriving on another is the
ordinary case, not an edge one. Without this relay the wake would look correct in
every test and simply never fire in production.

WHY THIS DOES NOT REPEAT THE ORIGINAL DESIGN'S MISTAKE
------------------------------------------------------
The project's first design blocked ON the broker, which is dead on a default
install because ``api/websocket.py`` gates its broker publish on
``_worker_count() > 1`` and the default broker is ``in_memory``. Here the broker is
strictly ADDITIVE: the in-process registry has already woken every local waiter
before this publishes, and this hop only reaches waiters on OTHER workers. If it
fails, or is not installed at all, local wakes are unaffected.

It is installed ONLY when the process runs multiple workers — which is exactly when
``ensure_broker_supports_worker_count`` has already refused to boot on an
``in_memory`` broker, so a relay that exists is guaranteed a broker that can carry it.

Edition Scope: Both.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from api.broker.base import WebSocketBrokerMessage
from giljo_mcp.services.agent_wake_registry import AgentWakeRegistry, get_wake_registry


logger = logging.getLogger(__name__)

# Control discriminator on the shared giljo_ws_events channel. Reuses the seam
# TSK-9006 established for ``disconnect_tenant`` rather than opening a second
# channel, which ADR-009 tenant-scoping would then have to be re-argued for.
WAKE_CONTROL = "agent_wake"

# Key under which the agent ids ride in the message's (otherwise empty) envelope.
AGENT_IDS_KEY = "agent_ids"


def install_wake_relay(
    *,
    broker: Any,
    websocket_manager: Any,
    worker_count: int,
    registry: AgentWakeRegistry | None = None,
) -> bool:
    """Wire the registry to the broker for multi-worker fan-out. Returns whether it did.

    No-ops on a single worker: the local registry is already complete there, and a
    publish whose only subscriber is this same process is pure overhead — the same
    reasoning ``_publish_to_broker_enabled`` applies to the WS fan-out.

    ``registry`` defaults to the process-wide one, which is what startup wants: the
    service layer signals from arbitrary write paths and must reach the same registry
    the transport wired, exactly as it reaches one broker. It is a PARAMETER because
    installing is a mutation, and a function that silently mutates a module global is
    one a caller cannot exercise without side effects. A test passes its own registry
    and touches nothing shared — which is the house "no module-level mutable state"
    rule satisfied structurally, rather than by a fixture that resets the global
    afterwards and leaves the next caller to rediscover the same trap.
    """
    if worker_count <= 1:
        return False

    registry = registry or get_wake_registry()
    origin = uuid4().hex

    async def _receive(message: WebSocketBrokerMessage) -> None:
        """Wake local waiters for a peer worker's write."""
        if message.control != WAKE_CONTROL:
            return
        # A worker's own publish comes back to it; it already woke its own waiters
        # in-process before publishing.
        if message.origin == origin:
            return
        agent_ids = (message.event or {}).get(AGENT_IDS_KEY) or []
        # relay=False: this wake ARRIVED over the broker. Re-publishing it would put
        # the workers in a loop, each relaying the other's relay forever.
        registry.signal(message.tenant_key, list(agent_ids), relay=False)

    broker.subscribe(_receive)

    def _publish(tenant_key: str, agent_ids: list[str]) -> None:
        """Fan a local wake out to peer workers.

        Synchronous by contract (the registry signals from non-async write paths),
        so the publish is scheduled as a tracked background task rather than
        awaited. ``websocket_manager.schedule`` holds a strong reference so the
        event loop cannot garbage-collect it mid-send.
        """
        websocket_manager.schedule(
            broker.publish(
                WebSocketBrokerMessage(
                    tenant_key=tenant_key,
                    event={AGENT_IDS_KEY: agent_ids},
                    origin=origin,
                    control=WAKE_CONTROL,
                )
            )
        )

    registry.set_relay(_publish)
    logger.info("Agent wake relay installed across %d workers (%s)", worker_count, broker.__class__.__name__)
    return True
