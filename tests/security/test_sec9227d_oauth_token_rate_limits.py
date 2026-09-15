# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

_WAY_OVER = 500


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, real_auth_rate_limiter):
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
    app = FastAPI()
    app.include_router(oauth_module.router, prefix="/api/oauth")
    app.include_router(revoke_module.router, prefix="/api/oauth")

    def _fake_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_db_session] = _fake_db
    return app


async def _prefilled_limiter(count: int) -> arl.RateLimiter:
    rl = arl.RateLimiter()
    bucket = rl._bucket_key("127.0.0.1", 60)
    for _ in range(count):
        await rl._backend.incr(arl._RATE_LIMIT_TENANT_SENTINEL, bucket, ttl_seconds=60)
    return rl


def _patched(rl: arl.RateLimiter):
    return (
        patch.object(oauth_module, "get_rate_limiter", return_value=rl),
        patch.object(revoke_module, "get_rate_limiter", return_value=rl),
    )


async def _post_malformed_json(app: FastAPI, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://example.local") as client:
        return await client.post(path, content=b"{not json", headers={"content-type": "application/json"})


_ENDPOINTS = [
    ("/api/oauth/token", "oauth_token"),
    ("/api/oauth/refresh", "oauth_refresh"),
    ("/api/oauth/revoke", "oauth_revoke"),
]




class TestDefaults:
    def test_oauth_token_family_limits_exist_with_documented_values(self):
        assert arlimits.limit_for("oauth_token") == 30
        assert arlimits.limit_for("oauth_refresh") == 30
        assert arlimits.limit_for("oauth_revoke") == 10

    def test_env_override_applies_per_endpoint(self, monkeypatch):
        monkeypatch.setenv("GILJO_RL_OAUTH_TOKEN", "99")
        assert arlimits.limit_for("oauth_token") == 99
        assert arlimits.limit_for("oauth_refresh") == 30
        assert arlimits.limit_for("oauth_revoke") == 10




class TestOverLimit429:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,name", _ENDPOINTS)
    async def test_over_limit_returns_429_not_oauth_envelope(self, path, name):
        rl = await _prefilled_limiter(_WAY_OVER)
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            r = await _post_malformed_json(app, path)

        assert r.status_code == 429, f"{name}: expected 429, got {r.status_code}: {r.text}"
        assert "Retry-After" in r.headers
        body = r.json()
        assert "error" not in body, f"{name}: 429 was rewritten into an OAuth envelope: {body}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,name", _ENDPOINTS)
    async def test_exactly_at_limit_blocks_the_next_request(self, path, name):
        rl = await _prefilled_limiter(arlimits.limit_for(name))
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            r = await _post_malformed_json(app, path)
        assert r.status_code == 429, f"{name}: expected 429, got {r.status_code}: {r.text}"




class TestUnderLimitFlowsThrough:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,name", _ENDPOINTS)
    async def test_under_limit_reaches_normal_validation(self, path, name):
        rl = await _prefilled_limiter(0)
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            r = await _post_malformed_json(app, path)

        assert r.status_code == 400, f"{name}: expected 400, got {r.status_code}: {r.text}"
        assert r.json()["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_under_limit_missing_fields_still_envelope_on_token(self):
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




class TestCeLoopbackExemption:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,name", _ENDPOINTS)
    async def test_ce_loopback_is_unthrottled(self, monkeypatch, path, name):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        rl = await _prefilled_limiter(_WAY_OVER)
        app = _build_app()
        p1, p2 = _patched(rl)
        with p1, p2:
            r = await _post_malformed_json(app, path)
        assert r.status_code == 400, f"{name}: expected 400 (exempt), got {r.status_code}: {r.text}"
        assert r.json()["error"] == "invalid_request"




_VALID_TOKEN_BODY = {
    "grant_type": "authorization_code",
    "code": "authcode",
    "client_id": "some-client",
    "redirect_uri": "http://127.0.0.1:1234/cb",
    "code_verifier": "v" * 43,
}


class TestInvalidClientPathUnthrottled:

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




class TestWindowReset:
    @pytest.mark.asyncio
    async def test_next_window_slot_admits_again(self, monkeypatch):
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
