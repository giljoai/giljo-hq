# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9227d — per-IP rate limiting on the OAuth token-endpoint family (M3).

POST /token, /refresh (api/endpoints/oauth.py) and /revoke
(api/endpoints/oauth_revoke.py) are public/unauthenticated by spec; every bad
client_secret costs a server-side bcrypt verify, so without a limiter they are
a CPU-amplification + client-secret brute-force surface. This suite proves:

* Over the limit → HTTP 429 with ``Retry-After``, and the 429 is NOT rewritten
  into the RFC 6749 §5.2 OAuth error envelope (no top-level ``error`` member —
  429 is not an OAuth protocol error).
* The limiter is the FIRST thing the request hits: the over-limit probes send a
  deliberately malformed body, so a 429 (not the parser's 400) proves the
  limiter runs before any parsing/validation return path.
* Under the limit, requests flow through to normal processing (the 400
  ``invalid_request`` envelope for a bad body) on all three endpoints.
* The CE loopback exemption still applies (127.0.0.1 unthrottled in CE mode).
* A new fixed-window slot resets the counter (clock-frozen, BE-1000a pattern —
  the window is advanced by moving the frozen clock, never by sleeping).

Clock discipline: ``arl.time.time`` is frozen to a constant so the window
bucket cannot roll over mid-test (house pattern from
tests/security/test_preauth_rate_limit_coverage.py).

``real_auth_rate_limiter`` (SEC-9227 H4) opts this suite out of the global
test-bypass — the whole point is to prove the real limiter fires. Default mode
is SaaS because the ASGI transport resolves the peer as ``127.0.0.1``, which CE
exempts by default; the CE-exemption case has its own dedicated test.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints import oauth as oauth_module
from api.endpoints import oauth_revoke as revoke_module
from api.middleware import auth_rate_limiter as arl
from api.middleware import auth_rate_limits as arlimits
from giljo_mcp.auth.dependencies import get_db_session
from giljo_mcp.services.cache_backends import reset_registry_for_tests


pytestmark = pytest.mark.security


_FROZEN_NOW = 1_000_000.0

# Prefill far past any plausible configured limit so the over-limit probes do
# not depend on the DEFAULTS values (those have their own explicit test).
_WAY_OVER = 500


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, real_auth_rate_limiter):
    """Real limiter (bypass OFF), clean registry + singleton, frozen clock, SaaS.

    ``real_auth_rate_limiter`` keeps the suite-wide test bypass OFF. SaaS mode
    disables the CE loopback exemption so the ASGI peer (127.0.0.1) is subject
    to the limit; the CE case flips the mode back explicitly.
    """
    monkeypatch.delenv(arl._TRUSTED_PROXIES_ENV, raising=False)
    monkeypatch.delenv("GILJO_RL_EXEMPT_LOCALHOST", raising=False)
    for name in arlimits.DEFAULTS:
        monkeypatch.delenv(f"GILJO_RL_{name.upper()}", raising=False)
    monkeypatch.setattr("api.app_state.GILJO_MODE", "saas")
    monkeypatch.setattr(arl.time, "time", lambda: _FROZEN_NOW)
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()
    yield
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()


def _build_app() -> FastAPI:
    """Bare app with the two OAuth routers mounted at the production prefix.

    The DB session is a MagicMock — every test here resolves (429 or a
    validation 400) before the service layer would touch the session.
    """
    app = FastAPI()
    app.include_router(oauth_module.router, prefix="/api/oauth")
    app.include_router(revoke_module.router, prefix="/api/oauth")

    def _fake_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_db_session] = _fake_db
    return app


async def _prefilled_limiter(count: int) -> arl.RateLimiter:
    """Fresh limiter with the ASGI peer's (127.0.0.1) frozen-window bucket
    pre-filled ``count`` times via the same atomic incr the limiter uses
    (BE-6006 seeding pattern)."""
    rl = arl.RateLimiter()
    bucket = rl._bucket_key("127.0.0.1", 60)
    for _ in range(count):
        await rl._backend.incr(arl._RATE_LIMIT_TENANT_SENTINEL, bucket, ttl_seconds=60)
    return rl


def _patched(rl: arl.RateLimiter):
    """Patch both endpoint modules' ``get_rate_limiter`` to the given limiter."""
    return (
        patch.object(oauth_module, "get_rate_limiter", return_value=rl),
        patch.object(revoke_module, "get_rate_limiter", return_value=rl),
    )


async def _post_malformed_json(app: FastAPI, path: str):
    """POST a deliberately malformed JSON body.

    On code WITHOUT the limiter (or under the limit) this returns the parser's
    400 ``invalid_request`` envelope — so a 429 here proves the limiter ran
    BEFORE any parsing return path (reject cheap, parse later).
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://example.local") as client:
        return await client.post(path, content=b"{not json", headers={"content-type": "application/json"})


_ENDPOINTS = [
    ("/api/oauth/token", "oauth_token"),
    ("/api/oauth/refresh", "oauth_refresh"),
    ("/api/oauth/revoke", "oauth_revoke"),
]


# ---------------------------------------------------------------------------
# Policy defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_oauth_token_family_limits_exist_with_documented_values(self):
        assert arlimits.limit_for("oauth_token") == 30
        assert arlimits.limit_for("oauth_refresh") == 30
        assert arlimits.limit_for("oauth_revoke") == 10

    def test_env_override_applies_per_endpoint(self, monkeypatch):
        monkeypatch.setenv("GILJO_RL_OAUTH_TOKEN", "99")
        assert arlimits.limit_for("oauth_token") == 99
        # The others are untouched by a single override.
        assert arlimits.limit_for("oauth_refresh") == 30
        assert arlimits.limit_for("oauth_revoke") == 10


# ---------------------------------------------------------------------------
# Over the limit → 429, un-enveloped, before any parsing
# ---------------------------------------------------------------------------


class TestOverLimit429:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,name", _ENDPOINTS)
    async def test_over_limit_returns_429_not_oauth_envelope(self, path, name):
        """Past the limit the response is 429 + Retry-After, NOT the RFC 6749
        envelope — and because the body is malformed JSON, a 429 also proves
        the limiter fired before the body parser's own 400 return path."""
        rl = await _prefilled_limiter(_WAY_OVER)
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            r = await _post_malformed_json(app, path)

        assert r.status_code == 429, f"{name}: expected 429, got {r.status_code}: {r.text}"
        assert "Retry-After" in r.headers
        body = r.json()
        # 429 is not an OAuth protocol error: it must NOT carry the RFC 6749
        # §5.2 top-level ``error`` member (i.e. never rewritten to
        # invalid_request by the endpoint's envelope conversion).
        assert "error" not in body, f"{name}: 429 was rewritten into an OAuth envelope: {body}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,name", _ENDPOINTS)
    async def test_exactly_at_limit_blocks_the_next_request(self, path, name):
        """Boundary: prefilled to exactly the configured limit, the very next
        request is the (limit+1)-th and trips 429."""
        rl = await _prefilled_limiter(arlimits.limit_for(name))
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            r = await _post_malformed_json(app, path)
        assert r.status_code == 429, f"{name}: expected 429, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Under the limit → flows through to normal processing
# ---------------------------------------------------------------------------


class TestUnderLimitFlowsThrough:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,name", _ENDPOINTS)
    async def test_under_limit_reaches_normal_validation(self, path, name):
        """With a fresh (empty) window, the request passes the limiter and
        reaches normal processing — proven by the endpoint's own 400
        ``invalid_request`` OAuth envelope for the malformed body."""
        rl = await _prefilled_limiter(0)
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            r = await _post_malformed_json(app, path)

        assert r.status_code == 400, f"{name}: expected 400, got {r.status_code}: {r.text}"
        assert r.json()["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_under_limit_missing_fields_still_envelope_on_token(self):
        """A parseable-but-incomplete /token body still gets the normal OAuth
        envelope (limiter passes, missing-field validation answers)."""
        rl = await _prefilled_limiter(0)
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://example.local") as client:
                r = await client.post("/api/oauth/token", data={"grant_type": "authorization_code"})
        assert r.status_code == 400
        body = r.json()
        assert body["error"] == "invalid_request"
        assert "missing required field" in body.get("error_description", "")


# ---------------------------------------------------------------------------
# CE loopback exemption
# ---------------------------------------------------------------------------


class TestCeLoopbackExemption:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,name", _ENDPOINTS)
    async def test_ce_loopback_is_unthrottled(self, monkeypatch, path, name):
        """CE mode + loopback peer: even a way-over-limit window never 429s —
        the request flows through to normal validation."""
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        rl = await _prefilled_limiter(_WAY_OVER)
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            r = await _post_malformed_json(app, path)
        assert r.status_code == 400, f"{name}: expected 400 (exempt), got {r.status_code}: {r.text}"
        assert r.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# invalid_client failure path — envelope preserved, single limiter check
# ---------------------------------------------------------------------------


_VALID_TOKEN_BODY = {
    "grant_type": "authorization_code",
    "code": "authcode",
    "client_id": "some-client",
    "redirect_uri": "http://127.0.0.1:1234/cb",
    "code_verifier": "v" * 43,
}


class TestInvalidClientPathUnthrottled:
    """The invalid_client failure path keeps its RFC 6749 envelope: under the
    limit, a bad client_secret gets the normal 401 ``invalid_client``, never a
    limiter response. (SEC-9227d shipped WITHOUT a failure-only counter: the
    limiter bucket is keyed per-IP with no limit-name dimension, so a tighter
    failure budget would read the same counter successes increment and 429
    honest first failures. Deferred to a name-dimensioned key follow-up.)"""

    @pytest.mark.asyncio
    async def test_failed_client_auth_under_limit_keeps_invalid_client_envelope(self):
        rl = await _prefilled_limiter(0)
        app = _build_app()

        fake_service = MagicMock()
        fake_service.exchange_code_for_token = AsyncMock(side_effect=ValueError("invalid_client: bad secret"))

        p1, p2 = _patched(rl)
        with p1, p2, patch.object(oauth_module, "OAuthService", return_value=fake_service):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://example.local") as client:
                r = await client.post("/api/oauth/token", data=_VALID_TOKEN_BODY)

        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"
        assert r.json()["error"] == "invalid_client"

    @pytest.mark.asyncio
    async def test_successful_exchange_makes_exactly_one_limiter_check(self):
        """A successful exchange makes exactly ONE limiter check (the entry
        check) — no hidden second check anywhere in the handler."""
        rl = await _prefilled_limiter(0)
        app = _build_app()

        fake_service = MagicMock()
        fake_service.exchange_code_for_token = AsyncMock(
            return_value={"access_token": "at", "token_type": "bearer", "expires_in": 3600}
        )

        calls: list[int] = []
        original_check = rl.check_rate_limit

        async def counting_check(request, limit, window=60, raise_on_limit=False):
            calls.append(limit)
            return await original_check(request, limit, window=window, raise_on_limit=raise_on_limit)

        rl.check_rate_limit = counting_check

        p1, p2 = _patched(rl)
        with p1, p2, patch.object(oauth_module, "OAuthService", return_value=fake_service):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://example.local") as client:
                r = await client.post("/api/oauth/token", data=_VALID_TOKEN_BODY)

        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        assert calls == [arlimits.limit_for("oauth_token")]


# ---------------------------------------------------------------------------
# Fixed-window semantics under the frozen clock
# ---------------------------------------------------------------------------


class TestWindowReset:
    @pytest.mark.asyncio
    async def test_next_window_slot_admits_again(self, monkeypatch):
        """Advancing the frozen clock one full window opens a fresh bucket: the
        blocked IP is admitted again (and reaches normal validation)."""
        rl = await _prefilled_limiter(_WAY_OVER)
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            r_blocked = await _post_malformed_json(app, "/api/oauth/token")
        assert r_blocked.status_code == 429

        monkeypatch.setattr(arl.time, "time", lambda: _FROZEN_NOW + 60.0)
        p1, p2 = _patched(rl)
        with p1, p2:
            r_fresh = await _post_malformed_json(app, "/api/oauth/token")
        assert r_fresh.status_code == 400
        assert r_fresh.json()["error"] == "invalid_request"
