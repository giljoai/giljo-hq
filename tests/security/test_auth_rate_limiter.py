# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.middleware import auth_rate_limiter as arl
from giljo_mcp.services.cache_backends import (
    AUTH_RATE_LIMIT_BACKEND_NAME,
    register_cache_backend,
    reset_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, real_auth_rate_limiter):
    monkeypatch.delenv(arl._TRUSTED_PROXIES_ENV, raising=False)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()
    yield
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()


def _make_request(
    *,
    client_host: str | None = "192.0.2.9",
    forwarded_for: str | None = None,
    cf_connecting_ip: str | None = None,
    path: str = "/api/auth/login",
    base_url: str = "http://app.example.local/",
) -> SimpleNamespace:
    headers: dict[str, str] = {}
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    if cf_connecting_ip is not None:
        headers["CF-Connecting-IP"] = cf_connecting_ip
    return SimpleNamespace(
        client=SimpleNamespace(host=client_host) if client_host is not None else None,
        headers=SimpleNamespace(get=headers.get),
        url=SimpleNamespace(path=path),
        base_url=base_url,
    )




class TestClientIpProxyAware:
    def test_xff_ignored_when_no_trusted_proxy_configured(self):
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7")
        assert limiter._get_client_ip(req) == "192.0.2.9"

    def test_xff_honored_when_peer_is_trusted_proxy(self, monkeypatch):
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7, 198.51.100.1")
        assert limiter._get_client_ip(req) == "203.0.113.7"

    def test_spoofed_xff_ignored_when_peer_untrusted(self, monkeypatch):
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "198.51.100.200")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7")
        assert limiter._get_client_ip(req) == "192.0.2.9"

    def test_exact_ip_allowlist_entry_matches(self, monkeypatch):
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.9")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7")
        assert limiter._get_client_ip(req) == "203.0.113.7"

    def test_trusted_peer_without_xff_falls_back_to_peer(self, monkeypatch):
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for=None)
        assert limiter._get_client_ip(req) == "192.0.2.9"

    def test_no_client_returns_unknown(self):
        limiter = arl.RateLimiter()
        req = _make_request(client_host=None, forwarded_for="203.0.113.7")
        assert limiter._get_client_ip(req) == "unknown"

    def test_malformed_allowlist_entry_is_skipped(self, monkeypatch):
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "not-an-ip, 192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7")
        assert limiter._get_client_ip(req) == "203.0.113.7"


    def test_cf_connecting_ip_preferred_when_peer_is_trusted_proxy(self, monkeypatch):
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", cf_connecting_ip="203.0.113.38")
        assert limiter._get_client_ip(req) == "203.0.113.38"

    def test_cf_connecting_ip_wins_over_xff_first_hop(self, monkeypatch):
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(
            client_host="192.0.2.9",
            cf_connecting_ip="203.0.113.38",
            forwarded_for="172.68.54.64, 198.51.100.1",
        )
        assert limiter._get_client_ip(req) == "203.0.113.38"

    def test_xff_used_when_no_cf_header(self, monkeypatch):
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7")
        assert limiter._get_client_ip(req) == "203.0.113.7"

    def test_spoofed_cf_connecting_ip_ignored_when_peer_untrusted(self, monkeypatch):
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "198.51.100.200")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", cf_connecting_ip="203.0.113.7")
        assert limiter._get_client_ip(req) == "192.0.2.9"




class TestSpoofedXffCannotEvadeLimit:
    @pytest.mark.asyncio
    async def test_rotating_spoofed_xff_does_not_reset_bucket(self):
        limiter = arl.RateLimiter()
        for i in range(2):
            req = _make_request(client_host="192.0.2.9", forwarded_for=f"203.0.113.{i}")
            assert await limiter.check_rate_limit(req, limit=2, window=60) is True

        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.250")
        assert await limiter.check_rate_limit(req, limit=2, window=60) is False




class TestAlwaysTrustProxyHeaderRewriteBypass:

    _TRUSTED_CF_RANGE = "192.0.2.0/24"
    _REAL_CLIENT = "203.0.113.7"

    def _always_trust_limiter(self, monkeypatch):
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, self._TRUSTED_CF_RANGE)
        arl._RateLimiterHolder.reset_for_tests()
        return arl.RateLimiter()

    def _rewritten_request(self, spoof_leftmost: str, *, with_cf_header: bool, extra_hop: str = ""):
        raw_xff = f"{spoof_leftmost}, {self._REAL_CLIENT}"
        if extra_hop:
            raw_xff = f"{raw_xff}, {extra_hop}"
        return _make_request(
            client_host=spoof_leftmost,
            forwarded_for=raw_xff,
            cf_connecting_ip=self._REAL_CLIENT if with_cf_header else None,
        )

    def test_resolver_returns_true_client_not_spoofed_leftmost(self, monkeypatch):
        limiter = self._always_trust_limiter(monkeypatch)
        req = self._rewritten_request("198.51.100.99", with_cf_header=True)
        assert limiter._get_client_ip(req) == self._REAL_CLIENT

    def test_resolver_walks_to_nearest_untrusted_when_no_cf_header(self, monkeypatch):
        limiter = self._always_trust_limiter(monkeypatch)
        req = self._rewritten_request("198.51.100.99", with_cf_header=False)
        assert limiter._get_client_ip(req) == self._REAL_CLIENT

    def test_walk_skips_trusted_egress_hop_when_intermediate_appends_it(self, monkeypatch):
        limiter = self._always_trust_limiter(monkeypatch)
        req = self._rewritten_request("198.51.100.99", with_cf_header=False, extra_hop="192.0.2.50")
        assert limiter._get_client_ip(req) == self._REAL_CLIENT

    @pytest.mark.asyncio
    async def test_rotating_spoofed_leftmost_cannot_mint_fresh_buckets(self, monkeypatch):
        limiter = self._always_trust_limiter(monkeypatch)
        for i in range(2):
            req = self._rewritten_request(f"198.51.100.{i}", with_cf_header=True)
            assert await limiter.check_rate_limit(req, limit=2, window=60) is True

        req = self._rewritten_request("198.51.100.250", with_cf_header=True)
        assert await limiter.check_rate_limit(req, limit=2, window=60) is False

    @pytest.mark.asyncio
    async def test_bypass_also_closed_without_cf_header(self, monkeypatch):
        limiter = self._always_trust_limiter(monkeypatch)
        for i in range(2):
            req = self._rewritten_request(f"198.51.100.{i}", with_cf_header=False)
            assert await limiter.check_rate_limit(req, limit=2, window=60) is True
        req = self._rewritten_request("198.51.100.250", with_cf_header=False)
        assert await limiter.check_rate_limit(req, limit=2, window=60) is False




class TestSharedLimiterStore:
    @pytest.mark.asyncio
    async def test_two_instances_share_one_combined_limit(self):
        worker_a = arl.RateLimiter()
        worker_b = arl.RateLimiter()
        assert worker_a._backend is worker_b._backend

        req = _make_request(client_host="198.51.100.5")

        assert await worker_a.check_rate_limit(req, limit=3, window=60) is True
        assert await worker_b.check_rate_limit(req, limit=3, window=60) is True
        assert await worker_a.check_rate_limit(req, limit=3, window=60) is True
        assert await worker_b.check_rate_limit(req, limit=3, window=60) is False
        assert await worker_a.check_rate_limit(req, limit=3, window=60) is False

    @pytest.mark.asyncio
    async def test_distinct_ips_have_independent_buckets(self):
        limiter = arl.RateLimiter()
        req_a = _make_request(client_host="198.51.100.1")
        req_b = _make_request(client_host="198.51.100.2")

        assert await limiter.check_rate_limit(req_a, limit=1, window=60) is True
        assert await limiter.check_rate_limit(req_a, limit=1, window=60) is False
        assert await limiter.check_rate_limit(req_b, limit=1, window=60) is True

    @pytest.mark.asyncio
    async def test_raise_on_limit_emits_429_with_retry_after(self):
        limiter = arl.RateLimiter()
        req = _make_request(client_host="198.51.100.9")
        assert await limiter.check_rate_limit(req, limit=1, window=60, raise_on_limit=True) is True
        with pytest.raises(HTTPException) as exc:
            await limiter.check_rate_limit(req, limit=1, window=60, raise_on_limit=True)
        assert exc.value.status_code == 429
        headers = exc.value.headers or {}
        assert int(headers["Retry-After"]) >= 1
        assert headers["X-RateLimit-Remaining"] == "0"

    @pytest.mark.asyncio
    async def test_explicit_flag_bypasses_but_host_header_never_does(self, monkeypatch):
        import api.middleware.auth_rate_limits as arlimits

        limiter = arl.RateLimiter()

        assert arlimits.is_test_bypass_enabled() is False, "flag must default OFF"
        req = _make_request(client_host="198.51.100.9", base_url="http://testanything.example/")
        assert await limiter.check_rate_limit(req, limit=1, window=60) is True
        assert await limiter.check_rate_limit(req, limit=1, window=60) is False

        arlimits.set_test_bypass(True)
        try:
            req2 = _make_request(client_host="198.51.100.10", base_url="http://app.example.local/")
            for _ in range(50):
                assert await limiter.check_rate_limit(req2, limit=1, window=60, raise_on_limit=True) is True
        finally:
            arlimits.set_test_bypass(False)


class _YieldingAtomicBackend:

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def _k(self, tenant_key: str, key: str) -> str:
        return f"{tenant_key}:{key}"

    async def get(self, tenant_key: str, key: str) -> str | None:
        await asyncio.sleep(0)
        return self._d.get(self._k(tenant_key, key))

    async def set(self, tenant_key: str, key: str, value: str, *, ttl_seconds: int) -> None:
        await asyncio.sleep(0)
        self._d[self._k(tenant_key, key)] = value

    async def setnx(self, tenant_key: str, key: str, value: str, *, ttl_seconds: int) -> bool:
        await asyncio.sleep(0)
        storage = self._k(tenant_key, key)
        if storage in self._d:
            return False
        self._d[storage] = value
        return True

    async def delete(self, tenant_key: str, key: str) -> None:
        self._d.pop(self._k(tenant_key, key), None)

    async def incr(self, tenant_key: str, key: str, *, ttl_seconds: int) -> int:
        storage = self._k(tenant_key, key)
        value = int(self._d.get(storage, 0)) + 1
        self._d[storage] = str(value)
        return value


class TestConcurrentAdmissionIsRaceFree:

    @pytest.mark.asyncio
    async def test_concurrent_admission_holds_exact_limit(self):
        register_cache_backend(AUTH_RATE_LIMIT_BACKEND_NAME, _YieldingAtomicBackend())
        limiter = arl.RateLimiter()
        req = _make_request(client_host="198.51.100.77")

        limit = 5
        results = await asyncio.gather(*(limiter.check_rate_limit(req, limit=limit, window=60) for _ in range(40)))

        assert sum(1 for allowed in results if allowed) == limit, results
        assert sum(1 for allowed in results if not allowed) == 40 - limit, results
