# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-8000h regression -- WebSocket handshake auth-failure throttling.

``authenticate_websocket`` validated API-key credentials via the same
bcrypt-verify path as the REST/MCP transports, but on failure it never called
the shared per-IP failed-auth throttle (``enforce_api_key_auth_failure``,
BE-6060b) -- an attacker could brute-force API keys over the WS handshake
without ever tripping the lockout that already stops the same attack over
REST/MCP. This drives the REAL WS auth path
(``api.auth_utils.authenticate_websocket``), the failing layer, mirroring the
existing MCP-transport lockout coverage in
``test_be6060b_api_key_sha256.py::TestFailedAuthRateLimit``.

Two-sided (WO mandate): repeated bad keys from one IP trip the lockout AND a
VALID key from the SAME now-throttled IP still connects normally -- only
failures count against the budget, never the happy path.

xdist-safe: unique per-test client IP (a documentation-range IPv6, never
collides across workers), the limiter's fixed-window clock is frozen so a
-n6-contended worker cannot straddle a minute boundary mid-loop (BE-6087),
no module-level mutable state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import pytest
from fastapi import WebSocketException

from api.auth_utils import authenticate_websocket
from api.middleware.auth_rate_limits import limit_for
from giljo_mcp.api_key_utils import get_key_prefix, hash_api_key
from giljo_mcp.models.auth import APIKey, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


class _WsAtIp:
    """Minimal WebSocket stand-in carrying an API key and a controllable client IP.

    Mirrors what Starlette exposes to ``authenticate_websocket``
    (``query_params`` + a header mapping) plus the ``client``/``base_url``
    surface the shared rate limiter reads. ``base_url`` deliberately does NOT
    start with ``http://test`` -- that prefix is the limiter's test-bypass for
    unrelated REST-style suites, and this test needs the REAL throttle path
    to engage.
    """

    def __init__(self, *, api_key: str, ip: str) -> None:
        self.query_params: dict[str, str] = {"api_key": api_key}
        self.headers: dict[str, str] = {}
        self.client = SimpleNamespace(host=ip)
        self.base_url = f"https://{ip}/ws"
        self.url = SimpleNamespace(path="/ws")


def _unique_ip() -> str:
    """An RFC 3849 (2001:db8::/32) documentation IPv6 -- non-loopback, unique
    per call so the per-IP limiter buckets never collide across xdist
    workers/tests."""
    return f"2001:db8::{uuid4().hex[:4]}:{uuid4().hex[:4]}"


def _freeze_rate_limit_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the limiter's fixed-window clock to the START of the current 60s
    bucket (BE-6087; see ``test_be6060b_api_key_sha256.py`` for the full
    boundary-flake rationale). ``monkeypatch`` auto-reverts at teardown."""
    from api.middleware import auth_rate_limiter as _arl

    frozen = float((int(_arl.time.time()) // 60) * 60)
    monkeypatch.setattr(_arl.time, "time", lambda: frozen)


async def _seed_api_key(db_manager) -> tuple[str, str]:
    """Create org+user+active API key. Returns ``(raw_api_key, tenant_key)``."""
    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    raw_key = f"gk_{uuid4().hex}{uuid4().hex}"

    async with db_manager.get_session_async() as session:
        org = Organization(name=f"BE8000h {unique}", slug=f"be8000h-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()

        user = User(
            username=f"be8000h_user_{unique}",
            email=f"be8000h_{unique}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tk,
            role="developer",
            org_id=org.id,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        session.add(
            APIKey(
                tenant_key=tk,
                user_id=user.id,
                name=f"BE8000h Key {unique}",
                key_hash=hash_api_key(raw_key),
                key_prefix=get_key_prefix(raw_key),
                permissions=["*"],
                is_active=True,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    return raw_key, tk


class TestWebSocketAuthFailureThrottle:
    @pytest.fixture(autouse=True)
    def _real_limiter(self, real_auth_rate_limiter):
        """SEC-9227 (H4): this suite exercises the real WS auth-failure throttle,
        so keep the global test-bypass OFF for all its tests."""
        return

    @pytest.mark.asyncio
    async def test_repeated_bad_api_key_over_ws_trips_lockout(self, db_session, monkeypatch):
        """``limit`` bad keys over the WS handshake are plain 1008 rejections;
        the (limit+1)th must be the THROTTLED rejection specifically -- proven
        via the reason string, since a normal auth failure also raises 1008."""
        _freeze_rate_limit_clock(monkeypatch)
        ip = _unique_ip()
        limit = limit_for("api_key_auth_failed")

        for _ in range(limit):
            with pytest.raises(WebSocketException) as exc:
                await authenticate_websocket(_WsAtIp(api_key=f"gk_{uuid4().hex}{uuid4().hex}", ip=ip), db=db_session)
            assert exc.value.reason != "Too many requests", "must not throttle before the budget is exhausted"

        with pytest.raises(WebSocketException) as exc:
            await authenticate_websocket(_WsAtIp(api_key=f"gk_{uuid4().hex}{uuid4().hex}", ip=ip), db=db_session)
        assert exc.value.reason == "Too many requests", "the over-budget attempt must be throttled, not just rejected"

    @pytest.mark.asyncio
    async def test_valid_key_from_throttled_ip_still_connects(self, db_manager, monkeypatch):
        """Two-sided: a VALID key from the SAME (now-throttled) IP must still
        authenticate over WS -- only failures count against the budget."""
        _freeze_rate_limit_clock(monkeypatch)
        ip = _unique_ip()
        limit = limit_for("api_key_auth_failed")
        raw_key, tk = await _seed_api_key(db_manager)

        async with db_manager.get_session_async() as db:
            # Exhaust the budget with bad keys from this IP first.
            for _ in range(limit + 1):
                with pytest.raises(WebSocketException):
                    await authenticate_websocket(_WsAtIp(api_key=f"gk_{uuid4().hex}{uuid4().hex}", ip=ip), db=db)

            # The IP is now throttled -- but the VALID key still authenticates.
            result = await authenticate_websocket(_WsAtIp(api_key=raw_key, ip=ip), db=db)

        assert result["authenticated"] is True, "a valid key from a throttled IP must still authenticate"
        assert result["user"]["tenant_key"] == tk
