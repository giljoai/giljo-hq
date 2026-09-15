# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib

import pytest


@pytest.mark.asyncio
async def test_reload_preserves_state_singleton_identity(monkeypatch):
    import api.app_state as app_state_module

    before = app_state_module.state
    monkeypatch.setenv("GILJO_MODE", "saas")
    try:
        importlib.reload(app_state_module)
        assert app_state_module.state is before, "reload FORKED the state singleton"
        assert app_state_module.GILJO_MODE == "saas"
    finally:
        monkeypatch.delenv("GILJO_MODE", raising=False)
        importlib.reload(app_state_module)
        assert app_state_module.state is before


@pytest.mark.asyncio
async def test_health_reports_degraded_services_across_app_state_reload(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    import api.app_state as app_state_module
    import api.wiring.events as events_module

    saved_events_state = events_module.state
    events_module.state = app_state_module.state
    monkeypatch.setenv("GILJO_MODE", "saas")
    try:
        importlib.reload(app_state_module)
        assert events_module.state is app_state_module.state

        from fastapi import FastAPI

        app = FastAPI()
        events_module.register_event_handlers(app)

        monkeypatch.setattr(app_state_module.state, "degraded_services", ["backup_scheduler", "deletion_reaper"])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["degraded_services"] == ["backup_scheduler", "deletion_reaper"]
    finally:
        monkeypatch.delenv("GILJO_MODE", raising=False)
        importlib.reload(app_state_module)
        events_module.state = saved_events_state
