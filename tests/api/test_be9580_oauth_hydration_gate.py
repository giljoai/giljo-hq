# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9580: the CE side of the OAuth hydration handshake.

Edition Scope: CE. The gate itself is CE code — it reads an attribute the SaaS
resolver may or may not have published and must never assume SaaS is present.
Nothing here imports from ``saas/``; the SaaS-side assertions live in
``tests/saas/auth/test_be9580_oauth_hydration_reaches_boot.py``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from api.startup.oauth_hydration_gate import run_saas_oauth_hydration


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield


@pytest.mark.asyncio
async def test_lifespan_gate_awaits_the_published_hydration():
    """The gate the lifespan calls actually runs the published work."""
    ran: list[str] = []
    app = FastAPI(lifespan=_lifespan)

    async def _hydrate() -> None:
        ran.append("hydrated")

    app.state.saas_oauth_hydrate = _hydrate

    await run_saas_oauth_hydration(app)

    assert ran == ["hydrated"]


@pytest.mark.asyncio
async def test_lifespan_gate_is_a_no_op_for_ce():
    """CE never installs the SaaS resolver, so the gate must find nothing and pass.

    Keeps the Deletion Test honest: the gate lives in CE code and must not
    assume any SaaS attribute exists.
    """
    app = FastAPI(lifespan=_lifespan)

    await run_saas_oauth_hydration(app)  # must not raise


@pytest.mark.asyncio
async def test_lifespan_gate_stays_best_effort_when_hydration_fails():
    """A DB-less boot (setup mode) must still start.

    Startup hydration is an optimisation, not a precondition — a boot without a
    reachable database must still start, and the cache fills on demand
    afterwards. Moving the work into the lifespan must not change that.
    """
    app = FastAPI(lifespan=_lifespan)

    async def _hydrate() -> None:
        raise RuntimeError("database unavailable at startup")

    app.state.saas_oauth_hydrate = _hydrate

    await run_saas_oauth_hydration(app)  # must not raise
