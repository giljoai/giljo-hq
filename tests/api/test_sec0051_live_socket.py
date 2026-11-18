# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import contextlib
import time
import uuid
from types import SimpleNamespace

import bcrypt
import pytest
from fastapi.testclient import TestClient
from starlette.middleware import Middleware
from starlette.websockets import WebSocketDisconnect

import api.wiring.websocket as ws_wiring
from api import auth_utils
from api.app_state import state
from api.middleware.rate_limiter import RateLimiter
from api.websocket import WebSocketManager
from giljo_mcp.auth.jwt_manager import JWTManager
from tests.api.test_be6004c_websocket_tenant_scope import (
    _build_portal_db_manager,
    _cleanup_tenant,
    _install_ws_app_state,
    _no_op_lifespan,
)


_PASSWORD = "Sec0051-old-Passw0rd!"
_NEW_PASSWORD = "Sec0051-new-Passw0rd!"
_SAME_ORIGIN = "http://testserver"




async def _seed(db_manager) -> dict:
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    suffix = uuid.uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(name=f"SEC0051 {suffix}", slug=f"sec0051-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        user = User(
            username=f"sec0051_{suffix}",
            email=f"sec0051_{suffix}@example.com",
            password_hash=bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt()).decode(),
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
            token_revocation_epoch=0,
        )
        session.add(user)
        await session.commit()
    return {"tenant_key": tenant_key, "user_id": str(user.id), "username": user.username}


def _mint(seeded: dict, *, epoch: int = 0) -> str:
    return JWTManager.create_access_token(
        user_id=seeded["user_id"],
        username=seeded["username"],
        role="developer",
        tenant_key=seeded["tenant_key"],
        revocation_epoch=epoch,
    )


async def _change_password(db_manager, seeded: dict) -> None:
    from giljo_mcp.services.user_auth_service import UserAuthService

    await UserAuthService(db_manager, seeded["tenant_key"]).change_password(
        seeded["user_id"], old_password=_PASSWORD, new_password=_NEW_PASSWORD
    )


async def _broadcast(tenant_key: str, marker: str) -> int:
    return await state.websocket_manager.broadcast_to_tenant(tenant_key, "project:updated", {"marker": marker})


async def _heartbeat() -> None:
    await state.websocket_manager.send_heartbeat()


def _cookie(token: str, origin: str | None = _SAME_ORIGIN) -> dict:
    headers = {"cookie": f"access_token={token}"}
    if origin is not None:
        headers["origin"] = origin
    return headers


@contextlib.contextmanager
def _live(monkeypatch, client_ip: str = "testclient"):
    from api.app import app

    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    with _no_op_lifespan(app), TestClient(app, client=(client_ip, 50000)) as client:
        db_manager = client.portal.call(_build_portal_db_manager)
        restore = _install_ws_app_state(db_manager)
        seeded = client.portal.call(_seed, db_manager)
        try:
            yield client, db_manager, seeded
        finally:
            client.portal.call(_cleanup_tenant, db_manager, seeded["tenant_key"])
            client.portal.call(db_manager.close_async)
            restore()


def _path() -> str:
    return f"/ws/sec0051-{uuid.uuid4().hex[:8]}"


def _assert_closed_by_server(ws) -> None:
    with pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    assert closed.value.code == 1008




def test_socket_closes_after_password_change(monkeypatch):
    with (
        _live(monkeypatch) as (client, db_manager, seeded),
        client.websocket_connect(_path(), headers=_cookie(_mint(seeded))) as ws,
    ):
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}

        client.portal.call(_change_password, db_manager, seeded)
        client.portal.call(_broadcast, seeded["tenant_key"], "after-password-change")

        _assert_closed_by_server(ws)


def test_reconnect_after_own_password_change_works(monkeypatch):
    with _live(monkeypatch) as (client, db_manager, seeded):
        with client.websocket_connect(_path(), headers=_cookie(_mint(seeded))) as ws:
            client.portal.call(_change_password, db_manager, seeded)
            client.portal.call(_broadcast, seeded["tenant_key"], "after-password-change")
            _assert_closed_by_server(ws)

        with client.websocket_connect(_path(), headers=_cookie(_mint(seeded, epoch=1))) as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert client.portal.call(_broadcast, seeded["tenant_key"], "fresh") == 1
            assert ws.receive_json()["data"]["marker"] == "fresh"


def test_socket_closes_after_logout(monkeypatch):
    with _live(monkeypatch) as (client, _db_manager, seeded):
        token = _mint(seeded)
        with client.websocket_connect(_path(), headers=_cookie(token)) as ws:
            response = client.post("/api/auth/logout", headers={"cookie": f"access_token={token}"})
            assert response.status_code == 200, response.text
            client.portal.call(_broadcast, seeded["tenant_key"], "after-logout")

            _assert_closed_by_server(ws)


def test_expired_token_socket_is_dropped_by_the_heartbeat(monkeypatch):
    monkeypatch.setattr(JWTManager, "ACCESS_TOKEN_EXPIRE_HOURS", 2 / 3600)
    with (
        _live(monkeypatch) as (client, _db_manager, seeded),
        client.websocket_connect(_path(), headers=_cookie(_mint(seeded))) as ws,
    ):
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}

        time.sleep(3.2)
        client.portal.call(_heartbeat)

        _assert_closed_by_server(ws)




@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example.test",
        "http://testserver:8080",
        "https://sibling.testserver",
        "null",
        None,
    ],
)
def test_cross_origin_cookie_handshake_is_refused(monkeypatch, origin):
    with _live(monkeypatch) as (client, _db_manager, seeded):
        with (
            pytest.raises(WebSocketDisconnect) as refused,
            client.websocket_connect(_path(), headers=_cookie(_mint(seeded), origin=origin)),
        ):
            pass
        assert refused.value.code == 1008


def test_same_origin_cookie_handshake_connects(monkeypatch):
    with (
        _live(monkeypatch) as (client, _db_manager, seeded),
        client.websocket_connect(_path(), headers=_cookie(_mint(seeded))) as ws,
    ):
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_configured_cors_origin_cookie_handshake_connects(monkeypatch):
    from fastapi.middleware.cors import CORSMiddleware

    from api.app import app

    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    listed = next(o for o in cors.kwargs["allow_origins"] if "testserver" not in o)
    with (
        _live(monkeypatch) as (client, _db_manager, seeded),
        client.websocket_connect(_path(), headers=_cookie(_mint(seeded), origin=listed)) as ws,
    ):
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_bearer_header_handshake_needs_no_origin(monkeypatch):
    with (
        _live(monkeypatch) as (client, _db_manager, seeded),
        client.websocket_connect(_path(), headers={"authorization": f"Bearer {_mint(seeded)}"}) as ws,
    ):
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}




class _RecordingWsManager:
    def __init__(self) -> None:
        self.disconnects: list[str] = []

    async def disconnect_tenant(self, tenant_key: str, **_) -> int:
        self.disconnects.append(tenant_key)
        return 0


@pytest.fixture
def spy_ws_manager(monkeypatch):
    spy = _RecordingWsManager()
    monkeypatch.setattr(state, "websocket_manager", spy)
    return spy


@pytest.mark.asyncio
async def test_change_password_closes_sockets_after_commit(db_manager, spy_ws_manager):
    seeded = await _seed(db_manager)

    await _change_password(db_manager, seeded)

    assert spy_ws_manager.disconnects == [seeded["tenant_key"]]


@pytest.mark.asyncio
async def test_user_service_password_update_closes_sockets(db_manager, spy_ws_manager):
    from giljo_mcp.services.user_service import UserService

    seeded = await _seed(db_manager)

    await UserService(db_manager=db_manager, tenant_key=seeded["tenant_key"]).update_user(
        seeded["user_id"], password=_NEW_PASSWORD
    )

    assert spy_ws_manager.disconnects == [seeded["tenant_key"]]


@pytest.mark.asyncio
async def test_pin_password_reset_closes_sockets(db_manager, spy_ws_manager):
    from giljo_mcp.models import User
    from giljo_mcp.services.user_auth_service import reset_password_via_pin

    seeded = await _seed(db_manager)
    async with db_manager.get_session_async(tenant_key=seeded["tenant_key"]) as session:
        user = await session.get(User, seeded["user_id"])
        await reset_password_via_pin(session, user, _NEW_PASSWORD)

    assert spy_ws_manager.disconnects == [seeded["tenant_key"]]


@pytest.mark.asyncio
async def test_api_key_revoke_closes_sockets(db_manager, spy_ws_manager):
    from giljo_mcp.services.auth_service import AuthService

    seeded = await _seed(db_manager)
    service = AuthService(db_manager)
    created = await service.create_api_key(seeded["user_id"], seeded["tenant_key"], "sec0051", ["*"])

    await service.revoke_api_key(created.id, seeded["user_id"])

    assert spy_ws_manager.disconnects == [seeded["tenant_key"]]




class _FakeSocket:
    def __init__(self, headers: dict | None = None, ip: str = "203.0.113.7") -> None:
        self.headers = headers or {}
        self.query_params: dict[str, str] = {}
        self.client = SimpleNamespace(host=ip)
        self.scope: dict = {}
        self.accepted = False
        self.closed_with: tuple[int, str] | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = (code, reason)


@pytest.mark.asyncio
async def test_handshake_validated_before_a_revocation_cannot_register_after_it():
    manager = WebSocketManager()
    validated_at = time.monotonic()
    await manager.disconnect_tenant("tk_revoked", publish_to_broker=False)

    from fastapi.exceptions import WebSocketException

    with pytest.raises(WebSocketException):
        await manager.connect(
            _FakeSocket(),
            "late-client",
            auth_context={"tenant_key": "tk_revoked", "authenticated_at": validated_at},
        )
    assert "late-client" not in manager.active_connections

    await manager.connect(
        _FakeSocket(), "fresh-client", auth_context={"tenant_key": "tk_revoked", "authenticated_at": time.monotonic()}
    )
    assert "fresh-client" in manager.active_connections




class _CountingDbManager:
    def __init__(self) -> None:
        self.opened = 0

    @contextlib.asynccontextmanager
    async def get_session_async(self, **_):
        self.opened += 1
        yield SimpleNamespace()


@pytest.mark.asyncio
async def test_anonymous_handshakes_do_not_each_take_a_db_connection(monkeypatch):
    async def _initialized(_db=None):
        return {"database_initialized": True}

    db_manager = _CountingDbManager()
    monkeypatch.setattr(auth_utils, "get_setup_state", _initialized)
    monkeypatch.setattr(state, "db_manager", db_manager)
    monkeypatch.setattr(state, "websocket_manager", WebSocketManager())

    for _ in range(3):
        ws = _FakeSocket()
        assert await ws_wiring.authenticate_ws_connection(ws, "anon", api_key=None, token=None) is None
        assert ws.closed_with is not None and ws.closed_with[0] == 1008

    assert db_manager.opened <= 1, f"{db_manager.opened} anonymous handshakes each opened a DB session"


@pytest.mark.asyncio
async def test_handshakes_past_the_per_ip_limit_are_refused(monkeypatch, real_rate_limiter):
    from fastapi import FastAPI

    from api.middleware.rate_limiter import RateLimitMiddleware

    app = FastAPI()
    app.user_middleware.insert(0, Middleware(RateLimitMiddleware, requests_per_minute=2))
    validated: list[str] = []

    async def _authenticate(websocket, db=None, **_):
        validated.append("x")
        return {"user": {"tenant_key": "tk_metered"}, "context": "normal"}

    monkeypatch.setattr(ws_wiring, "authenticate_websocket", _authenticate)
    monkeypatch.setattr(state, "db_manager", None)
    monkeypatch.setattr(state, "websocket_manager", WebSocketManager())

    ip = f"2001:db8::{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}"
    outcomes = []
    for n in range(3):
        ws = _FakeSocket(headers={"authorization": "Bearer jwt"}, ip=ip)
        ws.scope = {"app": app}
        outcomes.append(await ws_wiring.authenticate_ws_connection(ws, f"metered-{n}", api_key=None, token=None))

    assert outcomes[0] is not None and outcomes[1] is not None
    assert outcomes[2] is None, "the third handshake inside one minute was admitted"
    assert len(validated) == 2, "the refused handshake still reached credential validation"
    assert await RateLimiter(2).is_allowed(ip), "handshakes spent the address's request budget"




def _spend_request_budget(ip: str, limit: int):
    async def _spend() -> None:
        limiter = RateLimiter(limit)
        for _ in range(limit):
            await limiter.hit(ip)

    return _spend


def test_full_request_budget_does_not_refuse_the_handshake(monkeypatch, real_rate_limiter):
    from api.app import app
    from api.middleware.rate_limiter import RateLimitMiddleware

    limit = auth_utils.registered_middleware_kwargs(app, RateLimitMiddleware)["requests_per_minute"]
    ip = f"2001:db8:51c::{uuid.uuid4().hex[:4]}"
    with _live(monkeypatch, client_ip=ip) as (client, _db_manager, seeded):
        client.portal.call(_spend_request_budget(ip, limit))
        assert client.get("/api/v1/products/").status_code == 429, "the request budget is not full"

        with client.websocket_connect(_path(), headers={"authorization": f"Bearer {_mint(seeded)}"}) as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

        assert client.get("/api/v1/products/").status_code == 429, "the window rolled over mid-test"




@pytest.mark.asyncio
async def test_anonymous_handshake_without_a_database_is_admitted_and_never_latches(monkeypatch):
    monkeypatch.setattr(state, "db_manager", None)
    monkeypatch.setattr(state, "websocket_manager", WebSocketManager())
    monkeypatch.setattr(state, "connections", {})

    for n in range(2):
        ws = _FakeSocket()
        context = await ws_wiring.authenticate_ws_connection(ws, f"setup-{n}", api_key=None, token=None)

        assert context is not None, "a setup-mode handshake with no database was refused"
        assert context["context"] == "setup"
        assert ws.accepted and ws.closed_with is None
        assert state.ws_setup_complete is False, "the latch set without a database session"


class _FailingFirstSessionDbManager:

    def __init__(self, real) -> None:
        self._real = real
        self.opened = 0

    @contextlib.asynccontextmanager
    async def get_session_async(self, **kwargs):
        from sqlalchemy.exc import OperationalError

        self.opened += 1
        first = self.opened == 1
        async with self._real.get_session_async(**kwargs) as session:
            if first:

                async def _execute(*_args, **_kwargs):
                    raise OperationalError("SELECT setup_state", {}, ConnectionError("connection lost"))

                session.execute = _execute
            yield session


@pytest.mark.asyncio
async def test_setup_state_db_error_fails_closed_then_latches_without_reopening_the_db(db_manager, monkeypatch):
    seeded = await _seed(db_manager)
    failing = _FailingFirstSessionDbManager(db_manager)
    monkeypatch.setattr(state, "db_manager", failing)
    monkeypatch.setattr(state, "websocket_manager", WebSocketManager())
    monkeypatch.setattr(state, "connections", {})

    first = _FakeSocket()
    assert await ws_wiring.authenticate_ws_connection(first, "anon-1", api_key=None, token=None) is None
    assert first.closed_with is not None and first.closed_with[0] == 1008
    assert not first.accepted, "an anonymous handshake was admitted when the setup read failed"
    assert failing.opened == 1
    assert state.ws_setup_complete is True

    second = _FakeSocket()
    assert await ws_wiring.authenticate_ws_connection(second, "anon-2", api_key=None, token=None) is None
    assert second.closed_with is not None and second.closed_with[0] == 1008
    assert failing.opened == 1, "the latched anonymous handshake still opened a DB session"

    credentialed = _FakeSocket(headers={"authorization": f"Bearer {_mint(seeded)}"})
    context = await ws_wiring.authenticate_ws_connection(credentialed, "signed-in", api_key=None, token=None)
    assert context is not None, credentialed.closed_with
    assert context["tenant_key"] == seeded["tenant_key"]
    assert credentialed.accepted and credentialed.closed_with is None
    assert failing.opened == 2
