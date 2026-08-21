# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9296a — the wake crosses workers on a multi-worker install.

The registry maps ``asyncio.Event`` objects, so it is per-process by construction.
That is complete for a single worker — every CE self-hoster — because the writer
and the waiter are the same process. Hosted SaaS runs multiple uvicorn workers,
where an agent parked on one worker and the message that should wake it landing
on another is the ORDINARY case. Without this relay the wake would look correct
in every test and never fire in production.

The relay is strictly ADDITIVE and these tests pin that: local waiters are woken
in-process first, the broker hop only reaches OTHER workers, and a broker failure
cannot affect a local wake. That is the inversion of the project's original design,
which blocked ON the broker and would have been dead on a default install.

Parallel-safe: every test builds its own registry/broker, so nothing is shared
across xdist workers.
"""

from __future__ import annotations

import asyncio

from api.broker.base import WebSocketBrokerMessage
from api.broker.in_memory import InMemoryWebSocketEventBroker
from api.startup.agent_wake_relay import AGENT_IDS_KEY, WAKE_CONTROL, install_wake_relay
from giljo_mcp.services.agent_wake_registry import AgentWakeRegistry


class _Scheduler:
    """Stands in for WebSocketManager.schedule — runs the coroutine to completion."""

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []

    def schedule(self, coro):
        self.tasks.append(asyncio.create_task(coro))

    async def drain(self):
        if self.tasks:
            await asyncio.gather(*self.tasks)
            self.tasks.clear()


def test_a_single_worker_install_gets_no_relay():
    """The default CE posture must not pay for a hop whose only listener is itself.

    This is also the guard against re-introducing the original design: on one
    worker the wake MUST be complete without any broker involvement.
    """
    registry = AgentWakeRegistry()
    installed = install_wake_relay(
        broker=InMemoryWebSocketEventBroker(),
        websocket_manager=_Scheduler(),
        worker_count=1,
        registry=registry,
    )
    assert installed is False
    assert registry._relay is None


def test_multi_worker_installs_the_relay():
    registry = AgentWakeRegistry()
    installed = install_wake_relay(
        broker=InMemoryWebSocketEventBroker(),
        websocket_manager=_Scheduler(),
        worker_count=4,
        registry=registry,
    )
    assert installed is True
    assert registry._relay is not None


def test_installing_defaults_to_the_process_registry():
    """Startup passes no registry and must still reach the one the service signals.

    The parameter exists for testability; it must not have quietly changed which
    registry production wires, or the relay would be installed on an object no
    write path can see.
    """
    import inspect

    assert inspect.signature(install_wake_relay).parameters["registry"].default is None


async def test_a_local_signal_is_published_for_peer_workers():
    """The write side: signalling locally must also reach the other workers."""
    broker = InMemoryWebSocketEventBroker()
    scheduler = _Scheduler()
    published: list[WebSocketBrokerMessage] = []
    broker.subscribe(lambda m: _record(published, m))

    registry = AgentWakeRegistry()
    install_wake_relay(broker=broker, websocket_manager=scheduler, worker_count=4, registry=registry)
    registry.signal("tk_x", ["worker-1", "worker-2"])
    await scheduler.drain()

    wake_msgs = [m for m in published if m.control == WAKE_CONTROL]
    assert len(wake_msgs) == 1
    assert wake_msgs[0].tenant_key == "tk_x"
    assert wake_msgs[0].event[AGENT_IDS_KEY] == ["worker-1", "worker-2"]


async def test_an_inbound_relay_wakes_a_local_waiter():
    """The read side: a peer worker's write must wake the waiter parked here."""
    broker = InMemoryWebSocketEventBroker()
    registry = AgentWakeRegistry()
    install_wake_relay(broker=broker, websocket_manager=_Scheduler(), worker_count=4, registry=registry)

    event = registry.register("tk_x", "worker-1")

    # Arrives from a DIFFERENT worker, so a different origin.
    await broker.publish(
        WebSocketBrokerMessage(
            tenant_key="tk_x",
            event={AGENT_IDS_KEY: ["worker-1"]},
            origin="some-other-worker",
            control=WAKE_CONTROL,
        )
    )

    await asyncio.wait_for(event.wait(), timeout=2)
    assert event.is_set()
    registry.unregister("tk_x", "worker-1", event)


async def test_a_relayed_wake_is_not_relayed_onward():
    """Otherwise two workers relay each other's relay forever."""
    broker = InMemoryWebSocketEventBroker()
    scheduler = _Scheduler()
    seen: list[WebSocketBrokerMessage] = []
    broker.subscribe(lambda m: _record(seen, m))

    registry = AgentWakeRegistry()
    install_wake_relay(broker=broker, websocket_manager=scheduler, worker_count=4, registry=registry)
    event = registry.register("tk_x", "worker-1")

    await broker.publish(
        WebSocketBrokerMessage(
            tenant_key="tk_x",
            event={AGENT_IDS_KEY: ["worker-1"]},
            origin="some-other-worker",
            control=WAKE_CONTROL,
        )
    )
    await scheduler.drain()

    assert event.is_set()
    # Exactly the one inbound message; the handler published nothing back.
    assert len([m for m in seen if m.control == WAKE_CONTROL]) == 1
    registry.unregister("tk_x", "worker-1", event)


async def test_a_workers_own_publish_does_not_re_signal_it():
    """A worker already woke its own waiters in-process before publishing."""
    broker = InMemoryWebSocketEventBroker()
    scheduler = _Scheduler()
    registry = AgentWakeRegistry()
    install_wake_relay(broker=broker, websocket_manager=scheduler, worker_count=4, registry=registry)

    signalled = registry.signal("tk_x", ["worker-1"])
    await scheduler.drain()

    # No local waiter existed, and the echo of its own publish must not invent one.
    assert signalled == 0
    assert registry.waiter_count("tk_x") == 0


async def test_a_broker_failure_cannot_break_the_local_wake():
    """The whole point of additive: the local wake is the load-bearing half."""

    class _BrokenBroker(InMemoryWebSocketEventBroker):
        async def publish(self, message):
            raise RuntimeError("broker down")

    registry = AgentWakeRegistry()
    event = registry.register("tk_x", "worker-1")

    def _explode(_tenant, _agents):
        raise RuntimeError("publish failed")

    registry.set_relay(_explode)
    assert registry.signal("tk_x", ["worker-1"]) == 1
    assert event.is_set(), "a relay failure must not cost the local wake"


def test_the_control_discriminator_is_distinct_from_the_existing_one():
    """It shares TSK-9006's channel, so the two control values must not collide."""
    assert WAKE_CONTROL != "disconnect_tenant"


async def test_a_control_frame_is_never_fanned_out_to_browsers():
    """A control message is not an event — its envelope is empty by design.

    Before BE-9296a the broker handler fell through to broadcast_event_to_tenant for
    any control value it did not recognise, so a second control type sharing the
    channel would have been pushed to every connected browser as a bogus update.
    """
    from api.websocket import WebSocketManager

    manager = WebSocketManager()
    broadcast_calls: list[dict] = []

    async def _record_broadcast(**kwargs):
        broadcast_calls.append(kwargs)

    manager.broadcast_event_to_tenant = _record_broadcast  # type: ignore[method-assign]

    broker = InMemoryWebSocketEventBroker()
    manager.attach_broker(broker)

    await broker.publish(
        WebSocketBrokerMessage(
            tenant_key="tk_x",
            event={AGENT_IDS_KEY: ["worker-1"]},
            origin="peer",
            control=WAKE_CONTROL,
        )
    )
    assert broadcast_calls == [], "a control frame must not reach browser clients"

    # A genuine event (control=None) still fans out, so the guard is not too wide.
    await broker.publish(WebSocketBrokerMessage(tenant_key="tk_x", event={"type": "real"}, origin="peer"))
    assert len(broadcast_calls) == 1


async def _record(sink: list, message: WebSocketBrokerMessage) -> None:
    sink.append(message)
