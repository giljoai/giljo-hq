# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_update_check_cycle_error_logs_with_its_stack(monkeypatch, caplog):
    import asyncio

    from api.startup import update_checker

    async def _true(*args, **kwargs):
        return True

    async def _branch(*args, **kwargs):
        return "master"

    async def _boom(*args, **kwargs):
        raise RuntimeError("git exploded")

    async def _stop(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(update_checker, "_fetch_remote", _true)
    monkeypatch.setattr(update_checker, "_resolve_default_branch", _branch)
    monkeypatch.setattr(update_checker, "_commits_behind", _boom)
    monkeypatch.setattr(update_checker.asyncio, "sleep", _stop)
    with caplog.at_level(logging.DEBUG, logger=update_checker.__name__), pytest.raises(asyncio.CancelledError):
        await update_checker._update_check_loop(SimpleNamespace(update_available=None))
    record = next(r for r in caplog.records if "Update check cycle" in r.getMessage())
    assert record.levelno == logging.ERROR and record.exc_info is not None


@pytest.mark.asyncio
async def test_call_counts_is_503_without_a_database():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from api.app_state import state
    from api.endpoints import statistics
    from giljo_mcp.auth.dependencies import get_current_active_user

    app = FastAPI()
    app.include_router(statistics.router, prefix="/api/v1/stats")
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(tenant_key="tk")

    class _Tenant:
        async def __call__(self, request, call_next):
            request.state.tenant_key = "tk"
            return await call_next(request)

    from starlette.middleware.base import BaseHTTPMiddleware

    app.add_middleware(BaseHTTPMiddleware, dispatch=_Tenant())
    prior = state.db_manager
    state.db_manager = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/stats/call-counts")
    finally:
        state.db_manager = prior
    assert response.status_code == 503, response.text
