# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import exc as sa_exc
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import DatabaseManager
from tests.helpers.test_db_helper import PostgreSQLTestHelper


pytestmark = pytest.mark.asyncio

SERVER_BUSY_BODY = {"error_code": "SERVER_BUSY", "message": "The server is busy. Try again in a moment."}
FAKE_URL = "postgresql://u:p@localhost:5432/giljo_inf9799_fake"


def _pool_timeout() -> sa_exc.TimeoutError:
    return sa_exc.TimeoutError("QueuePool limit of size 1 overflow 0 reached, connection timed out, timeout 1.00")


async def _get(app: FastAPI, path: str, **kwargs):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, **kwargs)


def _assert_server_busy(response) -> None:
    assert response.status_code == 503, response.text
    assert response.json() == SERVER_BUSY_BODY
    assert response.headers.get("retry-after") == "5"


class TestPoolTimeoutIsServerBusy:
    async def test_pool_timeout_raised_in_a_dependency_is_503_server_busy(self):
        app = FastAPI()
        register_exception_handlers(app)

        async def _checkout():
            raise _pool_timeout()

        @app.get("/busy")
        async def busy(_db=Depends(_checkout)):
            return {"reached": True}

        _assert_server_busy(await _get(app, "/busy"))

    async def test_pool_timeout_raised_in_a_middleware_is_503_server_busy(self):
        app = FastAPI()
        register_exception_handlers(app)

        class _CheckoutInMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                raise _pool_timeout()

        app.add_middleware(_CheckoutInMiddleware)

        @app.get("/busy")
        async def busy():
            return {"reached": True}

        _assert_server_busy(await _get(app, "/busy"))

    async def test_operational_error_is_not_remapped(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/broken")
        async def broken():
            raise sa_exc.OperationalError("SELECT 1", {}, Exception("connection refused"))

        response = await _get(app, "/broken")
        assert response.status_code == 500
        assert response.json()["error_code"] == "INTERNAL_SERVER_ERROR"

    async def test_busy_warning_names_the_pool_status(self, monkeypatch, caplog):
        from api.app_state import state

        manager = DatabaseManager(FAKE_URL, is_async=True)
        monkeypatch.setattr(state, "db_manager", manager)
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/busy")
        async def busy():
            raise _pool_timeout()

        with caplog.at_level(logging.WARNING, logger="api.exception_handlers"):
            await _get(app, "/busy")

        busy_lines = [r.getMessage() for r in caplog.records if "db_pool_timeout" in r.getMessage()]
        assert len(busy_lines) == 1, caplog.text
        assert manager.async_engine.pool.status() in busy_lines[0]
        assert "/busy" in busy_lines[0]


@pytest.fixture
async def held_one_connection_pool():
    manager = DatabaseManager(
        PostgreSQLTestHelper.get_test_db_url(), is_async=True, pool_size=1, max_overflow=0, pool_timeout=1
    )
    async with manager.get_session_async() as holder:
        await holder.execute(text("SELECT 1"))
        assert manager.async_engine.pool.checkedout() == 1
        yield manager
    await manager.close_async()


class TestAuthFailsClosed:
    async def test_pool_timeout_in_get_current_active_user_is_503_never_allowed(self, held_one_connection_pool):
        app = FastAPI()
        register_exception_handlers(app)
        app.state.api_state = SimpleNamespace(db_manager=held_one_connection_pool)
        reached: list[str] = []

        @app.get("/api/v1/projects/")
        async def list_projects(_user=Depends(get_current_active_user)):
            reached.append("route")
            return {"projects": ["must never be served"]}

        token = JWTManager.create_access_token(
            user_id=uuid.uuid4(), username="inf9799", role="admin", tenant_key=f"tk_{uuid.uuid4().hex}"
        )
        started = time.monotonic()
        response = await _get(app, "/api/v1/projects/", cookies={"access_token": token})
        elapsed = time.monotonic() - started

        _assert_server_busy(response)
        assert reached == [], "the route body ran although authentication never completed"
        assert elapsed < 5, f"the request waited {elapsed:.1f}s; the pool timeout is 1s"


@pytest.fixture
async def held_pool_slow_timeout():
    manager = DatabaseManager(
        PostgreSQLTestHelper.get_test_db_url(), is_async=True, pool_size=1, max_overflow=0, pool_timeout=5
    )
    async with manager.get_session_async() as holder:
        await holder.execute(text("SELECT 1"))
        assert manager.async_engine.pool.checkedout() == 1
        yield manager
    await manager.close_async()


class TestHealthIsLivenessOnly:

    async def test_health_answers_within_a_second_while_the_pool_is_exhausted(
        self, monkeypatch, held_pool_slow_timeout
    ):
        from api.app_state import state
        from api.wiring import events as events_mod

        monkeypatch.setattr(events_mod, "GILJO_MODE", "ce")
        monkeypatch.setattr(state, "db_manager", held_pool_slow_timeout)
        monkeypatch.setattr(state, "websocket_manager", object())
        monkeypatch.setattr(state, "connections", {})
        monkeypatch.setattr(state, "degraded_services", [])
        monkeypatch.setattr(state, "health_detail", {}, raising=False)
        app = FastAPI()
        register_exception_handlers(app)
        events_mod.register_event_handlers(app)

        started = time.monotonic()
        response = await _get(app, "/health")
        elapsed = time.monotonic() - started

        assert response.status_code == 200, response.text
        assert elapsed < 1.0, f"/health waited {elapsed:.1f}s on the database pool"
        body = response.json()
        assert body["status"] == "healthy"
        assert set(body) == {"status", "checks"}
        assert "database" not in body["checks"]
        assert body["checks"]["api"] == "healthy"
        assert body["checks"]["websocket"] == "healthy"

    async def test_database_readiness_probe_is_bounded_to_two_seconds(self, held_pool_slow_timeout):
        from api.app_state import state
        from api.endpoints import configuration
        from giljo_mcp.auth.dependencies import require_ce_mode

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(configuration.router, prefix="/api/v1/config")
        app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(tenant_key="tk_inf9799")
        app.dependency_overrides[require_ce_mode] = lambda: None
        previous = state.db_manager
        state.db_manager = held_pool_slow_timeout
        try:
            started = time.monotonic()
            response = await _get(app, "/api/v1/config/health/database")
            elapsed = time.monotonic() - started
        finally:
            state.db_manager = previous

        assert response.status_code == 503, response.text
        assert elapsed < 3.0, f"the readiness probe waited {elapsed:.1f}s; its bound is 2 s"
