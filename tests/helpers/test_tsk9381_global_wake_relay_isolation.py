# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.agent_wake_registry import get_wake_registry
from tests.fixtures.base_fixtures import restored_global_wake_relay


def _noop_relay(_tenant_key: str, _agent_ids: list[str]) -> None:
    pass


def test_the_containment_puts_back_exactly_what_it_found():
    registry = get_wake_registry()
    assert registry._relay is None, "a prior test leaked a relay into this one"

    with restored_global_wake_relay():
        registry.set_relay(_noop_relay)
        assert registry._relay is _noop_relay, "the leak must be real inside the block"

    assert registry._relay is None, "the relay must not outlive the test that installed it"


def test_a_relay_installed_by_a_test_does_not_reach_the_next_one():
    registry = get_wake_registry()
    assert registry._relay is None, "a prior test leaked a relay into this one"

    registry.set_relay(_noop_relay)
    assert registry._relay is _noop_relay
