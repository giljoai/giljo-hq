# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    ran: list[str] = []
    app = FastAPI(lifespan=_lifespan)

    async def _hydrate() -> None:
        ran.append("hydrated")

    app.state.saas_oauth_hydrate = _hydrate

    await run_saas_oauth_hydration(app)

    assert ran == ["hydrated"]


@pytest.mark.asyncio
async def test_lifespan_gate_is_a_no_op_for_ce():
    app = FastAPI(lifespan=_lifespan)

    await run_saas_oauth_hydration(app)


@pytest.mark.asyncio
async def test_lifespan_gate_stays_best_effort_when_hydration_fails():
    app = FastAPI(lifespan=_lifespan)

    async def _hydrate() -> None:
        raise RuntimeError("database unavailable at startup")

    app.state.saas_oauth_hydrate = _hydrate

    await run_saas_oauth_hydration(app)
