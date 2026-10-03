# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import bcrypt
import pytest
from fastapi import HTTPException


async def _seed_api_key(db_manager, *, key_hash_override: str | None = None) -> tuple[str, str, str]:
    from giljo_mcp.api_key_utils import hash_api_key
    from giljo_mcp.models.auth import APIKey, User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    raw_key = f"gk_{uuid4().hex}{uuid4().hex}"
    key_id = str(uuid4())
    key_hash = key_hash_override if key_hash_override is not None else hash_api_key(raw_key)

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"BE6060b Org {unique}",
            slug=f"be6060b-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"be6060b_user_{unique}",
            email=f"be6060b_{unique}@example.com",
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
            name=f"BE6060b Key {unique}",
            key_hash=key_hash,
            key_prefix=f"{raw_key[:12]}...",
            permissions=["*"],
            is_active=True,
            created_at=datetime.now(UTC),
        )
        session.add(api_key)
        await session.commit()

    return raw_key, tk, key_id


async def _authenticate(db_manager, raw_key: str):
    from api.endpoints.mcp_session import MCPSessionManager

    async with db_manager.get_session_async() as db:
        mgr = MCPSessionManager(db)
        return await mgr.authenticate_api_key(raw_key)




class TestNewKeySha256RoundTrip:
    @pytest.mark.asyncio
    async def test_new_mint_is_sha256_and_authenticates(self, db_manager):
        from sqlalchemy import select

        from giljo_mcp.api_key_utils import bust_api_key_cache
        from giljo_mcp.database import tenant_isolation_bypass
        from giljo_mcp.models.auth import APIKey

        raw_key, _tk, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)

        async with db_manager.get_session_async() as db:
            with tenant_isolation_bypass(db, reason="test read", models=(APIKey,)):
                row = (await db.execute(select(APIKey).where(APIKey.id == key_id))).scalar_one()
        assert row.key_hash.startswith("sha256$"), f"new key must store sha256$, got {row.key_hash[:8]!r}"
        assert not row.key_hash.startswith("$2b$")

        result = await _authenticate(db_manager, raw_key)
        assert result is not None, "a freshly minted sha256 key must authenticate"
        key_record, user = result
        assert key_record.id == key_id
        assert user is not None

    @pytest.mark.asyncio
    async def test_wrong_secret_same_prefix_rejected(self, db_manager):
        from giljo_mcp.api_key_utils import bust_api_key_cache

        raw_key, _tk, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)
        tampered = raw_key[:-4] + ("aaaa" if not raw_key.endswith("aaaa") else "bbbb")
        result = await _authenticate(db_manager, tampered)
        assert result is None, "a tampered secret must not authenticate"




class TestLegacyBcryptStillVerifies:
    @pytest.mark.asyncio
    async def test_legacy_bcrypt_positive_match(self, db_manager):
        from giljo_mcp.api_key_utils import bust_api_key_cache, hash_api_key
        from giljo_mcp.models.auth import APIKey, User
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.tenant import TenantManager

        tk = TenantManager.generate_tenant_key()
        unique = uuid4().hex[:8]
        raw_key = f"gk_{uuid4().hex}{uuid4().hex}"
        legacy_hash = bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        assert legacy_hash.startswith("$2b$"), "this case must store a real bcrypt hash"
        assert legacy_hash != hash_api_key(raw_key), "legacy format must differ from the new sha256 format"
        key_id = str(uuid4())

        async with db_manager.get_session_async() as session:
            org = Organization(
                name=f"BE6060b Legacy {unique}", slug=f"be6060b-legacy-{unique}", tenant_key=tk, is_active=True
            )
            session.add(org)
            await session.flush()
            user = User(
                username=f"be6060b_legacy_{unique}",
                email=f"be6060b_legacy_{unique}@example.com",
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
                    id=key_id,
                    tenant_key=tk,
                    user_id=user.id,
                    name=f"BE6060b Legacy Key {unique}",
                    key_hash=legacy_hash,
                    key_prefix=f"{raw_key[:12]}...",
                    permissions=["*"],
                    is_active=True,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

        bust_api_key_cache(key_id)
        result = await _authenticate(db_manager, raw_key)
        assert result is not None, "a legacy bcrypt key must still authenticate (no row rewrite)"
        assert result[0].id == key_id




class TestDowngradeFailsClosed:
    def test_old_bcrypt_only_verify_raises_on_sha256(self):
        from giljo_mcp.api_key_utils import hash_api_key

        raw_key = f"gk_{uuid4().hex}"
        sha_hash = hash_api_key(raw_key)
        with pytest.raises(ValueError):
            bcrypt.checkpw(raw_key.encode("utf-8"), sha_hash.encode("utf-8"))

    def test_verify_fails_closed_on_a_sha256_row(self):
        from giljo_mcp.api_key_utils import hash_api_key, verify_api_key

        raw_key = f"gk_{uuid4().hex}"
        assert verify_api_key(raw_key, hash_api_key(raw_key)) is True
        assert verify_api_key(raw_key, "$2b$12$not-a-real-bcrypt-hash") is False




class TestFallbackNeedsPrefixHit:
    @pytest.mark.asyncio
    async def test_no_prefix_match_skips_all_verification(self, db_manager, monkeypatch):
        from giljo_mcp import api_key_utils

        await _seed_api_key(db_manager)

        calls = {"n": 0}
        real_verify = api_key_utils.verify_api_key

        def _counting_verify(api_key: str, key_hash: str) -> bool:
            calls["n"] += 1
            return real_verify(api_key, key_hash)

        monkeypatch.setattr(api_key_utils, "verify_api_key", _counting_verify)

        no_match = f"gk_{uuid4().hex}{uuid4().hex}"
        result = await _authenticate(db_manager, no_match)
        assert result is None, "a key with no prefix match must not authenticate"
        assert calls["n"] == 0, (
            f"verify ran {calls['n']} time(s) without a key_prefix hit — the SQL prefix "
            "filter must gate ALL verification (bcrypt/sha256 CPU-DoS guard)"
        )




def _unique_public_ip() -> str:
    return f"2001:db8::{uuid4().hex[:4]}:{uuid4().hex[:4]}"


def _freeze_rate_limit_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.middleware import auth_rate_limiter as _arl

    frozen = float((int(_arl.time.time()) // 60) * 60)
    monkeypatch.setattr(_arl.time, "time", lambda: frozen)


def _request_with_ip(ip: str):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [],
        "query_string": b"",
        "client": (ip, 12345),
        "server": ("api.example.test", 443),
        "scheme": "https",
    }
    return Request(scope)


class TestFailedAuthRateLimit:
    @pytest.fixture(autouse=True)
    def _real_limiter(self, real_auth_rate_limiter):
        return

    @pytest.mark.asyncio
    async def test_failed_auth_429_engages_per_ip(self, monkeypatch):
        from api.middleware.auth_rate_limiter import enforce_api_key_auth_failure
        from api.middleware.auth_rate_limits import limit_for

        _freeze_rate_limit_clock(monkeypatch)

        limit = limit_for("api_key_auth_failed")
        req = _request_with_ip(_unique_public_ip())

        for _ in range(limit):
            await enforce_api_key_auth_failure(req)

        with pytest.raises(HTTPException) as exc:
            await enforce_api_key_auth_failure(req)
        assert exc.value.status_code == 429, "over-budget failed auth must raise 429"
        assert "Retry-After" in (exc.value.headers or {}), "429 must carry Retry-After"

        await enforce_api_key_auth_failure(_request_with_ip(_unique_public_ip()))

    @pytest.mark.asyncio
    async def test_mcp_transport_throttles_spray_but_not_valid_key(self, db_manager, monkeypatch):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from api.middleware.auth_rate_limits import limit_for

        _freeze_rate_limit_clock(monkeypatch)

        ip = _unique_public_ip()
        valid_key, _tk, key_id = await _seed_api_key(db_manager)
        from giljo_mcp.api_key_utils import bust_api_key_cache

        bust_api_key_cache(key_id)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            limit = limit_for("api_key_auth_failed")

            for _ in range(limit):
                status, _h, _b = await _drive_mcp(MCPAuthMiddleware, ip=ip, api_key=f"gk_{uuid4().hex}{uuid4().hex}")
                assert status == 401, f"a bad key must 401, got {status}"

            status, headers, _b = await _drive_mcp(MCPAuthMiddleware, ip=ip, api_key=f"gk_{uuid4().hex}{uuid4().hex}")
            assert status == 429, f"over-budget IP must be throttled with 429, got {status}"
            assert "retry-after" in headers, "429 must carry retry-after"

            status, _h, _b = await _drive_mcp(MCPAuthMiddleware, ip=ip, api_key=valid_key)
            assert status == 200, (
                f"a valid key from a throttled IP must still authenticate (failures throttle, not success), got {status}"
            )
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_window_boundary_resets_counter_is_why_clock_is_frozen(self, monkeypatch):
        from api.middleware import auth_rate_limiter as _arl
        from api.middleware.auth_rate_limiter import enforce_api_key_auth_failure
        from api.middleware.auth_rate_limits import limit_for

        limit = limit_for("api_key_auth_failed")
        req = _request_with_ip(_unique_public_ip())

        w1 = float((int(_arl.time.time()) // 60) * 60)
        monkeypatch.setattr(_arl.time, "time", lambda: w1)
        for _ in range(limit):
            await enforce_api_key_auth_failure(req)
        with pytest.raises(HTTPException) as exc:
            await enforce_api_key_auth_failure(req)
        assert exc.value.status_code == 429, "in-window over-budget must raise 429"

        w2 = w1 + 60.0
        monkeypatch.setattr(_arl.time, "time", lambda: w2)
        await enforce_api_key_auth_failure(req)


class _InnerOk:

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})


async def _drive_mcp(middleware_cls, *, ip: str, api_key: str) -> tuple[int, dict[str, str], bytes]:
    mw = middleware_cls(app=_InnerOk())
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        }
    ).encode("utf-8")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "method": "POST",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": [(b"x-api-key", api_key.encode()), (b"content-type", b"application/json")],
        "client": (ip, 12345),
        "server": ("api.example.test", 443),
        "scheme": "https",
        "root_path": "",
    }
    captured: dict = {"code": 0, "headers": {}, "body": bytearray()}
    sent = {"done": False}

    async def receive() -> dict:
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured["code"] = message["status"]
            for k, v in message.get("headers", []):
                captured["headers"][(k.decode() if isinstance(k, bytes) else k).lower()] = (
                    v.decode() if isinstance(v, bytes) else v
                )
        elif message["type"] == "http.response.body":
            captured["body"].extend(message.get("body", b""))

    await mw(scope, receive, send)
    return captured["code"], captured["headers"], bytes(captured["body"])
