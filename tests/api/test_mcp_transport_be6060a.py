# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




class _CapturingInnerApp:

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
    from giljo_mcp.api_key_utils import hash_api_key
    from giljo_mcp.models.auth import APIKey, User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
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




class TestGetReturns405:

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
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)

        status, _headers, _body = await _drive_middleware(mw, method="GET", headers=[])
        assert status == 405, f"405 (method) must win over 401 (no creds), got {status}"




class TestNo3xxEverEmitted:

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




class TestPostBodyByteParity:

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




class TestRevokedKeyIs401:

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

            async with db_manager.get_session_async() as session:
                with tenant_isolation_bypass(session, reason="test revoke", models=(APIKey,)):
                    await session.execute(
                        update(APIKey).where(APIKey.id == key_id).values(is_active=False, revoked_at=datetime.now(UTC))
                    )
                    await session.commit()
            bust_api_key_cache(key_id)

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




class _ManualClock:

    def __init__(self) -> None:
        self._now = time.monotonic()

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds




class TestBcryptOffLoopAndCached:

    @pytest.mark.asyncio
    async def test_one_bcrypt_per_ttl_window_under_burst(self, db_manager, jwt_env, monkeypatch):
        from api.endpoints import mcp_session as mcp_session_mod
        from giljo_mcp import api_key_utils
        from giljo_mcp.api_key_utils import bust_api_key_cache, verify_api_key

        raw_key, _tenant_key, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)

        loop_thread_id = threading.get_ident()

        call_count = {"n": 0}
        verify_thread_ids: list[int] = []
        real_verify = verify_api_key

        def _counting_verify(api_key: str, key_hash: str) -> bool:
            call_count["n"] += 1
            verify_thread_ids.append(threading.get_ident())
            return real_verify(api_key, key_hash)

        monkeypatch.setattr(api_key_utils, "verify_api_key", _counting_verify)

        clock = _ManualClock()
        monkeypatch.setattr(api_key_utils, "time", clock)

        async def _one_auth() -> None:
            async with db_manager.get_session_async() as db:
                mgr = mcp_session_mod.MCPSessionManager(db)
                result = await mgr.authenticate_api_key(raw_key)
                assert result is not None, "valid key must authenticate"

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

        clock.advance(api_key_utils._VERIFY_CACHE_TTL_POSITIVE + 1.0)
        await _one_auth()
        assert call_count["n"] > burst_count, (
            "no further sync verify after the TTL window closed — either the "
            "verdict cache never expires, or this test's clock is not the one "
            "the cache reads and the absorption count above proved nothing"
        )
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




class _StubRequest:

    def __init__(self, path: str = "/api/me") -> None:
        self.url = type("_U", (), {"path": path})()
        self.client = None
        self.base_url = "http://test/api/me"


class TestDashboardApiKeyOffLoopAndCached:

    @pytest.mark.asyncio
    async def test_dashboard_one_bcrypt_per_ttl_window_under_burst(self, db_manager, jwt_env, monkeypatch):
        from giljo_mcp import api_key_utils
        from giljo_mcp.api_key_utils import bust_api_key_cache, verify_api_key
        from giljo_mcp.auth import dependencies as deps_mod

        raw_key, _tenant_key, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)

        loop_thread_id = threading.get_ident()

        call_count = {"n": 0}
        verify_thread_ids: list[int] = []
        real_verify = verify_api_key

        def _counting_verify(api_key: str, key_hash: str) -> bool:
            call_count["n"] += 1
            verify_thread_ids.append(threading.get_ident())
            return real_verify(api_key, key_hash)

        monkeypatch.setattr(api_key_utils, "verify_api_key", _counting_verify)

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

        clock.advance(api_key_utils._VERIFY_CACHE_TTL_POSITIVE + 1.0)
        await _one_auth()
        assert call_count["n"] > burst_count, (
            "no further dashboard sync verify after the TTL window closed — "
            "either the shared verdict cache never expires, or this test's clock "
            "is not the one the cache reads and the count above proved nothing"
        )
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

    @pytest.mark.asyncio
    async def test_dashboard_revoked_key_is_401_after_bust(self, db_manager, jwt_env):
        from sqlalchemy import update

        from giljo_mcp.api_key_utils import bust_api_key_cache
        from giljo_mcp.auth import dependencies as deps_mod
        from giljo_mcp.database import tenant_isolation_bypass
        from giljo_mcp.models.auth import APIKey

        raw_key, _tenant_key, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)

        async with db_manager.get_session_async() as db:
            user = await deps_mod.get_current_user(
                request=_StubRequest(),
                access_token=None,
                x_api_key=raw_key,
                authorization=None,
                db=db,
            )
            assert user is not None, "pre-revoke dashboard auth must succeed"

        async with db_manager.get_session_async() as db:
            with tenant_isolation_bypass(db, reason="test revoke", models=(APIKey,)):
                await db.execute(
                    update(APIKey).where(APIKey.id == key_id).values(is_active=False, revoked_at=datetime.now(UTC))
                )
                await db.commit()
        bust_api_key_cache(key_id)

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
