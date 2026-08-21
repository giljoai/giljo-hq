# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Regression tests for BE-6060a — MCP transport + auth hot-path hardening.

This boundary (``MCPAuthMiddleware`` + ``api_key_utils``) shipped the GET /mcp
SSE storm with ZERO tests; per CLAUDE.md the fix MUST add regression coverage
at the failing layer (the ASGI middleware + the cached verify path), not at a
unit layer that the production bug bypassed.

The five mandated guarantees (DoD):

1. ``TestGetReturns405``         — GET /mcp → 405, empty body, NO SSE retry hint
                                   and NOT ``text/event-stream``; ``Allow: POST, DELETE``.
2. ``TestNo3xxEverEmitted``      — no 3xx for /mcp on GET/POST/DELETE/OPTIONS
                                   (the 307 trap is why the bridge route exists).
3. ``TestPostBodyByteParity``    — the inner SDK app sees the POST body bytes
                                   unchanged after the ``_replay_receive`` repair.
4. ``TestRevokedKeyIs401``       — a revoked/deactivated key + a still-valid
                                   ``Mcp-Session-Id`` → 401 (a session id must
                                   NEVER become a standalone bearer credential).
5. ``TestBcryptOffLoopAndCached``— ≤1 sync ``verify_api_key`` per key per TTL
                                   window under a 100-request burst, and a
                                   thread-identity assertion proving every
                                   sync verify ran off the event loop
                                   (``asyncio.to_thread``). See the hash-format
                                   note below for what the fixture executes.

BE-6061 fold-in (REST dashboard X-API-Key path, ``get_current_user``):

6. ``TestDashboardApiKeyOffLoopAndCached`` — the dashboard X-API-Key dependency
                                   also verifies off-loop + caches: ≤1 sync
                                   verify per key per TTL under a 100-request
                                   burst with the same thread-identity assertion.
7. ``TestDashboardRevokedKeyBust`` — a revoked key on the dashboard path 401s
                                   once ``bust_api_key_cache`` fires, proving the
                                   shared cache-bust reaches this path too.

Hash-format note (BE-6060b; recorded by INF-9398 because the old timing
assertion was sized against the wrong branch). ``_seed_api_key`` stores
``hash_api_key()``, which since BE-6060b is ``sha256$<hex>``. So the
``verify_api_key`` these tests exercise takes the ``hmac.compare_digest``
branch -- microseconds -- NOT the ~250-400ms ``bcrypt.checkpw`` a legacy
``$2b$`` row would take. Both guarantees here are format-independent and hold
for either branch: at most one SYNC verify per key per TTL window, and that
verify never executing on the event loop. The off-loop hop exists so a legacy
bcrypt row cannot block the loop; since this fixture runs the cheap branch,
elapsed time proves nothing about it, which is why the tests assert WHERE the
verify ran rather than how long anything took.

Failing-layer discipline: every case drives the real ASGI middleware, the real
``MCPSessionManager.authenticate_api_key``, or the real
``auth.dependencies.get_current_user`` — the exact code path a production client
hits. xdist-safe: unique tenant_key + key per test, no module-level mutable
state, no ordering deps.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# ASGI drive harness (parameterized method — mirrors test_mcp_protocol_version)
# ---------------------------------------------------------------------------


class _CapturingInnerApp:
    """Minimal ASGI app that records whether the middleware reached it + the body."""

    def __init__(self, response_status: int = 200) -> None:
        self.called: bool = False
        self.body_seen: bytes = b""

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        message = await receive()
        self.body_seen = message.get("body", b"")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})


async def _drive_middleware(
    middleware,
    *,
    method: str,
    headers: list[tuple[bytes, bytes]],
    body: bytes = b"",
) -> tuple[int, dict[str, str], bytes]:
    """Run a single ASGI request through ``middleware`` for the given method/body."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "method": method,
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
    }

    captured_status: dict = {"code": 0}
    captured_headers: dict[str, str] = {}
    captured_body = bytearray()
    body_sent = {"done": False}

    async def receive() -> dict:
        if body_sent["done"]:
            return {"type": "http.disconnect"}
        body_sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured_status["code"] = message["status"]
            for k, v in message.get("headers", []):
                key = k.decode("latin-1") if isinstance(k, bytes) else k
                val = v.decode("latin-1") if isinstance(v, bytes) else v
                captured_headers[key.lower()] = val
        elif message["type"] == "http.response.body":
            captured_body.extend(message.get("body", b""))

    await middleware(scope, receive, send)
    return captured_status["code"], captured_headers, bytes(captured_body)


def _jsonrpc_body(method: str, params: dict | None = None) -> bytes:
    payload: dict = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    return json.dumps(payload).encode("utf-8")


@pytest_asyncio.fixture
async def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    yield "test_secret_key"


async def _seed_api_key(db_manager) -> tuple[str, str, str]:
    """Create an org+user+api_key triplet.

    Returns ``(raw_api_key, tenant_key, api_key_id)``.
    """
    from giljo_mcp.api_key_utils import hash_api_key
    from giljo_mcp.models.auth import APIKey, User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    # Unique hex immediately after gk_ so get_key_prefix() (first 12 chars) is
    # unique per key. This keeps authenticate_api_key's prefix-narrowed
    # candidate set at exactly one row even though seed data is committed,
    # avoiding cross-test/cross-run accumulation under the shared prefix.
    raw_key = f"gk_{uuid4().hex}{uuid4().hex}"
    key_id = str(uuid4())

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"BE6060a Org {unique}",
            slug=f"be6060a-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"be6060a_user_{unique}",
            email=f"be6060a_{unique}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tk,
            role="developer",
            org_id=org.id,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        api_key = APIKey(
            id=key_id,
            tenant_key=tk,
            user_id=user.id,
            name=f"BE6060a Key {unique}",
            key_hash=hash_api_key(raw_key),
            key_prefix=f"{raw_key[:12]}...",
            permissions=["*"],
            is_active=True,
            created_at=datetime.now(UTC),
        )
        session.add(api_key)
        await session.commit()

    return raw_key, tk, key_id


# ---------------------------------------------------------------------------
# 1) GET /mcp → 405 pre-auth, no SSE retry hint
# ---------------------------------------------------------------------------


class TestGetReturns405:
    """GET /mcp must return 405 BEFORE auth, with no SSE retry hint."""

    @pytest.mark.asyncio
    async def test_get_returns_405_empty_body_no_sse_hint(self):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)

        status, headers, body = await _drive_middleware(
            mw,
            method="GET",
            headers=[(b"accept", b"text/event-stream")],
        )

        assert status == 405, f"GET /mcp must be 405, got {status}"
        assert inner.called is False, "405 must short-circuit before the inner SDK app"
        # Empty (or trivially short) body — definitely not an SSE stream.
        assert b"retry:" not in body, "405 body must NOT carry an SSE `retry:` field"
        assert b"data:" not in body, "405 body must NOT be an SSE event stream"
        content_type = headers.get("content-type", "")
        assert "text/event-stream" not in content_type, (
            f"405 must NOT be text/event-stream (would trigger client re-poll): {content_type!r}"
        )

    @pytest.mark.asyncio
    async def test_get_405_advertises_allowed_methods(self):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)

        _status, headers, _body = await _drive_middleware(
            mw,
            method="GET",
            headers=[],
        )

        allow = headers.get("allow", "")
        allowed = {m.strip().upper() for m in allow.split(",") if m.strip()}
        assert "POST" in allowed, f"Allow header must list POST: {allow!r}"
        assert "DELETE" in allowed, f"Allow header must list DELETE (session terminate): {allow!r}"
        assert "GET" not in allowed, f"Allow header must NOT list GET (that's what we reject): {allow!r}"

    @pytest.mark.asyncio
    async def test_get_405_precedes_auth(self):
        """An authless GET still gets 405 — proves the branch is pre-auth (not a 401)."""
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)

        status, _headers, _body = await _drive_middleware(mw, method="GET", headers=[])
        assert status == 405, f"405 (method) must win over 401 (no creds), got {status}"


# ---------------------------------------------------------------------------
# 2) No 3xx EVER on /mcp for any method
# ---------------------------------------------------------------------------


class TestNo3xxEverEmitted:
    """The middleware must never emit a 3xx for /mcp on any method."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE", "OPTIONS"])
    async def test_no_redirect_status(self, method):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)

        body = _jsonrpc_body("tools/list") if method in ("POST", "DELETE") else b""
        status, _headers, _body = await _drive_middleware(
            mw,
            method=method,
            headers=[(b"content-type", b"application/json")],
            body=body,
        )

        assert not (300 <= status < 400), (
            f"/mcp {method} emitted a 3xx ({status}); the 307 trap is exactly why the bridge route exists"
        )


# ---------------------------------------------------------------------------
# 3) POST body byte-parity (the _replay_receive repair must not corrupt the body)
# ---------------------------------------------------------------------------


class TestPostBodyByteParity:
    """The inner SDK app must observe the POST body bytes unchanged after replay."""

    @pytest.mark.asyncio
    async def test_inner_app_sees_unchanged_body(self, db_manager, jwt_env):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        raw_key, _tenant_key, _key_id = await _seed_api_key(db_manager)
        original_body = _jsonrpc_body(
            "initialize",
            params={"protocolVersion": "2025-06-18", "capabilities": {}, "marker": uuid4().hex},
        )

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            inner = _CapturingInnerApp()
            mw = MCPAuthMiddleware(app=inner)

            status, _headers, _body = await _drive_middleware(
                mw,
                method="POST",
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"content-type", b"application/json"),
                ],
                body=original_body,
            )

            assert status == 200, f"valid initialize returned {status}"
            assert inner.called is True, "auth must reach inner app on valid key"
            assert inner.body_seen == original_body, (
                "inner SDK app saw a DIFFERENT body than was sent — _replay_receive corrupted the stream"
            )
        finally:
            state.db_manager = prior_db


# ---------------------------------------------------------------------------
# 4) Revoked key + valid session id → 401 (session id is not a bearer credential)
# ---------------------------------------------------------------------------


class TestRevokedKeyIs401:
    """A deactivated key must fail auth even when a valid Mcp-Session-Id is presented."""

    @pytest.mark.asyncio
    async def test_revoked_key_with_valid_session_id_returns_401(self, db_manager, jwt_env):
        from sqlalchemy import update

        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.api_key_utils import bust_api_key_cache
        from giljo_mcp.database import tenant_isolation_bypass
        from giljo_mcp.models.auth import APIKey

        raw_key, _tenant_key, key_id = await _seed_api_key(db_manager)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            # Step 1: initialize to mint a real session id while the key is valid.
            inner = _CapturingInnerApp()
            mw = MCPAuthMiddleware(app=inner)
            _status, init_headers, _body = await _drive_middleware(
                mw,
                method="POST",
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body(
                    "initialize",
                    params={"protocolVersion": "2025-06-18", "capabilities": {}},
                ),
            )
            session_id = init_headers.get("mcp-session-id")
            assert session_id, "initialize must mint a session id for this test to be meaningful"

            # Step 2: revoke (deactivate) the key + bust the verdict cache.
            async with db_manager.get_session_async() as session:
                with tenant_isolation_bypass(session, reason="test revoke", models=(APIKey,)):
                    await session.execute(
                        update(APIKey).where(APIKey.id == key_id).values(is_active=False, revoked_at=datetime.now(UTC))
                    )
                    await session.commit()
            bust_api_key_cache(key_id)

            # Step 3: reuse the still-valid session id with the now-revoked key.
            inner2 = _CapturingInnerApp()
            mw2 = MCPAuthMiddleware(app=inner2)
            status, _headers, _body = await _drive_middleware(
                mw2,
                method="POST",
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"mcp-protocol-version", b"2025-06-18"),
                    (b"mcp-session-id", session_id.encode("ascii")),
                    (b"content-type", b"application/json"),
                ],
                body=_jsonrpc_body("tools/list"),
            )

            assert status == 401, (
                f"revoked key + valid session id must be 401 (session id is NOT a bearer credential), got {status}"
            )
            assert inner2.called is False, "a revoked key must never reach the inner SDK app"
        finally:
            state.db_manager = prior_db


# ---------------------------------------------------------------------------
# INF-9478: a manual monotonic clock for the two absorption proofs.
#
# The count assertion in both burst tests ("the burst adds ZERO further sync
# verifies") was correct only while the burst FINISHED INSIDE the verdict
# cache's real-time TTL window. That dependency was invisible: it reads as a
# pure count, and nothing in the test mentions time. Measured on an idle box the
# warm+100 burst takes ~6-7s against a 60s window (_VERIFY_CACHE_TTL_POSITIVE),
# so it held with ~9x to spare -- until three concurrent -n 6 suites, one more
# than the two INF-9398 was validated against, stretched it past the window. The
# entry then expires mid-burst, ONE HONEST extra verify lands, and the assertion
# fails while the cache is doing exactly what it was built to do.
#
# Driving the cache from a clock the test owns removes the elapsed-time term
# from the proof entirely, without weakening it: the count assertion still says
# "the cache absorbs every repeat", it just no longer also says "...provided the
# machine was fast enough". No production code changes -- api_key_utils reads
# ``time`` as a module global (its only three uses are time.monotonic()), which
# is the same seam this file already uses to count verify_api_key.
#
# NOT an xfail, a retry, a longer sleep or a serial marker: every one of those
# buys green by making the gate quieter. This one makes it deterministic.
#
# THE BOUNDARY OF THIS CLOCK, because the next reader will want to reuse it and
# it is narrower than it looks. It controls ``time``, which is three of the
# cache's FOUR clock reads. The fourth is ``datetime.now(UTC)`` in
# ``_verify_cache_put`` (api_key_utils.py:226), which caps a verdict's deadline
# at the key's own expiry -- and it reads REAL time regardless of anything here.
# It is unreachable in these two tests only because ``_seed_api_key`` sets no
# ``expires_at``, so the ``if expires_at is not None`` branch never runs. That is
# a property of the fixture, not of the patch. An absorption proof written for an
# EXPIRING key must handle that second clock, or it will silently depend on
# elapsed real time again -- the exact defect this comment sits above.
# ---------------------------------------------------------------------------


class _ManualClock:
    """Stands in for the ``time`` module global inside ``api_key_utils``.

    Only ``monotonic`` is provided because that is the module's entire use of
    ``time`` -- three calls, all ``time.monotonic()``, in ``_verify_cache_get``
    and ``_verify_cache_put``. Starts at the real reading so a verdict cached
    before the patch (by another test in the same worker process) keeps its
    relative deadline instead of being read as expired.
    """

    def __init__(self) -> None:
        self._now = time.monotonic()

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ---------------------------------------------------------------------------
# 5) bcrypt off-loop + cached: ≤1 sync verify per key per TTL window + lag probe
# ---------------------------------------------------------------------------


class TestBcryptOffLoopAndCached:
    """A 100-request burst must trigger ≤1 bcrypt verify, and every verify runs off-loop."""

    @pytest.mark.asyncio
    async def test_one_bcrypt_per_ttl_window_under_burst(self, db_manager, jwt_env, monkeypatch):
        from api.endpoints import mcp_session as mcp_session_mod
        from giljo_mcp import api_key_utils
        from giljo_mcp.api_key_utils import bust_api_key_cache, verify_api_key

        raw_key, _tenant_key, key_id = await _seed_api_key(db_manager)
        # Start from a clean verdict cache for this key.
        bust_api_key_cache(key_id)

        # This coroutine body runs ON the event loop, so its thread id IS the
        # loop thread's. See the off-loop assertion at the end of the test.
        loop_thread_id = threading.get_ident()

        call_count = {"n": 0}
        verify_thread_ids: list[int] = []
        real_verify = verify_api_key

        def _counting_verify(api_key: str, key_hash: str) -> bool:
            call_count["n"] += 1
            verify_thread_ids.append(threading.get_ident())
            return real_verify(api_key, key_hash)

        # Patch the sync verify at its definition module. verify_api_key_cached
        # resolves ``verify_api_key`` as a module global inside the to_thread
        # call, so patching here counts exactly the sync verifies -- and runs on
        # the thread each one executed on. (Which comparison branch that verify
        # takes is the hash-format note's business, not this test's.)
        monkeypatch.setattr(api_key_utils, "verify_api_key", _counting_verify)

        # INF-9478: drive the verdict cache's TTL from a clock this test owns,
        # patched at the same module global api_key_utils reads. Installed
        # BEFORE the warm auth so the entry's deadline is computed on it. The
        # burst below therefore cannot outrun the window no matter how loaded
        # the box is -- the window does not move unless this test moves it.
        clock = _ManualClock()
        monkeypatch.setattr(api_key_utils, "time", clock)

        async def _one_auth() -> None:
            async with db_manager.get_session_async() as db:
                mgr = mcp_session_mod.MCPSessionManager(db)
                result = await mgr.authenticate_api_key(raw_key)
                assert result is not None, "valid key must authenticate"

        # Warm the cache once. The candidate set is narrowed by key_prefix, so
        # other keys committed by sibling tests that share the gk_be6060a_
        # prefix also get verified-and-cached here — that's the realistic
        # multi-key-per-prefix production case. The invariant under test is
        # "≤1 bcrypt per key per TTL window", i.e. the burst adds ZERO further
        # bcrypt calls, not that the warm cost is globally 1.
        await _one_auth()
        warm_count = call_count["n"]
        assert warm_count >= 1, "first auth must run a real bcrypt verify"

        for _ in range(100):
            await _one_auth()

        burst_count = call_count["n"]
        assert burst_count == warm_count, (
            "a 100-request burst added "
            f"{burst_count - warm_count} bcrypt verifies on top of the warm cache — "
            "the verdict cache must absorb every repeat (≤1 bcrypt per key per TTL window)"
        )

        # INF-9478, second half: prove the WINDOW, and prove the clock above is
        # actually wired. A patch that silently failed to take would freeze
        # nothing and let the count assertion pass for the wrong reason -- on a
        # fast box it would pass either way, which is exactly how the elapsed-
        # time dependency stayed invisible for so long. Rolling the clock past
        # the TTL must expire the verdict and cost a fresh sync verify; if it
        # does not, this test is not driving the cache it claims to be driving.
        clock.advance(api_key_utils._VERIFY_CACHE_TTL_POSITIVE + 1.0)
        await _one_auth()
        assert call_count["n"] > burst_count, (
            "no further sync verify after the TTL window closed — either the "
            "verdict cache never expires, or this test's clock is not the one "
            "the cache reads and the absorption count above proved nothing"
        )
        # INF-9398: prove the off-loop guarantee STRUCTURALLY, by where the work
        # ran, not by how long the loop took to answer. This assertion reads the
        # same on an idle machine and under two concurrent -n 6 suites; the
        # event-loop-lag probe it replaces read machine load as if it were an
        # on-loop bcrypt and crashed xdist workers for it.
        #
        # _counting_verify replaces the module global that verify_api_key_cached
        # resolves INSIDE asyncio.to_thread, so it executes on whatever thread
        # the verify actually ran on. A regression that drops the to_thread hop
        # -- or hands it the wrong callable -- lands the sync verify back on the
        # loop thread and fails here, whichever hash branch it takes.
        assert verify_thread_ids, (
            "no sync verify was observed at all — the off-loop assertion below would pass vacuously"
        )
        on_loop = [t for t in verify_thread_ids if t == loop_thread_id]
        assert not on_loop, (
            f"{len(on_loop)} of {len(verify_thread_ids)} sync verify_api_key calls ran on the "
            f"event-loop thread ({loop_thread_id}) — the verify must run in a worker thread "
            "via asyncio.to_thread"
        )

    @pytest.mark.asyncio
    async def test_bust_forces_fresh_bcrypt(self, db_manager, jwt_env, monkeypatch):
        """After ``bust_api_key_cache`` the next auth must re-run the sync verify."""
        from api.endpoints import mcp_session as mcp_session_mod
        from giljo_mcp import api_key_utils
        from giljo_mcp.api_key_utils import bust_api_key_cache, verify_api_key

        raw_key, _tenant_key, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)

        call_count = {"n": 0}
        real_verify = verify_api_key

        def _counting_verify(api_key: str, key_hash: str) -> bool:
            call_count["n"] += 1
            return real_verify(api_key, key_hash)

        monkeypatch.setattr(api_key_utils, "verify_api_key", _counting_verify)
        monkeypatch.setattr(mcp_session_mod, "verify_api_key", _counting_verify, raising=False)

        async def _one_auth() -> None:
            async with db_manager.get_session_async() as db:
                mgr = mcp_session_mod.MCPSessionManager(db)
                await mgr.authenticate_api_key(raw_key)

        await _one_auth()
        assert call_count["n"] == 1, "first auth must run a real bcrypt verify"

        await _one_auth()
        assert call_count["n"] == 1, "second auth (cache hit) must NOT re-run bcrypt"

        bust_api_key_cache(key_id)
        await _one_auth()
        assert call_count["n"] == 2, "after a cache bust the next auth MUST re-run bcrypt"


# ---------------------------------------------------------------------------
# 6) BE-6061: REST dashboard X-API-Key auth (auth/dependencies.get_current_user)
#    inherits the same off-loop + cache-bust verify the /mcp transport uses.
#
# Failing layer = giljo_mcp.auth.dependencies.get_current_user (the FastAPI
# dependency every dashboard endpoint injects via get_current_active_user).
# Before BE-6061 this path called the SYNC verify_api_key (bcrypt) directly on
# the event loop on every request. These cases drive the REAL dependency.
# ---------------------------------------------------------------------------


class _StubRequest:
    """Minimal Request stand-in for get_current_user (reads .url.path + .client).

    TSK-9021: a failed X-API-Key auth now also runs the shared per-IP
    auth-failure throttle (``enforce_api_key_auth_failure``), which reads
    ``base_url`` off the request-like object. ``base_url`` starts with
    ``http://test`` so the limiter's existing test-bypass exempts this suite
    (it is testing bcrypt/cache behavior, not the throttle -- that has its
    own dedicated coverage in ``test_sec3004c_transport_parity.py``).
    """

    def __init__(self, path: str = "/api/me") -> None:
        self.url = type("_U", (), {"path": path})()
        self.client = None
        self.base_url = "http://test/api/me"


class TestDashboardApiKeyOffLoopAndCached:
    """get_current_user (dashboard X-API-Key) must verify off-loop + cache the verdict."""

    @pytest.mark.asyncio
    async def test_dashboard_one_bcrypt_per_ttl_window_under_burst(self, db_manager, jwt_env, monkeypatch):
        from giljo_mcp import api_key_utils
        from giljo_mcp.api_key_utils import bust_api_key_cache, verify_api_key
        from giljo_mcp.auth import dependencies as deps_mod

        raw_key, _tenant_key, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)

        # This coroutine body runs ON the event loop, so its thread id IS the
        # loop thread's. See the off-loop assertion at the end of the test.
        loop_thread_id = threading.get_ident()

        call_count = {"n": 0}
        verify_thread_ids: list[int] = []
        real_verify = verify_api_key

        def _counting_verify(api_key: str, key_hash: str) -> bool:
            call_count["n"] += 1
            verify_thread_ids.append(threading.get_ident())
            return real_verify(api_key, key_hash)

        # Patch the sync verify at its definition module — verify_api_key_cached
        # resolves it as a module global inside asyncio.to_thread, so this counts
        # exactly the sync verifies the dashboard path triggers, and records the
        # thread each one actually ran on.
        monkeypatch.setattr(api_key_utils, "verify_api_key", _counting_verify)

        # INF-9478: same manual clock as the /mcp twin, installed before the
        # warm auth for the same reason. Kept identical in shape to that one so
        # the two cannot drift.
        clock = _ManualClock()
        monkeypatch.setattr(api_key_utils, "time", clock)

        async def _one_auth() -> None:
            async with db_manager.get_session_async() as db:
                user = await deps_mod.get_current_user(
                    request=_StubRequest(),
                    access_token=None,
                    x_api_key=raw_key,
                    authorization=None,
                    db=db,
                )
                assert user is not None, "valid dashboard key must authenticate"

        await _one_auth()
        warm_count = call_count["n"]
        assert warm_count >= 1, "first dashboard auth must run a real bcrypt verify"

        for _ in range(100):
            await _one_auth()

        burst_count = call_count["n"]
        assert burst_count == warm_count, (
            "a 100-request dashboard burst added "
            f"{burst_count - warm_count} bcrypt verifies on top of the warm cache — "
            "the shared verdict cache must absorb every repeat (≤1 bcrypt per key per TTL)"
        )

        # INF-9478: same window proof + same wiring check as the /mcp twin.
        clock.advance(api_key_utils._VERIFY_CACHE_TTL_POSITIVE + 1.0)
        await _one_auth()
        assert call_count["n"] > burst_count, (
            "no further dashboard sync verify after the TTL window closed — "
            "either the shared verdict cache never expires, or this test's clock "
            "is not the one the cache reads and the count above proved nothing"
        )
        # INF-9398: same structural proof as the /mcp transport twin above —
        # assert WHERE each verify ran, never how long the loop took to answer.
        # Kept identical in shape to that one so the two cannot drift.
        assert verify_thread_ids, (
            "no sync verify was observed at all — the off-loop assertion below would pass vacuously"
        )
        on_loop = [t for t in verify_thread_ids if t == loop_thread_id]
        assert not on_loop, (
            f"{len(on_loop)} of {len(verify_thread_ids)} dashboard X-API-Key sync verify_api_key "
            f"calls ran on the event-loop thread ({loop_thread_id}) — the verify must run in a "
            "worker thread via asyncio.to_thread"
        )


class TestDashboardRevokedKeyBust:
    """A revoked dashboard key must 401 immediately once the shared cache is busted."""

    @pytest.mark.asyncio
    async def test_dashboard_revoked_key_is_401_after_bust(self, db_manager, jwt_env):
        from sqlalchemy import update

        from giljo_mcp.api_key_utils import bust_api_key_cache
        from giljo_mcp.auth import dependencies as deps_mod
        from giljo_mcp.database import tenant_isolation_bypass
        from giljo_mcp.models.auth import APIKey

        raw_key, _tenant_key, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)

        # Step 1: valid key authenticates and seeds a positive verdict in the cache.
        async with db_manager.get_session_async() as db:
            user = await deps_mod.get_current_user(
                request=_StubRequest(),
                access_token=None,
                x_api_key=raw_key,
                authorization=None,
                db=db,
            )
            assert user is not None, "pre-revoke dashboard auth must succeed"

        # Step 2: deactivate the key + bust the shared verdict cache (the exact two
        # operations AuthService._revoke_api_key_impl performs).
        async with db_manager.get_session_async() as db:
            with tenant_isolation_bypass(db, reason="test revoke", models=(APIKey,)):
                await db.execute(
                    update(APIKey).where(APIKey.id == key_id).values(is_active=False, revoked_at=datetime.now(UTC))
                )
                await db.commit()
        bust_api_key_cache(key_id)

        # Step 3: the revoked key must now be rejected — no stale positive survives.
        with pytest.raises(HTTPException) as exc_info:
            async with db_manager.get_session_async() as db:
                await deps_mod.get_current_user(
                    request=_StubRequest(),
                    access_token=None,
                    x_api_key=raw_key,
                    authorization=None,
                    db=db,
                )
        assert exc_info.value.status_code == 401, (
            "a revoked dashboard key must 401 once bust_api_key_cache fires — "
            "the cache-bust must reach this path, not only /mcp"
        )
