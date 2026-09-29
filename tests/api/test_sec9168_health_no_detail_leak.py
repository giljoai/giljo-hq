# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest


DB_SENTINEL = "internal-db-host-9f7.local:5432 refused"
REDIS_SENTINEL = "internal-redis-host-3c1.local:6379 reset"


class _FailingSessionCtx:
    async def __aenter__(self):
        raise ConnectionError(DB_SENTINEL)

    async def __aexit__(self, *exc_info):
        return False


class _FailingDbManager:
    def get_session_async(self):
        return _FailingSessionCtx()


class _HealthySession:
    async def execute(self, *args, **kwargs):
        return None


class _HealthySessionCtx:
    async def __aenter__(self):
        return _HealthySession()

    async def __aexit__(self, *exc_info):
        return False


class _HealthyDbManager:
    def get_session_async(self):
        return _HealthySessionCtx()


class _DyingRedisClient:
    async def ping(self):
        raise ConnectionError(REDIS_SENTINEL)


def _build_app(monkeypatch, *, giljo_mode: str, db_manager, redis_mode: str = "unset", redis_client=None):
    from fastapi import FastAPI

    from api.app_state import state
    from api.wiring import events as events_mod

    monkeypatch.setattr(events_mod, "GILJO_MODE", giljo_mode)
    monkeypatch.setattr(state, "db_manager", db_manager)
    monkeypatch.setattr(state, "websocket_manager", object())
    monkeypatch.setattr(state, "connections", {})
    monkeypatch.setattr(state, "degraded_services", [])
    monkeypatch.setattr(state, "redis_mode", redis_mode)
    monkeypatch.setattr(state, "redis_client", redis_client)
    monkeypatch.setattr(state, "health_detail", {}, raising=False)
    monkeypatch.setattr(state, "pending_migration", False)
    monkeypatch.setattr(state, "update_available", None)

    app = FastAPI()
    events_mod.register_event_handlers(app)
    return app


async def _get(app, path: str):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_anonymous_health_db_failure_carries_no_exception_text(monkeypatch):
    app = _build_app(monkeypatch, giljo_mode="ce", db_manager=_FailingDbManager())

    response = await _get(app, "/health")
    body = response.json()

    assert DB_SENTINEL not in response.text
    assert body["checks"]["database"] == "unhealthy: database"
    assert body["status"] == "degraded"


@pytest.mark.asyncio
async def test_anonymous_health_redis_failure_carries_no_exception_text(monkeypatch):
    app = _build_app(
        monkeypatch,
        giljo_mode="saas",
        db_manager=_HealthyDbManager(),
        redis_mode="connected",
        redis_client=_DyingRedisClient(),
    )

    response = await _get(app, "/health")
    body = response.json()

    assert REDIS_SENTINEL not in response.text
    assert body["checks"]["redis"] == "unhealthy: redis"
    assert body["status"] == "degraded"


@pytest.mark.asyncio
async def test_authenticated_system_status_carries_a_fixed_code_not_raw_text(monkeypatch, caplog):
    import logging

    from giljo_mcp.auth.dependencies import get_current_active_user

    app = _build_app(monkeypatch, giljo_mode="saas", db_manager=_FailingDbManager())
    app.dependency_overrides[get_current_active_user] = object

    with caplog.at_level(logging.WARNING, logger="api.app"):
        await _get(app, "/health")
    response = await _get(app, "/api/system/status")
    body = response.json()

    assert DB_SENTINEL not in response.text, (
        f"raw exception text leaked to an authenticated non-operator SaaS user: {response.text}"
    )
    assert body["health_detail"]["database"] == "unreachable"
    assert DB_SENTINEL in caplog.text, "the original exception text must still be logged server-side"
    assert "pending_migration" in body
    assert "update_available" in body


@pytest.mark.asyncio
async def test_health_recovery_clears_the_stashed_detail(monkeypatch):
    from api.app_state import state
    from giljo_mcp.auth.dependencies import get_current_active_user

    app = _build_app(monkeypatch, giljo_mode="ce", db_manager=_HealthyDbManager())
    app.dependency_overrides[get_current_active_user] = object
    state.health_detail["database"] = "stale detail from a previous outage"

    await _get(app, "/health")
    response = await _get(app, "/api/system/status")

    assert response.json()["health_detail"] == {}
