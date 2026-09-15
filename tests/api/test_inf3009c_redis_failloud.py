# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import socket
import types

import pytest

from api.startup.cache_backends_gate import install_saas_cache_backends
from giljo_mcp.services.cache_backends import (
    reset_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def _closed_port_url() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"redis://127.0.0.1:{port}/0"


def _fresh_state() -> types.SimpleNamespace:
    return types.SimpleNamespace(redis_mode="unset", redis_client=None)




@pytest.mark.asyncio
async def test_ce_mode_unset_redis_url_is_noop(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    state = _fresh_state()

    await install_saas_cache_backends(state, giljo_mode="ce")

    assert state.redis_mode == "unset"
    assert state.redis_client is None


@pytest.mark.asyncio
async def test_ce_mode_unreachable_redis_url_is_noop(monkeypatch):
    monkeypatch.setenv("REDIS_URL", _closed_port_url())
    state = _fresh_state()

    await install_saas_cache_backends(state, giljo_mode="ce")

    assert state.redis_mode == "unset"
    assert state.redis_client is None


@pytest.mark.asyncio
async def test_saas_mode_unset_redis_url_stays_in_process(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    state = _fresh_state()

    await install_saas_cache_backends(state, giljo_mode="saas")

    assert state.redis_mode == "unset"
    assert state.redis_client is None


@pytest.mark.asyncio
async def test_saas_mode_unreachable_redis_url_raises(monkeypatch):
    monkeypatch.setenv("REDIS_URL", _closed_port_url())
    state = _fresh_state()

    with pytest.raises(RuntimeError, match="unreachable at boot"):
        await install_saas_cache_backends(state, giljo_mode="saas")

    assert state.redis_mode == "unset"
    assert state.redis_client is None




class _FakeSession:
    async def execute(self, *args, **kwargs):
        return None


class _FakeSessionCtx:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, *exc_info):
        return False


class _FakeHealthyDbManager:

    def get_session_async(self):
        return _FakeSessionCtx()


async def _get_health(monkeypatch, *, giljo_mode: str, redis_mode: str, redis_client=None):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from api.app_state import state
    from api.wiring import events as events_mod

    monkeypatch.setattr(events_mod, "GILJO_MODE", giljo_mode)
    monkeypatch.setattr(state, "db_manager", _FakeHealthyDbManager())
    monkeypatch.setattr(state, "websocket_manager", object())
    monkeypatch.setattr(state, "connections", {})
    monkeypatch.setattr(state, "degraded_services", [])
    monkeypatch.setattr(state, "redis_mode", redis_mode)
    monkeypatch.setattr(state, "redis_client", redis_client)

    app = FastAPI()
    events_mod.register_event_handlers(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    return response.json()


@pytest.mark.asyncio
async def test_health_ce_mode_never_reports_redis(monkeypatch):
    body = await _get_health(monkeypatch, giljo_mode="ce", redis_mode="unset")
    assert "redis" not in body["checks"]


@pytest.mark.asyncio
async def test_health_saas_mode_unset_reports_in_process(monkeypatch):
    body = await _get_health(monkeypatch, giljo_mode="saas", redis_mode="unset")
    assert body["checks"]["redis"] == "in-process"


@pytest.mark.asyncio
async def test_health_saas_mode_connected_pings_live_client(monkeypatch):
    class _HealthyClient:
        async def ping(self):
            return True

    body = await _get_health(monkeypatch, giljo_mode="saas", redis_mode="connected", redis_client=_HealthyClient())
    assert body["checks"]["redis"] == "healthy"


@pytest.mark.asyncio
async def test_health_saas_mode_connected_ping_failure_reports_unhealthy_and_degrades(monkeypatch):
    class _DyingClient:
        async def ping(self):
            raise ConnectionError("connection reset by peer")

    body = await _get_health(monkeypatch, giljo_mode="saas", redis_mode="connected", redis_client=_DyingClient())
    assert body["checks"]["redis"].startswith("unhealthy:")
    assert body["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_saas_mode_in_process_does_not_force_degraded_status(monkeypatch):
    body = await _get_health(monkeypatch, giljo_mode="saas", redis_mode="unset")
    assert body["checks"]["redis"] == "in-process"
    assert body["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_saas_mode_connected_healthy_ping_keeps_status_healthy(monkeypatch):
    class _HealthyClient:
        async def ping(self):
            return True

    body = await _get_health(monkeypatch, giljo_mode="saas", redis_mode="connected", redis_client=_HealthyClient())
    assert body["checks"]["redis"] == "healthy"
    assert body["status"] == "healthy"
