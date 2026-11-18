# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.exception_handlers import register_exception_handlers


pytestmark = pytest.mark.asyncio

_REMOTE = ("203.0.113.9", 51000)
_LOCAL = ("127.0.0.1", 51000)


async def test_frontend_config_carries_no_tenant_key(api_client):
    from api.app_state import state

    resp = await api_client.get("/api/v1/config/frontend")

    assert resp.status_code == 200, resp.text
    assert "default_tenant_key" not in resp.json()["security"]
    default_key = state.config.tenant.default_tenant_key
    if isinstance(default_key, str) and default_key:
        assert default_key not in resp.text


async def test_frontend_config_keeps_what_the_dashboard_reads(api_client):
    body = (await api_client.get("/api/v1/config/frontend")).json()

    assert {"api", "websocket", "security", "edition", "giljo_mode", "version"} <= set(body)


@pytest.fixture
def health_app(monkeypatch):
    from api.app_state import state
    from api.wiring import events as events_mod

    monkeypatch.setattr(events_mod, "GILJO_MODE", "ce")
    monkeypatch.setattr(state, "websocket_manager", object())
    monkeypatch.setattr(state, "connections", {"c1": object(), "c2": object()})
    monkeypatch.setattr(state, "degraded_services", ["backup_scheduler"])
    monkeypatch.setattr(state, "health_detail", {}, raising=False)
    app = FastAPI()
    register_exception_handlers(app)
    events_mod.register_event_handlers(app)
    return app


async def _health(app: FastAPI, client: tuple[str, int], headers: dict | None = None):
    transport = ASGITransport(app=app, client=client)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.get("/health", headers=headers or {})


async def test_remote_anonymous_health_is_status_only(health_app):
    resp = await _health(health_app, _REMOTE)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "degraded"}


async def test_proxied_request_from_loopback_is_not_local(health_app):
    resp = await _health(health_app, _LOCAL, {"X-Forwarded-For": "198.51.100.7"})

    assert resp.json() == {"status": "degraded"}


async def test_local_probe_keeps_the_detail(health_app):
    body = (await _health(health_app, _LOCAL)).json()

    assert body["status"] == "degraded"
    assert body["checks"]["api"] == "healthy"
    assert body["checks"]["active_connections"] == 2
    assert body["checks"]["degraded_services"] == ["backup_scheduler"]
