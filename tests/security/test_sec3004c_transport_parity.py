# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-3004c — transport parity at the REAL layer (WebSocket + MCP middleware).

After the consolidation every transport routes through ``validate_principal``,
so the contract matrix must hold when exercised through the ACTUAL transport
entry points — not a helper (the BE-5042 lesson). This file drives:

- the real WebSocket handshake ``authenticate_websocket`` (the ``/ws`` upgrade
  auth), and
- the real ``MCPAuthMiddleware`` ASGI app (driven exactly like a production
  POST /mcp client).

Two-sided throughout, and it deliberately asserts the DRIFT that step c closes:
WebSocket auth previously enforced NEITHER jti-revocation NOR is_active (for
both JWT and API-key); it now rejects revoked tokens, deactivated users, and
API keys whose owner was deactivated — while valid credentials still connect.

Parallel-safe: unique tenant/user per test, revocation + verdict caches cleared
around mutate steps, commit-capable ``db_manager``. No module-level state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import pytest
from fastapi import HTTPException, WebSocketException

from api.middleware.auth_rate_limits import limit_for
from giljo_mcp.api_key_utils import clear_api_key_verify_cache, get_key_prefix, hash_api_key
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.services.oauth_revocation_service import (
    clear_revocation_cache,
    revoke_dashboard_access_jwt,
    revoke_token,
)


_CANONICAL_AUD = "http://test/mcp"


@pytest.fixture
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "sec3004c_" + "parity_secret")  # concat: public gitleaks defang
    return "sec3004c_parity_secret"


async def _seed_user(db_manager, *, is_active: bool = True) -> tuple[str, str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"3004c {unique}", slug=f"c3004-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"c3004_user_{unique}",
                email=f"c3004_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=is_active,
            )
        )
        await session.commit()
    return user_id, f"c3004_user_{unique}", tk


async def _seed_api_key(db_manager, *, user_active: bool = True) -> tuple[str, str]:
    from giljo_mcp.models.auth import APIKey, User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    raw_key = f"gk_{uuid4().hex}{uuid4().hex}"
    user_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"3004c key {unique}", slug=f"c3004-key-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"c3004_keyuser_{unique}",
                email=f"c3004_key_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=user_active,
            )
        )
        await session.flush()
        session.add(
            APIKey(
                id=str(uuid4()),
                tenant_key=tk,
                user_id=user_id,
                name=f"3004c Key {unique}",
                key_hash=hash_api_key(raw_key),
                key_prefix=get_key_prefix(raw_key),
                permissions=["*"],
                is_active=True,
                created_at=datetime.now(UTC),
                expires_at=None,
            )
        )
        await session.commit()
    return raw_key, tk


class _FakeWebSocket:
    """Minimal WebSocket stand-in: credentials via query params only.

    ``client``/``base_url`` are needed since BE-8000h: a failed API-key
    validation now runs the shared per-IP auth-failure throttle
    (``enforce_api_key_auth_failure``), which reads both off the request-like
    object. The WS parity tests here authenticate valid/one-shot credentials
    and are not meant to be throttled — the global ``_auth_rate_limit_test_bypass``
    fixture (SEC-9227 H4) keeps the limiter's explicit test bypass ON for them.
    (``base_url`` is now inert for that decision — it used to carry the
    ``http://test`` sentinel; the throttle behavior itself is covered in
    BE-6060b/BE-8000h's dedicated regression tests, not here.)
    """

    def __init__(self, *, token: str | None = None, api_key: str | None = None) -> None:
        self.query_params: dict[str, str] = {}
        if token:
            self.query_params["token"] = token
        if api_key:
            self.query_params["api_key"] = api_key
        self.headers: dict[str, str] = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.base_url = "http://test/ws"


# ---------------------------------------------------------------------------
# WebSocket handshake (transport #3) — real authenticate_websocket
# ---------------------------------------------------------------------------


class TestWebSocketParity:
    @pytest.mark.asyncio
    async def test_valid_jwt_authenticates(self, db_manager, jwt_secret):
        from api.auth_utils import authenticate_websocket

        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = JWTManager.create_access_token(user_id=user_id, username=username, role="developer", tenant_key=tk)
        async with db_manager.get_session_async() as db:
            result = await authenticate_websocket(_FakeWebSocket(token=token), db=db)
        assert result["authenticated"] is True
        assert result["user"]["tenant_key"] == tk
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_revoked_jwt_rejected(self, db_manager, jwt_secret):
        # DRIFT CLOSED: the WS handshake now enforces jti-revocation.
        from api.auth_utils import authenticate_websocket

        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = JWTManager.create_access_token(user_id=user_id, username=username, role="developer", tenant_key=tk)
        async with db_manager.get_session_async() as db:
            await revoke_dashboard_access_jwt(db, token=token)
            await db.commit()
        clear_revocation_cache()
        async with db_manager.get_session_async() as db:
            with pytest.raises(WebSocketException):
                await authenticate_websocket(_FakeWebSocket(token=token), db=db)
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_deactivated_user_jwt_rejected(self, db_manager, jwt_secret):
        # DRIFT CLOSED: the WS handshake now enforces is_active for JWTs.
        from api.auth_utils import authenticate_websocket

        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager, is_active=False)
        token = JWTManager.create_access_token(user_id=user_id, username=username, role="developer", tenant_key=tk)
        async with db_manager.get_session_async() as db:
            with pytest.raises(WebSocketException):
                await authenticate_websocket(_FakeWebSocket(token=token), db=db)
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_valid_api_key_authenticates(self, db_manager):
        from api.auth_utils import authenticate_websocket

        clear_api_key_verify_cache()
        raw_key, tk = await _seed_api_key(db_manager)
        async with db_manager.get_session_async() as db:
            result = await authenticate_websocket(_FakeWebSocket(api_key=raw_key), db=db)
        assert result["authenticated"] is True
        assert result["user"]["tenant_key"] == tk
        clear_api_key_verify_cache()

    @pytest.mark.asyncio
    async def test_api_key_with_deactivated_user_rejected(self, db_manager):
        # DRIFT CLOSED: WS API-key auth previously never checked the owner's
        # is_active; it now rejects a key whose user was deactivated.
        from api.auth_utils import authenticate_websocket

        clear_api_key_verify_cache()
        raw_key, _tk = await _seed_api_key(db_manager, user_active=False)
        async with db_manager.get_session_async() as db:
            with pytest.raises(WebSocketException):
                await authenticate_websocket(_FakeWebSocket(api_key=raw_key), db=db)
        clear_api_key_verify_cache()


# ---------------------------------------------------------------------------
# MCP middleware (transport #4) — real MCPAuthMiddleware ASGI drive
# ---------------------------------------------------------------------------


async def _drive_mcp(middleware_cls, *, token: str, db_manager) -> tuple[int, bool]:
    """POST /mcp tools/list through the real MCPAuthMiddleware; return (status, inner_called)."""
    inner_called = {"flag": False}

    async def inner_app(scope, receive, send) -> None:
        inner_called["flag"] = True
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})

    mw = middleware_cls(inner_app)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "method": "POST",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"host", b"test"),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
    }
    captured = {"code": 0}
    body_sent = {"done": False}

    async def receive() -> dict:
        if body_sent["done"]:
            return {"type": "http.disconnect"}
        body_sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured["code"] = message["status"]

    await mw(scope, receive, send)
    return captured["code"], inner_called["flag"]


def _unique_ip() -> str:
    """An RFC 3849 (2001:db8::/32) documentation IPv6 -- non-loopback, unique
    per call so the per-IP auth-failure limiter buckets never collide across
    xdist workers/tests."""
    return f"2001:db8::{uuid4().hex[:4]}:{uuid4().hex[:4]}"


def _freeze_rate_limit_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the limiter's fixed-window clock to the START of the current 60s
    bucket (BE-6087; see ``test_be6060b_api_key_sha256.py`` for the full
    boundary-flake rationale). ``monkeypatch`` auto-reverts at teardown."""
    from api.middleware import auth_rate_limiter as _arl

    frozen = float((int(_arl.time.time()) // 60) * 60)
    monkeypatch.setattr(_arl.time, "time", lambda: frozen)


class _FakeRestRequest:
    """Minimal Request stand-in for driving ``get_current_user`` directly.

    TSK-9021 (REST parity with BE-8000h/BE-6060b): a failed X-API-Key auth now
    runs the shared per-IP auth-failure throttle (``enforce_api_key_auth_failure``),
    which reads ``client``/``headers``/``base_url`` off the request-like object,
    same as the WS handshake stand-in above. This class drives the REAL throttle,
    so it opts out of the global test bypass via ``real_auth_rate_limiter``
    (SEC-9227 H4). (``base_url`` is now inert for that decision — it used to
    carry the ``http://test`` sentinel.)
    """

    def __init__(self, *, ip: str) -> None:
        self.client = SimpleNamespace(host=ip)
        self.headers: dict[str, str] = {}
        self.base_url = f"https://{ip}/"
        self.url = SimpleNamespace(path="/api/products")


# ---------------------------------------------------------------------------
# REST dependency (transport #1) — real get_current_user, TSK-9021
# ---------------------------------------------------------------------------


class TestRestParity:
    @pytest.fixture(autouse=True)
    def _real_limiter(self, real_auth_rate_limiter):
        """SEC-9227 (H4): this class asserts the REST failed-auth throttle fires,
        so keep the global test-bypass OFF for its tests."""
        return

    @pytest.mark.asyncio
    async def test_repeated_bad_api_key_over_rest_trips_lockout(self, db_session, monkeypatch):
        """``limit`` bad X-API-Keys over REST are plain 401 rejections; the
        (limit+1)th must be the THROTTLED 429 -- proving the REST dependency
        now throttles failed API-key auth same as WS/MCP (BE-8000h/BE-6060b)."""
        from giljo_mcp.auth.dependencies import get_current_user

        _freeze_rate_limit_clock(monkeypatch)
        ip = _unique_ip()
        limit = limit_for("api_key_auth_failed")

        for _ in range(limit):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(
                    request=_FakeRestRequest(ip=ip),
                    access_token=None,
                    x_api_key=f"gk_{uuid4().hex}{uuid4().hex}",
                    authorization=None,
                    db=db_session,
                )
            assert exc.value.status_code == 401, "must not throttle before the budget is exhausted"

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                request=_FakeRestRequest(ip=ip),
                access_token=None,
                x_api_key=f"gk_{uuid4().hex}{uuid4().hex}",
                authorization=None,
                db=db_session,
            )
        assert exc.value.status_code == 429, "the over-budget attempt must be throttled, not just rejected"

    @pytest.mark.asyncio
    async def test_valid_api_key_from_throttled_ip_still_authenticates(self, db_manager, monkeypatch):
        """Two-sided (WO mandate): a VALID key from the SAME (now-throttled) IP
        must still authenticate over REST -- only failures count against the
        budget, never the happy path."""
        from giljo_mcp.auth.dependencies import get_current_user

        _freeze_rate_limit_clock(monkeypatch)
        ip = _unique_ip()
        limit = limit_for("api_key_auth_failed")
        raw_key, tk = await _seed_api_key(db_manager)

        async with db_manager.get_session_async() as db:
            # Exhaust the budget with bad keys from this IP first (401s, then a 429).
            for _ in range(limit + 1):
                with pytest.raises(HTTPException):
                    await get_current_user(
                        request=_FakeRestRequest(ip=ip),
                        access_token=None,
                        x_api_key=f"gk_{uuid4().hex}{uuid4().hex}",
                        authorization=None,
                        db=db,
                    )

            # The IP is now throttled -- but the VALID key still authenticates.
            user = await get_current_user(
                request=_FakeRestRequest(ip=ip),
                access_token=None,
                x_api_key=raw_key,
                authorization=None,
                db=db,
            )

        assert user.tenant_key == tk, "a valid key from a throttled IP must still authenticate"


class TestMcpParity:
    @pytest.mark.asyncio
    async def test_valid_then_revoked_jwt(self, db_manager, jwt_secret):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = JWTManager.create_access_token(
            user_id=user_id,
            username=username,
            role="developer",
            tenant_key=tk,
            audience=_CANONICAL_AUD,
            scope="mcp:read mcp:write",
        )
        prior = state.db_manager
        state.db_manager = db_manager
        try:
            # Happy: active, non-revoked JWT reaches the inner SDK app.
            status, inner = await _drive_mcp(MCPAuthMiddleware, token=token, db_manager=db_manager)
            assert status == 200, f"valid JWT must authenticate on /mcp, got {status}"
            assert inner is True

            # Revoke via the RFC 7009 path (verify_aud=False), the correct
            # revoker for an aud-bound MCP token; the dashboard-logout revoker
            # is for aud-less cookie tokens.
            async with db_manager.get_session_async() as db:
                await revoke_token(db, token=token)
                await db.commit()
            clear_revocation_cache()

            # Reject: the SAME token is now revoked — 401, inner never reached.
            status2, inner2 = await _drive_mcp(MCPAuthMiddleware, token=token, db_manager=db_manager)
            assert status2 == 401, f"revoked JWT must 401 on /mcp, got {status2}"
            assert inner2 is False
        finally:
            state.db_manager = prior
            clear_revocation_cache()
