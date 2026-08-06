# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6060b regression — API-key format v2 (``sha256$`` for NEW keys only).

New API keys are stored as a fast, deterministic ``sha256$<hex>`` digest; legacy
keys remain bcrypt and keep verifying via the format-detecting verify path. No
migration, existing rows are NEVER rewritten.

Failing-layer discipline (CLAUDE.md): the behavior lives in ``api_key_utils``
(hash/verify) AND on the MCP auth boundary (``MCPSessionManager.
authenticate_api_key``) the production transport hits. These cases exercise both,
not just a unit layer the production bug would bypass.

DoD -> cases:
1. ``TestNewKeySha256RoundTrip``  — new mint stores ``sha256$`` and authenticates.
2. ``TestLegacyBcryptStillVerifies`` — a ``$2b$`` row still authenticates (fallback).
3. ``TestDowngradeFailsClosed``    — a ``sha256$`` hash fed to the OLD bcrypt-only
                                     verify raises, and the auth boundary swallows
                                     it -> None (fail closed, no exception leak).
4. ``TestFallbackNeedsPrefixHit``  — verify is unreachable without a key_prefix
                                     index hit (the bcrypt CPU-DoS gate).

xdist-safe: unique tenant_key + key per test, no module-level mutable state.
The ``TestFailedAuthRateLimit`` cases additionally FREEZE the limiter's
fixed-window clock (see ``_freeze_rate_limit_clock``) so a -n6-contended worker
cannot straddle a wall-clock minute boundary mid-loop (BE-6087).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import bcrypt
import pytest
from fastapi import HTTPException


async def _seed_api_key(db_manager, *, key_hash_override: str | None = None) -> tuple[str, str, str]:
    """Create org+user+api_key. Returns ``(raw_api_key, tenant_key, api_key_id)``.

    By default the stored ``key_hash`` is whatever ``hash_api_key`` produces (the
    new ``sha256$`` format). Pass ``key_hash_override`` to store a specific hash
    (e.g. a legacy bcrypt hash) for the legacy-fallback case.
    """
    from giljo_mcp.api_key_utils import hash_api_key
    from giljo_mcp.models.auth import APIKey, User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    # Unique hex right after gk_ so get_key_prefix() (first 12 chars) is unique per
    # key -> the prefix-narrowed candidate set is exactly one row even with
    # committed seed data, avoiding cross-test accumulation under a shared prefix.
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


# ---------------------------------------------------------------------------
# 1) New key: stored as sha256$ and authenticates through the boundary.
# ---------------------------------------------------------------------------


class TestNewKeySha256RoundTrip:
    @pytest.mark.asyncio
    async def test_new_mint_is_sha256_and_authenticates(self, db_manager):
        from sqlalchemy import select

        from giljo_mcp.api_key_utils import bust_api_key_cache
        from giljo_mcp.database import tenant_isolation_bypass
        from giljo_mcp.models.auth import APIKey

        raw_key, _tk, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)

        # The stored hash is the new fast format, not bcrypt.
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
        """A wrong secret never authenticates even though hashing is deterministic."""
        from giljo_mcp.api_key_utils import bust_api_key_cache

        raw_key, _tk, key_id = await _seed_api_key(db_manager)
        bust_api_key_cache(key_id)
        # Same gk_ prefix, different body -> prefix won't match the stored row, but
        # even if it did the sha256 compare fails. Use the real key's prefix region.
        tampered = raw_key[:-4] + ("aaaa" if not raw_key.endswith("aaaa") else "bbbb")
        result = await _authenticate(db_manager, tampered)
        assert result is None, "a tampered secret must not authenticate"


# ---------------------------------------------------------------------------
# 2) Legacy bcrypt row still verifies (format-detect fallback).
# ---------------------------------------------------------------------------


class TestLegacyBcryptStillVerifies:
    @pytest.mark.asyncio
    async def test_legacy_bcrypt_positive_match(self, db_manager):
        """The exact secret behind a legacy $2b$ row authenticates via fallback."""
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


# ---------------------------------------------------------------------------
# 3) Downgrade landmine: a sha256$ hash fed to the OLD bcrypt-only verify must
#    fail CLOSED at the boundary (no exception leakage).
# ---------------------------------------------------------------------------


class TestDowngradeFailsClosed:
    def test_old_bcrypt_only_verify_raises_on_sha256(self):
        """Documents WHY rows are never rewritten: old code raises on sha256$."""
        from giljo_mcp.api_key_utils import hash_api_key

        raw_key = f"gk_{uuid4().hex}"
        sha_hash = hash_api_key(raw_key)
        # The pre-BE-6060b verify_api_key was literally this single call.
        with pytest.raises(ValueError):
            bcrypt.checkpw(raw_key.encode("utf-8"), sha_hash.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_boundary_swallows_downgrade_exception(self, db_manager, monkeypatch):
        """Old verify on a sha256 row -> boundary returns None, never raises/leaks."""
        from giljo_mcp import api_key_utils
        from giljo_mcp.api_key_utils import bust_api_key_cache

        raw_key, _tk, key_id = await _seed_api_key(db_manager)  # stored as sha256$
        bust_api_key_cache(key_id)

        def _old_bcrypt_only_verify(api_key: str, key_hash: str) -> bool:
            # Exact pre-BE-6060b behavior: bcrypt.checkpw raises on a sha256 hash.
            return bcrypt.checkpw(api_key.encode("utf-8"), key_hash.encode("utf-8"))

        monkeypatch.setattr(api_key_utils, "verify_api_key", _old_bcrypt_only_verify)

        # Must NOT raise out of the boundary — the broad except returns None.
        result = await _authenticate(db_manager, raw_key)
        assert result is None, "a downgraded reader must fail closed (key silently invalid), not crash"


# ---------------------------------------------------------------------------
# 4) The verify path (any format) is unreachable without a key_prefix index hit.
# ---------------------------------------------------------------------------


class TestFallbackNeedsPrefixHit:
    @pytest.mark.asyncio
    async def test_no_prefix_match_skips_all_verification(self, db_manager, monkeypatch):
        """A presented key whose prefix matches no row triggers ZERO verify calls."""
        from giljo_mcp import api_key_utils

        # Seed a real key so the table is non-empty, then present a DIFFERENT key
        # whose 12-char prefix cannot collide with it.
        await _seed_api_key(db_manager)

        calls = {"n": 0}
        real_verify = api_key_utils.verify_api_key

        def _counting_verify(api_key: str, key_hash: str) -> bool:
            calls["n"] += 1
            return real_verify(api_key, key_hash)

        monkeypatch.setattr(api_key_utils, "verify_api_key", _counting_verify)

        no_match = f"gk_{uuid4().hex}{uuid4().hex}"  # unique prefix -> no candidate row
        result = await _authenticate(db_manager, no_match)
        assert result is None, "a key with no prefix match must not authenticate"
        assert calls["n"] == 0, (
            f"verify ran {calls['n']} time(s) without a key_prefix hit — the SQL prefix "
            "filter must gate ALL verification (bcrypt/sha256 CPU-DoS guard)"
        )


# ---------------------------------------------------------------------------
# 5) Failed-auth rate limit per IP engages; the happy path is never penalized.
# ---------------------------------------------------------------------------


def _unique_public_ip() -> str:
    """An RFC 3849 (2001:db8::/32) documentation IPv6 — non-loopback, unique per
    call so the per-IP limiter buckets never collide across xdist workers/tests."""
    return f"2001:db8::{uuid4().hex[:4]}:{uuid4().hex[:4]}"


def _freeze_rate_limit_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the limiter's fixed-window clock to the START of the current 60s bucket.

    BE-6087. The pre-auth IP limiter buckets on ``int(time.time()) // window``
    (window=60s). A test that drives ``limit`` increments and then asserts the
    decisive ``(limit+1)``th raises 429 is only deterministic if all of those
    calls land in ONE window. Under pytest-xdist ``-n6`` the worker is CPU- and
    DB-contended, so a multi-round-trip limiter test can take long enough to
    straddle a wall-clock minute boundary mid-loop: the bucket id rolls, the
    counter resets, and the decisive request is admitted (401/200) instead of
    throttled (429) — passing solo, flaking under ``-n6``. Freezing the clock to
    a constant inside the test removes the boundary entirely; the limiter sees a
    single, stable window. This is the SAME fixed-window determinism fix BE-1000a
    applied to the SaaS per-tenant rate-limit tests, and it is test-only — the
    documented production fixed-window burst behaviour (auth_rate_limiter
    module docstring) is unchanged. ``monkeypatch`` auto-reverts at teardown, so
    no module-level mutable state leaks to a sibling test.
    """
    from api.middleware import auth_rate_limiter as _arl

    frozen = float((int(_arl.time.time()) // 60) * 60)
    monkeypatch.setattr(_arl.time, "time", lambda: frozen)


def _request_with_ip(ip: str):
    """A Starlette Request whose client IP is ``ip`` and whose base_url is NOT
    ``http://test`` (so the limiter's test-bypass does not short-circuit it)."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [],
        "query_string": b"",
        "client": (ip, 12345),
        "server": ("app.giljo.ai", 443),
        "scheme": "https",
    }
    return Request(scope)


class TestFailedAuthRateLimit:
    @pytest.fixture(autouse=True)
    def _real_limiter(self, real_auth_rate_limiter):
        """SEC-9227 (H4): these tests assert the real failed-auth throttle fires,
        so keep the global test-bypass OFF for the whole class."""
        return

    @pytest.mark.asyncio
    async def test_failed_auth_429_engages_per_ip(self, monkeypatch):
        """N failures are allowed; the (N+1)th raises 429. A different IP is free."""
        from api.middleware.auth_rate_limiter import enforce_api_key_auth_failure
        from api.middleware.auth_rate_limits import limit_for

        # BE-6087: stable window so the limit-boundary assertion can't be
        # invalidated by a wall-clock minute roll mid-loop under -n6.
        _freeze_rate_limit_clock(monkeypatch)

        limit = limit_for("api_key_auth_failed")
        req = _request_with_ip(_unique_public_ip())

        for _ in range(limit):
            await enforce_api_key_auth_failure(req)  # under budget -> no raise

        with pytest.raises(HTTPException) as exc:
            await enforce_api_key_auth_failure(req)
        assert exc.value.status_code == 429, "over-budget failed auth must raise 429"
        assert "Retry-After" in (exc.value.headers or {}), "429 must carry Retry-After"

        # Per-IP isolation: a fresh IP is unaffected by the throttled one.
        await enforce_api_key_auth_failure(_request_with_ip(_unique_public_ip()))

    @pytest.mark.asyncio
    async def test_mcp_transport_throttles_spray_but_not_valid_key(self, db_manager, monkeypatch):
        """End-to-end: bad keys from one IP get 401s then a 429; a VALID key from
        the SAME (now-throttled) IP still authenticates — failures throttle, the
        happy path never does."""
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from api.middleware.auth_rate_limits import limit_for

        # BE-6087: freeze the limiter window. This case is the worst flake risk —
        # it does DB seeding + ~12 middleware round-trips, so under -n6 load it is
        # the most likely to straddle a minute boundary and lose its decisive 429.
        _freeze_rate_limit_clock(monkeypatch)

        ip = _unique_public_ip()
        valid_key, _tk, key_id = await _seed_api_key(db_manager)
        from giljo_mcp.api_key_utils import bust_api_key_cache

        bust_api_key_cache(key_id)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            limit = limit_for("api_key_auth_failed")

            # `limit` bad keys -> 401 each (recorded as failures).
            for _ in range(limit):
                status, _h, _b = await _drive_mcp(MCPAuthMiddleware, ip=ip, api_key=f"gk_{uuid4().hex}{uuid4().hex}")
                assert status == 401, f"a bad key must 401, got {status}"

            # One more bad key from the same IP -> 429 (throttled).
            status, headers, _b = await _drive_mcp(MCPAuthMiddleware, ip=ip, api_key=f"gk_{uuid4().hex}{uuid4().hex}")
            assert status == 429, f"over-budget IP must be throttled with 429, got {status}"
            assert "retry-after" in headers, "429 must carry retry-after"

            # The VALID key from the SAME throttled IP still authenticates: only
            # failures are counted, never the happy path.
            status, _h, _b = await _drive_mcp(MCPAuthMiddleware, ip=ip, api_key=valid_key)
            assert status == 200, (
                f"a valid key from a throttled IP must still authenticate (failures throttle, not success), got {status}"
            )
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_window_boundary_resets_counter_is_why_clock_is_frozen(self, monkeypatch):
        """BE-6087 regression — pins the flake MECHANISM the frozen clock defeats.

        The pre-auth limiter is a fixed-window counter keyed on
        ``int(time.time()) // 60``. Driving the SAME IP across two adjacent frozen
        windows proves: (1) inside one window the ``(limit+1)``th call raises 429;
        (2) the FIRST call of the next 60s window is admitted again because the
        bucket rolled and the counter reset. That reset is exactly what a
        wall-clock minute boundary does to a real enforcement loop mid-run —
        deterministic here only because the clock is controlled. It documents that
        the boundary behaviour is real (so the enforcement tests MUST freeze the
        clock) while confirming it is the *documented* fixed-window burst, not a
        production regression. If a future change made the limiter stop honouring
        its window, the window-2 admission below would start raising and flag it.
        """
        from api.middleware import auth_rate_limiter as _arl
        from api.middleware.auth_rate_limiter import enforce_api_key_auth_failure
        from api.middleware.auth_rate_limits import limit_for

        limit = limit_for("api_key_auth_failed")
        req = _request_with_ip(_unique_public_ip())

        # Window 1: pin to a bucket start; `limit` allowed, the next one throttled.
        w1 = float((int(_arl.time.time()) // 60) * 60)
        monkeypatch.setattr(_arl.time, "time", lambda: w1)
        for _ in range(limit):
            await enforce_api_key_auth_failure(req)
        with pytest.raises(HTTPException) as exc:
            await enforce_api_key_auth_failure(req)
        assert exc.value.status_code == 429, "in-window over-budget must raise 429"

        # Window 2 (next 60s bucket): the SAME IP is admitted again — the counter
        # reset at the boundary. A real -n6 enforcement loop straddling this point
        # would silently lose its decisive 429; freezing the clock prevents that.
        w2 = w1 + 60.0
        monkeypatch.setattr(_arl.time, "time", lambda: w2)
        await enforce_api_key_auth_failure(req)  # MUST NOT raise — fresh window


class _InnerOk:
    """Minimal inner ASGI app: 200 + a JSON-RPC-ish body."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})


async def _drive_mcp(middleware_cls, *, ip: str, api_key: str) -> tuple[int, dict[str, str], bytes]:
    """Drive one POST /mcp initialize through the middleware from client ``ip``.

    Server host is ``app.giljo.ai`` (NOT ``test``) so the rate limiter is active.
    """
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
        "server": ("app.giljo.ai", 443),
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
