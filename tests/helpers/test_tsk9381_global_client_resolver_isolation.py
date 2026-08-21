# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9381 — the process-global OAuth client resolver must not survive a test.

THE INCIDENT, caught on a full ``-n 6`` sweep after three targeted probes had
failed to reproduce it:

    FAILED tests/unit/test_oauth_resolver_seam.py::TestBuiltinResolver
           ::test_get_client_resolver_returns_callable
    [gw1] AttributeError: 'coroutine' object has no attribute 'client_id'
    tests/unit/test_oauth_resolver_seam.py:71

``oauth_service`` holds the active resolver in a module global. SaaS startup
replaces the CE built-in with an ASYNC, DB-backed one process-wide
(``install_saas_resolver`` -> ``set_client_resolver(_saas_resolver)``, reached
from ``register_saas_routes`` whenever an app is built with GILJO_MODE=saas).
That install deliberately has no teardown — it is startup, and in production the
process is meant to keep it. In a test process it outlives the test that caused
it, and the next test calling the resolver synchronously gets a coroutine back.

Why it read as "1 run in 5": under xdist ``--dist load`` the app-building test
and the seam file land in the same worker process only sometimes. Note the
victim is in ``tests/unit`` while the leaker is not, and neither ``tests/unit``
alone (2595 passed) nor the whole of ``tests/saas`` alone (1327 passed) leaks —
only the combination a full sweep produces. That is exactly why targeted probes
kept coming back clean and why this was mis-filed as a flaky test.

The containment is snapshot-and-restore, deliberately NOT "pin the builtin
before each test": a module- or class-scoped fixture installing a resolver runs
at a higher scope than a function-scoped autouse one, so pinning would clobber
deliberate installs. Restoring what was there confines the leak to the test that
created it, which is the whole requirement.
"""

from __future__ import annotations

from giljo_mcp.services.oauth_service import (
    ResolvedClient,
    _builtin_single_client_resolver,
    get_client_resolver,
    set_client_resolver,
)
from tests.fixtures.base_fixtures import restored_global_client_resolver


async def _async_resolver(client_id: str, _tenant_key: str) -> ResolvedClient | None:
    """Stands in for ``_saas_resolver`` — async, which is what breaks callers."""
    return ResolvedClient(
        client_id=client_id,
        client_name="Leaked SaaS Client",
        redirect_uris=None,
        client_secret_hash=None,
    )


def test_the_containment_puts_back_exactly_what_it_found():
    """THE deterministic gate: drive the containment itself, in one test.

    Order-independent and xdist-proof — it needs no sibling test to have run
    first, so worker assignment cannot silently defeat it. Exercises the same
    context manager the autouse fixture in tests/conftest.py uses.
    """
    assert get_client_resolver() is _builtin_single_client_resolver, (
        "a prior test leaked a non-builtin resolver into this one"
    )

    with restored_global_client_resolver():
        set_client_resolver(_async_resolver)
        assert get_client_resolver() is _async_resolver, "the leak must be real inside the block"

    assert get_client_resolver() is _builtin_single_client_resolver, (
        "the resolver must not outlive the test that installed it"
    )


def test_a_leaked_async_resolver_would_break_a_synchronous_caller():
    """Pin WHY this matters, not just that the global changed.

    Without this, the containment looks like tidiness. The leaked resolver is
    async, so a synchronous caller gets a coroutine and dies on attribute access
    — the exact AttributeError seen on gw1. Reproducing the consequence here
    means a future reader cannot mistake the fixture for optional hygiene.

    The leak is left in place at the end on purpose: the autouse fixture is what
    cleans it up, and the test above is what proves that happened.
    """
    set_client_resolver(_async_resolver)

    result = get_client_resolver()("giljo-mcp-default", "tk_irrelevant")
    try:
        assert not hasattr(result, "client_id"), "an async resolver must not look synchronous"
    finally:
        result.close()  # never awaited; close it so no "coroutine was never awaited" warning
