# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio

from api.broker.base import WebSocketBrokerMessage
from api.broker.in_memory import InMemoryWebSocketEventBroker
from api.startup.agent_wake_relay import AGENT_IDS_KEY, WAKE_CONTROL, install_wake_relay
from giljo_mcp.services.agent_wake_registry import AgentWakeRegistry


class _Scheduler:

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []

    def schedule(self, coro):
        self.tasks.append(asyncio.create_task(coro))

    async def drain(self):
        if self.tasks:
            await asyncio.gather(*self.tasks)
            self.tasks.clear()


def test_a_single_worker_install_gets_no_relay():
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
    import inspect

    assert inspect.signature(install_wake_relay).parameters["registry"].default is None


async def test_a_local_signal_is_published_for_peer_workers():
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
    broker = InMemoryWebSocketEventBroker()
    registry = AgentWakeRegistry()
    install_wake_relay(broker=broker, websocket_manager=_Scheduler(), worker_count=4, registry=registry)

    event = registry.register("tk_x", "worker-1")

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
    assert len([m for m in seen if m.control == WAKE_CONTROL]) == 1
    registry.unregister("tk_x", "worker-1", event)


async def test_a_workers_own_publish_does_not_re_signal_it():
    broker = InMemoryWebSocketEventBroker()
    scheduler = _Scheduler()
    registry = AgentWakeRegistry()
    install_wake_relay(broker=broker, websocket_manager=scheduler, worker_count=4, registry=registry)

    signalled = registry.signal("tk_x", ["worker-1"])
    await scheduler.drain()

    assert signalled == 0
    assert registry.waiter_count("tk_x") == 0


async def test_a_broker_failure_cannot_break_the_local_wake():

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
    assert WAKE_CONTROL != "disconnect_tenant"


async def test_a_control_frame_is_never_fanned_out_to_browsers():
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

    await broker.publish(WebSocketBrokerMessage(tenant_key="tk_x", event={"type": "real"}, origin="peer"))
    assert len(broadcast_calls) == 1


async def _record(sink: list, message: WebSocketBrokerMessage) -> None:
    sink.append(message)
