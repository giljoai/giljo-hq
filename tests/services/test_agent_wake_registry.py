# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import uuid

from giljo_mcp.services.agent_wake_registry import (
    MAX_WAITERS_PER_TENANT,
    AgentWakeRegistry,
    get_wake_registry,
)


WAKE_DEADLINE_SECONDS = 2.0


def _tk(suffix: str) -> str:
    return f"tk_be9296a_{suffix}_{uuid.uuid4().hex[:8]}"


async def test_a_signal_before_the_await_is_not_lost():
    registry = AgentWakeRegistry()
    tenant, agent = _tk("race"), "worker-1"

    event = registry.register(tenant, agent)
    assert registry.signal(tenant, [agent]) == 1

    await asyncio.wait_for(event.wait(), timeout=WAKE_DEADLINE_SECONDS)
    assert event.is_set()


def test_unregister_drops_the_key_so_the_registry_cannot_leak():
    registry = AgentWakeRegistry()
    tenant, agent = _tk("leak"), "worker-1"

    event = registry.register(tenant, agent)
    assert registry.waiter_count(tenant) == 1

    registry.unregister(tenant, agent, event)
    assert registry.waiter_count(tenant) == 0
    registry.unregister(tenant, agent, event)
    assert registry.waiter_count(tenant) == 0


def test_two_sessions_for_one_agent_each_get_their_own_wake():
    registry = AgentWakeRegistry()
    tenant, agent = _tk("multi"), "worker-1"

    first, second = registry.register(tenant, agent), registry.register(tenant, agent)
    assert registry.waiter_count(tenant) == 2
    assert registry.signal(tenant, [agent]) == 2
    assert first.is_set() and second.is_set()


def test_waiter_counts_are_scoped_per_tenant():
    registry = AgentWakeRegistry()
    first_tenant, second_tenant = _tk("a"), _tk("b")

    registry.register(first_tenant, "worker-1")
    assert registry.waiter_count(first_tenant) == 1
    assert registry.waiter_count(second_tenant) == 0


def test_signalling_an_unknown_or_blank_agent_is_a_no_op():
    registry = AgentWakeRegistry()
    assert registry.signal(_tk("unknown"), ["nobody-here", ""]) == 0


def test_a_failing_relay_cannot_break_the_local_wake():
    registry = AgentWakeRegistry()
    tenant, agent = _tk("relay"), "worker-1"

    def _boom(_tenant, _agents):
        raise RuntimeError("broker down")

    registry.set_relay(_boom)
    event = registry.register(tenant, agent)

    assert registry.signal(tenant, [agent]) == 1
    assert event.is_set()


def test_the_relay_receives_the_tenant_and_agents_when_installed():
    registry = AgentWakeRegistry()
    tenant = _tk("published")
    seen: list[tuple[str, list[str]]] = []

    registry.set_relay(lambda tk, agents: seen.append((tk, agents)))
    registry.register(tenant, "worker-1")
    registry.signal(tenant, ["worker-1", "worker-2"])

    assert seen == [(tenant, ["worker-1", "worker-2"])]


def test_relay_can_be_suppressed_for_a_relayed_signal():
    registry = AgentWakeRegistry()
    tenant = _tk("noecho")
    seen: list[str] = []

    registry.set_relay(lambda tk, agents: seen.append(tk))
    event = registry.register(tenant, "worker-1")

    registry.signal(tenant, ["worker-1"], relay=False)
    assert event.is_set()
    assert seen == [], "a relayed signal must not be relayed onward"


def test_the_waiter_cap_is_bounded():
    assert 0 < MAX_WAITERS_PER_TENANT <= 1024


def test_the_process_global_registry_is_a_singleton():
    assert get_wake_registry() is get_wake_registry()
