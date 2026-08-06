# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6063f — pre-auth IP rate-limit hardening coverage.

Covers the three gaps closed in BE-6063f at the layer the behavior lives
(``api/middleware/auth_rate_limiter.RateLimiter`` + the ``auth_rate_limits``
policy module):

* Configurable per-path limits (``limit_for`` + ``GILJO_RL_<NAME>`` override).
* CE-only loopback exemption (``is_exempt_ip``) — exempt in CE, NEVER in SaaS.
* The limiter short-circuits to allow for an exempt IP.

Clock discipline (BE-1000a): the sliding-window limiter keys off wall-clock
``time.time()``. A test that crosses a real minute boundary can see the window
reset mid-test and flap 429->200. We FREEZE ``arl.time.time`` to a fixed value
so the window never advances within a test.

Test style: direct-call against ``RateLimiter`` with duck-typed request stubs
(mirrors ``tests/security/test_auth_rate_limiter.py``). Parallel-safe: every
test resets the cache-backend registry and the limiter singleton in an autouse
fixture; no module-level mutable state; GILJO_MODE and GILJO_RL_* env are
monkeypatched per test.
"""

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
    """Clean registry + fresh singleton + no trusted proxies + frozen clock.

    ``real_auth_rate_limiter`` (SEC-9227 H4) keeps the global test-bypass OFF —
    this suite's whole purpose is to prove the real limiter fires.

    Freezing ``arl.time.time`` to a constant pins the fixed-window bucket
    inside a single test, eliminating the BE-1000a minute-boundary flake.
    Default mode is CE with the loopback exemption ON (the env keys are
    deleted so the production defaults apply unless a test overrides them).
    """
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


# ---------------------------------------------------------------------------
# limit_for — configurable per-path limits
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# is_exempt_ip — CE loopback exemption, NEVER in SaaS
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Limiter behavior — limit enforcement, independence, exemption short-circuit
# ---------------------------------------------------------------------------


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
        # IP B is unaffected by IP A's exhaustion.
        assert await limiter.check_rate_limit(req_b, limit=1, window=60) is True

    @pytest.mark.asyncio
    async def test_env_override_raises_the_effective_limit(self, monkeypatch):
        """An operator override flows end-to-end: the limiter honors the bumped
        number, so what was rejected at the default is now allowed."""
        monkeypatch.setenv("GILJO_RL_LOGIN", "3")
        limiter = arl.RateLimiter()
        req = _make_request(client_host="198.51.100.40")
        bumped = arlimits.limit_for("login")
        assert bumped == 3
        for _ in range(bumped):
            assert await limiter.check_rate_limit(req, limit=bumped, window=60) is True
        # The (bumped+1)-th is blocked.
        assert await limiter.check_rate_limit(req, limit=bumped, window=60) is False


class TestLocalhostExemptionInLimiter:
    @pytest.mark.asyncio
    async def test_ce_localhost_exempt_allows_far_past_the_limit(self, monkeypatch):
        """CE + loopback peer: 50 calls at limit=1 are ALL allowed (exempt)."""
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        limiter = arl.RateLimiter()
        req = _make_request(client_host="127.0.0.1")
        for _ in range(50):
            assert await limiter.check_rate_limit(req, limit=1, window=60, raise_on_limit=True) is True

    @pytest.mark.asyncio
    async def test_saas_localhost_not_exempt_blocks_at_limit(self, monkeypatch):
        """SaaS + loopback peer: the exemption is OFF, so limit=1 blocks the 2nd call."""
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


# ---------------------------------------------------------------------------
# GAP 2 — create-first-admin 429 boundary, exercised through the ASGI app
# ---------------------------------------------------------------------------


class TestCreateFirstAdmin429Boundary:
    """The unauthenticated create-first-admin POST now has a per-IP limiter.

    Mirrors ``tests/saas/test_saas_rate_limits_429.py``: a real (un-mocked)
    RateLimiter, pre-filled to the limit with the SAME frozen clock value, behind
    a non-``http://test`` base_url so the test-bypass does not short-circuit.

    create-first-admin is CE-only (it 403s in SaaS). The ASGI transport resolves
    ``request.client.host`` as ``127.0.0.1``, which CE exempts by default — so we
    turn the localhost exemption OFF for this boundary test, otherwise no 429
    could ever fire from a loopback client.
    """

    @pytest.mark.asyncio
    async def test_create_first_admin_returns_429_after_limit(self, monkeypatch):
        monkeypatch.setattr("api.app_state.GILJO_MODE", "ce")
        monkeypatch.setenv("GILJO_RL_EXEMPT_LOCALHOST", "false")

        from api.endpoints.auth import registration
        from api.endpoints.dependencies import get_auth_service

        limit = arlimits.limit_for("create_first_admin")
        rl = arl.RateLimiter()
        # Pre-fill the limiter's window for the ASGI peer IP at the frozen clock
        # value so the very next request is the (limit+1)-th and trips 429.
        # BE-6006: seed via the same atomic incr the limiter uses, against this
        # IP's frozen-clock window bucket.
        bucket = rl._bucket_key("127.0.0.1", 60)
        for _ in range(limit):
            await rl._backend.incr(arl._RATE_LIMIT_TENANT_SENTINEL, bucket, ttl_seconds=60)

        app = FastAPI()
        app.include_router(registration.router, prefix="/api/auth")
        # The 429 raises before the auth service is touched; a sentinel override
        # is enough to satisfy the dependency wiring (object() is a valid factory).
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
