# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from api.middleware import auth_rate_limiter as arl
from api.middleware import auth_rate_limits as arlimits
from giljo_mcp.services.cache_backends import reset_registry_for_tests


pytestmark = pytest.mark.security


_FROZEN_NOW = 1_000_000.0


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, real_auth_rate_limiter):
    monkeypatch.delenv(arl._TRUSTED_PROXIES_ENV, raising=False)
    monkeypatch.delenv("GILJO_RL_EXEMPT_LOCALHOST", raising=False)
    for name in arlimits.DEFAULTS:
        monkeypatch.delenv(f"GILJO_RL_{name.upper()}", raising=False)
    monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
    monkeypatch.setattr(arl.time, "time", lambda: _FROZEN_NOW)
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()
    yield
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()


def _make_request(
    *,
    client_host: str | None = "192.0.2.9",
    forwarded_for: str | None = None,
    path: str = "/api/auth/login",
    base_url: str = "http://app.example.local/",
) -> SimpleNamespace:
    headers: dict[str, str] = {}
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    return SimpleNamespace(
        client=SimpleNamespace(host=client_host) if client_host is not None else None,
        headers=SimpleNamespace(get=headers.get),
        url=SimpleNamespace(path=path),
        base_url=base_url,
    )




class TestLimitFor:
    def test_defaults_match_documented_values(self):
        assert arlimits.limit_for("login") == 5
        assert arlimits.limit_for("register") == 3
        assert arlimits.limit_for("create_first_admin") == 3
        assert arlimits.limit_for("password_reset_confirm") == 10

    def test_env_override_raises_the_limit(self, monkeypatch):
        monkeypatch.setenv("GILJO_RL_LOGIN", "20")
        assert arlimits.limit_for("login") == 20

    def test_blank_override_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("GILJO_RL_LOGIN", "   ")
        assert arlimits.limit_for("login") == 5

    def test_non_integer_override_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("GILJO_RL_LOGIN", "lots")
        assert arlimits.limit_for("login") == 5

    def test_non_positive_override_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("GILJO_RL_LOGIN", "0")
        assert arlimits.limit_for("login") == 5
        monkeypatch.setenv("GILJO_RL_LOGIN", "-7")
        assert arlimits.limit_for("login") == 5

    def test_unknown_name_is_a_programming_error(self):
        with pytest.raises(KeyError):
            arlimits.limit_for("not_a_real_path")




class TestIsExemptIp:
    def test_ce_loopback_ipv4_is_exempt(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        assert arlimits.is_exempt_ip("127.0.0.1") is True

    def test_ce_loopback_ipv6_is_exempt(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        assert arlimits.is_exempt_ip("::1") is True

    def test_ce_non_loopback_is_not_exempt(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        assert arlimits.is_exempt_ip("203.0.113.7") is False

    def test_saas_loopback_is_never_exempt(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "saas")
        assert arlimits.is_exempt_ip("127.0.0.1") is False
        assert arlimits.is_exempt_ip("::1") is False

    def test_ce_toggle_off_disables_exemption(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        monkeypatch.setenv("GILJO_RL_EXEMPT_LOCALHOST", "false")
        assert arlimits.is_exempt_ip("127.0.0.1") is False

    def test_unparseable_ip_is_never_exempt(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        assert arlimits.is_exempt_ip("unknown") is False




class TestLimiterEnforcement:
    @pytest.mark.asyncio
    async def test_exceeding_limit_returns_429(self):
        limiter = arl.RateLimiter()
        req = _make_request(client_host="198.51.100.9")
        assert await limiter.check_rate_limit(req, limit=1, window=60, raise_on_limit=True) is True
        with pytest.raises(HTTPException) as exc:
            await limiter.check_rate_limit(req, limit=1, window=60, raise_on_limit=True)
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_distinct_ips_have_independent_buckets(self):
        limiter = arl.RateLimiter()
        req_a = _make_request(client_host="198.51.100.1")
        req_b = _make_request(client_host="198.51.100.2")
        assert await limiter.check_rate_limit(req_a, limit=1, window=60) is True
        assert await limiter.check_rate_limit(req_a, limit=1, window=60) is False
        assert await limiter.check_rate_limit(req_b, limit=1, window=60) is True

    @pytest.mark.asyncio
    async def test_env_override_raises_the_effective_limit(self, monkeypatch):
        monkeypatch.setenv("GILJO_RL_LOGIN", "3")
        limiter = arl.RateLimiter()
        req = _make_request(client_host="198.51.100.40")
        bumped = arlimits.limit_for("login")
        assert bumped == 3
        for _ in range(bumped):
            assert await limiter.check_rate_limit(req, limit=bumped, window=60) is True
        assert await limiter.check_rate_limit(req, limit=bumped, window=60) is False


class TestLocalhostExemptionInLimiter:
    @pytest.mark.asyncio
    async def test_ce_localhost_exempt_allows_far_past_the_limit(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        limiter = arl.RateLimiter()
        req = _make_request(client_host="127.0.0.1")
        for _ in range(50):
            assert await limiter.check_rate_limit(req, limit=1, window=60, raise_on_limit=True) is True

    @pytest.mark.asyncio
    async def test_saas_localhost_not_exempt_blocks_at_limit(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "saas")
        limiter = arl.RateLimiter()
        req = _make_request(client_host="127.0.0.1")
        assert await limiter.check_rate_limit(req, limit=1, window=60) is True
        assert await limiter.check_rate_limit(req, limit=1, window=60) is False

    @pytest.mark.asyncio
    async def test_ce_toggle_off_makes_localhost_subject_to_limit(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        monkeypatch.setenv("GILJO_RL_EXEMPT_LOCALHOST", "0")
        limiter = arl.RateLimiter()
        req = _make_request(client_host="127.0.0.1")
        assert await limiter.check_rate_limit(req, limit=1, window=60) is True
        assert await limiter.check_rate_limit(req, limit=1, window=60) is False




class TestCreateFirstAdmin429Boundary:

    @pytest.mark.asyncio
    async def test_create_first_admin_returns_429_after_limit(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        monkeypatch.setenv("GILJO_RL_EXEMPT_LOCALHOST", "false")

        from api.endpoints.auth import registration
        from api.endpoints.dependencies import get_auth_service

        limit = arlimits.limit_for("create_first_admin")
        rl = arl.RateLimiter()
        bucket = rl._bucket_key("127.0.0.1", 60)
        for _ in range(limit):
            await rl._backend.incr(arl._RATE_LIMIT_TENANT_SENTINEL, bucket, ttl_seconds=60)

        app = FastAPI()
        app.include_router(registration.router, prefix="/api/auth")
        app.dependency_overrides[get_auth_service] = object

        with patch.object(registration, "get_rate_limiter", return_value=rl):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://example.local",
            ) as client:
                r = await client.post(
                    "/api/auth/create-first-admin",
                    json={"username": "admin", "password": "Sup3rStr0ng!pw"},
                )

        assert r.status_code == 429, f"Expected 429, got {r.status_code}: {r.text}"
        assert "Retry-After" in r.headers
