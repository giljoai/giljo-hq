# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9381 — the process-global agent-wake relay must not survive a test.

THE INCIDENT (reproduced before it was fixed, deterministically):

    pytest tests/api/test_be3008c_broker_hardening.py \\
           tests/services/test_comm_thread_wake_mixin.py
    -> 1 failed, 40 passed in 5.21s
    -> assert <function install_wake_relay.<locals>._publish at 0x...> is None
       tests/services/test_comm_thread_wake_mixin.py:340

``test_startup_attaches_postgres_broker_multiworker`` drives
``init_websocket_broker`` at worker_count=2, which reaches
``install_wake_relay`` (api/startup/core_services.py) with NO ``registry``
argument — so the relay lands on the process-global registry. Its teardown stops
the broker and leaves the relay behind. The next test in that worker asserting
the default single-worker posture then fails, having done nothing wrong.

Every test that calls ``install_wake_relay`` DIRECTLY already passes its own
``AgentWakeRegistry()`` and touches nothing shared — the shape that function's
docstring asks for. The leak is at the layer above, where no such seam exists,
so containment (``restored_global_wake_relay``) is the only available fix and
the reason the house preference could not be followed here.

Why the diagnosis was hard, and why it read as "ambient": under xdist
``--dist load`` the two files land in the same worker process only sometimes, so
the same green tree produced a different unlucky victim on different runs.

The two tests below mirror the structure INF-5092's own file uses — one that
reproduces the real-world shape, and one that gates the invariant
deterministically — because the realistic shape is the weaker gate here (see
each test's note).
"""

from __future__ import annotations

from giljo_mcp.services.agent_wake_registry import get_wake_registry
from tests.fixtures.base_fixtures import restored_global_wake_relay


def _noop_relay(_tenant_key: str, _agent_ids: list[str]) -> None:
    """Stand-in for the ``_publish`` closure ``install_wake_relay`` installs."""


def test_the_containment_puts_back_exactly_what_it_found():
    """THE deterministic gate: drive the containment itself, in one test.

    Order-independent and xdist-proof — it needs no sibling test to have run
    first, so it cannot be silently defeated by worker assignment. It exercises
    the SAME context manager the autouse fixture in tests/conftest.py uses, so a
    regression in that fixture's body fails here rather than surfacing as a
    mystery failure somewhere else in the suite.
    """
    registry = get_wake_registry()
    assert registry._relay is None, "a prior test leaked a relay into this one"

    with restored_global_wake_relay():
        registry.set_relay(_noop_relay)
        assert registry._relay is _noop_relay, "the leak must be real inside the block"

    assert registry._relay is None, "the relay must not outlive the test that installed it"


def test_a_relay_installed_by_a_test_does_not_reach_the_next_one():
    """The realistic shape: leak from a test body and let TEARDOWN clean it.

    This is the incident as it actually happened — nothing here restores the
    relay, exactly like ``test_startup_attaches_postgres_broker_multiworker``.
    The autouse fixture must clear it, which the test above proves and the whole
    suite proves in aggregate.

    Deliberately NOT paired with a follow-on "now assert it is None" test: under
    ``--dist load`` the pair can be split across worker processes, where the
    second half would pass vacuously. A gate that can silently stop gating is
    worse than no gate, so the assertion lives in the test above instead.
    """
    registry = get_wake_registry()
    assert registry._relay is None, "a prior test leaked a relay into this one"

    registry.set_relay(_noop_relay)
    assert registry._relay is _noop_relay
