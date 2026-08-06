# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-6001 — proxy-aware client IP keying + shared limiter store.

Covers the two auth-rate-limiter hardening units at the layer the bug lives
(``api/middleware/auth_rate_limiter.RateLimiter``):

Unit 1 — proxy-aware IP. ``X-Forwarded-For`` is honored ONLY when the immediate
peer (``request.client.host``) is in the ``GILJO_TRUSTED_PROXIES`` allowlist.
When the peer is untrusted, XFF is a forgeable header and is ignored — the
limiter falls back to the direct peer IP. Default empty allowlist = no proxy
trusted (the pre-SEC-6001 behavior).

Unit 2 — shared store. The fixed-window counters live in the
``CacheBackend`` registry, so two ``RateLimiter`` instances that share one
backend enforce ONE combined limit (the multi-worker bug: per-process state
multiplies the limit by worker count). BE-6006 made the counter atomic
(backend ``incr``) so the limit also holds under concurrent admission.

Test style: direct-call against ``RateLimiter`` with duck-typed request stubs
(mirrors ``tests/security/test_rate_limit.py``). No DB, no app state — the
limiter is self-contained. Parallel-safe: every test resets the cache-backend
registry and the limiter singleton in fixtures; no module-level mutable state.
"""

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
    """Each test starts with a clean registry, fresh singleton, no trusted proxies.

    ``real_auth_rate_limiter`` (SEC-9227 H4) opts this whole suite out of the
    global test-bypass — it exercises the limiter itself, so the bypass stays OFF.
    """
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


# ---------------------------------------------------------------------------
# Unit 1 — proxy-aware IP resolution
# ---------------------------------------------------------------------------


class TestClientIpProxyAware:
    def test_xff_ignored_when_no_trusted_proxy_configured(self):
        """Default (empty allowlist): XFF is never trusted; key on peer IP."""
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7")
        assert limiter._get_client_ip(req) == "192.0.2.9"

    def test_xff_honored_when_peer_is_trusted_proxy(self, monkeypatch):
        """Peer in allowlist: the first XFF hop (original client) is used."""
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7, 198.51.100.1")
        assert limiter._get_client_ip(req) == "203.0.113.7"

    def test_spoofed_xff_ignored_when_peer_untrusted(self, monkeypatch):
        """Peer NOT in allowlist: XFF is a forgeable header — fall back to peer IP."""
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "198.51.100.200")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7")
        # 192.0.2.9 is not the trusted 198.51.100.200, so the spoofed XFF is dropped.
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
        """A typo in one entry must not crash or disable limiting; it is ignored."""
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "not-an-ip, 192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7")
        assert limiter._get_client_ip(req) == "203.0.113.7"

    # -- CF-Connecting-IP (perf-findings 2026-06-11): behind Cloudflare→Railway
    #    the XFF first hop is a Cloudflare edge IP, not the real client, so
    #    XFF-only keying collapsed all users into shared CF-IP buckets → 429
    #    storms. The resolver now prefers CF-Connecting-IP (the authoritative
    #    real client) when the peer is trusted, with XFF kept as the fallback.

    def test_cf_connecting_ip_preferred_when_peer_is_trusted_proxy(self, monkeypatch):
        """Trusted CF peer: the authoritative CF-Connecting-IP is the real client."""
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", cf_connecting_ip="71.241.214.38")
        assert limiter._get_client_ip(req) == "71.241.214.38"

    def test_cf_connecting_ip_wins_over_xff_first_hop(self, monkeypatch):
        """When both headers are present (prod shape: XFF first hop = a CF edge IP),
        CF-Connecting-IP — the true client — takes precedence over XFF."""
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(
            client_host="192.0.2.9",
            cf_connecting_ip="71.241.214.38",
            forwarded_for="172.68.54.64, 198.51.100.1",
        )
        assert limiter._get_client_ip(req) == "71.241.214.38"

    def test_xff_used_when_no_cf_header(self, monkeypatch):
        """Non-Cloudflare trusted proxy (no CF header): XFF first hop still works."""
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "192.0.2.0/24")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.7")
        assert limiter._get_client_ip(req) == "203.0.113.7"

    def test_spoofed_cf_connecting_ip_ignored_when_peer_untrusted(self, monkeypatch):
        """Untrusted peer: CF-Connecting-IP is a forgeable header — drop it and key
        on the peer IP. The trusted-proxy gate is the only spoofing protection."""
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, "198.51.100.200")
        arl._RateLimiterHolder.reset_for_tests()
        limiter = arl.RateLimiter()
        req = _make_request(client_host="192.0.2.9", cf_connecting_ip="203.0.113.7")
        assert limiter._get_client_ip(req) == "192.0.2.9"


# ---------------------------------------------------------------------------
# Unit 1 — spoofing cannot be used to evade the limit
# ---------------------------------------------------------------------------


class TestSpoofedXffCannotEvadeLimit:
    @pytest.mark.asyncio
    async def test_rotating_spoofed_xff_does_not_reset_bucket(self):
        """An attacker rotating XFF from an untrusted peer stays on ONE bucket.

        Without the trusted-proxy gate, each forged XFF would be a fresh key and
        the limit could be evaded indefinitely. With the gate, all requests key
        on the (single) untrusted peer IP and the limit holds.
        """
        limiter = arl.RateLimiter()
        for i in range(2):
            req = _make_request(client_host="192.0.2.9", forwarded_for=f"203.0.113.{i}")
            assert await limiter.check_rate_limit(req, limit=2, window=60) is True

        # Third request, again a fresh forged XFF — must still be blocked.
        req = _make_request(client_host="192.0.2.9", forwarded_for="203.0.113.250")
        assert await limiter.check_rate_limit(req, limit=2, window=60) is False


# ---------------------------------------------------------------------------
# SEC-9217d — composition bug: uvicorn FORWARDED_ALLOW_IPS=* leftmost-hop rewrite
# ---------------------------------------------------------------------------


class TestAlwaysTrustProxyHeaderRewriteBypass:
    """Prod runs uvicorn with ``FORWARDED_ALLOW_IPS=*`` (needed so uvicorn honors
    X-Forwarded-Proto for OAuth https detection). With ``always_trust``, uvicorn's
    ProxyHeadersMiddleware overwrites ``scope["client"]`` with
    ``x_forwarded_for_hosts[0]`` — the LEFTMOST hop, the original attacker-supplied
    X-Forwarded-For entry (uvicorn 0.49 ``_TrustedHosts.get_trusted_client_address``).
    ``request.client.host`` is then spoofable, so the resolver's
    ``peer_is_trusted_proxy(client.host)`` gate is defeated and it returns the
    attacker value verbatim → rotating XFF mints a fresh rate-limit bucket every
    request → the auth limiter is bypassed.

    These stubs reproduce the REAL Cloudflare→Railway shape, NOT a synthetic one:
    the client sends a spoofed ``X-Forwarded-For``, Cloudflare APPENDS the true
    client as the right-most XFF entry and sets ``CF-Connecting-IP`` to it, and
    Cloudflare's egress is the TCP peer (so it is NOT in XFF). uvicorn's
    always-trust rewrite then leaves ``client.host`` = the spoofed LEFTMOST hop.
    ``GILJO_TRUSTED_PROXIES`` stands in for the Cloudflare egress ranges, as prod.
    """

    _TRUSTED_CF_RANGE = "192.0.2.0/24"  # stands in for Cloudflare egress ranges
    _REAL_CLIENT = "203.0.113.7"  # constant true client (CF-appended, right-most)

    def _always_trust_limiter(self, monkeypatch):
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
        monkeypatch.setenv(arl._TRUSTED_PROXIES_ENV, self._TRUSTED_CF_RANGE)
        arl._RateLimiterHolder.reset_for_tests()
        return arl.RateLimiter()

    def _rewritten_request(self, spoof_leftmost: str, *, with_cf_header: bool, extra_hop: str = ""):
        # Real chain: client-supplied spoof (leftmost) then CF-appended true
        # client (right-most). uvicorn always_trust set client.host = leftmost.
        raw_xff = f"{spoof_leftmost}, {self._REAL_CLIENT}"
        if extra_hop:
            raw_xff = f"{raw_xff}, {extra_hop}"
        return _make_request(
            client_host=spoof_leftmost,
            forwarded_for=raw_xff,
            cf_connecting_ip=self._REAL_CLIENT if with_cf_header else None,
        )

    def test_resolver_returns_true_client_not_spoofed_leftmost(self, monkeypatch):
        """The resolver must key on the true client, not uvicorn's spoofable
        leftmost rewrite of client.host. CF-Connecting-IP is authoritative."""
        limiter = self._always_trust_limiter(monkeypatch)
        req = self._rewritten_request("198.51.100.99", with_cf_header=True)
        assert limiter._get_client_ip(req) == self._REAL_CLIENT

    def test_resolver_walks_to_nearest_untrusted_when_no_cf_header(self, monkeypatch):
        """No CF header: walk the raw XFF from the connection side (rightmost) to
        the nearest untrusted hop — the CF-appended real client — never the
        spoofable leftmost entry."""
        limiter = self._always_trust_limiter(monkeypatch)
        req = self._rewritten_request("198.51.100.99", with_cf_header=False)
        assert limiter._get_client_ip(req) == self._REAL_CLIENT

    def test_walk_skips_trusted_egress_hop_when_intermediate_appends_it(self, monkeypatch):
        """Robustness: if an intermediate DID append our own egress IP (a trusted
        proxy) to the right of the real client, the walk skips it and still lands
        on the real client, not the trusted infra IP."""
        limiter = self._always_trust_limiter(monkeypatch)
        # ...S(spoof), R(real client), 192.0.2.50(our trusted egress, right-most)
        req = self._rewritten_request("198.51.100.99", with_cf_header=False, extra_hop="192.0.2.50")
        assert limiter._get_client_ip(req) == self._REAL_CLIENT

    @pytest.mark.asyncio
    async def test_rotating_spoofed_leftmost_cannot_mint_fresh_buckets(self, monkeypatch):
        """The bypass, at the limiter layer: an attacker rotating the leftmost XFF
        hop (which uvicorn writes into client.host) must NOT get a fresh bucket per
        request — all requests key on the constant true client and the limit holds."""
        limiter = self._always_trust_limiter(monkeypatch)
        for i in range(2):
            req = self._rewritten_request(f"198.51.100.{i}", with_cf_header=True)
            assert await limiter.check_rate_limit(req, limit=2, window=60) is True

        # Third request, again rotating the spoofed leftmost hop — must be blocked
        # because it keys on the same true client as the first two.
        req = self._rewritten_request("198.51.100.250", with_cf_header=True)
        assert await limiter.check_rate_limit(req, limit=2, window=60) is False

    @pytest.mark.asyncio
    async def test_bypass_also_closed_without_cf_header(self, monkeypatch):
        """Same bypass, non-Cloudflare trusted proxy path (no CF header): rotating
        the spoofed leftmost hop still keys on the constant right-most real client."""
        limiter = self._always_trust_limiter(monkeypatch)
        for i in range(2):
            req = self._rewritten_request(f"198.51.100.{i}", with_cf_header=False)
            assert await limiter.check_rate_limit(req, limit=2, window=60) is True
        req = self._rewritten_request("198.51.100.250", with_cf_header=False)
        assert await limiter.check_rate_limit(req, limit=2, window=60) is False


# ---------------------------------------------------------------------------
# Unit 2 — shared store enforces one combined limit across instances
# ---------------------------------------------------------------------------


class TestSharedLimiterStore:
    @pytest.mark.asyncio
    async def test_two_instances_share_one_combined_limit(self):
        """Two RateLimiter instances (simulating two workers) sharing the registry
        backend enforce a SINGLE combined limit, not limit-per-instance.
        """
        worker_a = arl.RateLimiter()
        worker_b = arl.RateLimiter()
        # Same registry backend => same store.
        assert worker_a._backend is worker_b._backend

        req = _make_request(client_host="198.51.100.5")

        # limit=3 combined. A handles 2, B handles 1 → bucket full.
        assert await worker_a.check_rate_limit(req, limit=3, window=60) is True
        assert await worker_b.check_rate_limit(req, limit=3, window=60) is True
        assert await worker_a.check_rate_limit(req, limit=3, window=60) is True
        # 4th request on EITHER instance must be rejected — combined limit reached.
        assert await worker_b.check_rate_limit(req, limit=3, window=60) is False
        assert await worker_a.check_rate_limit(req, limit=3, window=60) is False

    @pytest.mark.asyncio
    async def test_distinct_ips_have_independent_buckets(self):
        limiter = arl.RateLimiter()
        req_a = _make_request(client_host="198.51.100.1")
        req_b = _make_request(client_host="198.51.100.2")

        assert await limiter.check_rate_limit(req_a, limit=1, window=60) is True
        assert await limiter.check_rate_limit(req_a, limit=1, window=60) is False
        # IP B unaffected by IP A exhaustion.
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
        """SEC-9227 (H4): the bypass is the explicit process flag, NOT the Host.

        Two-sided: (1) a request whose base_url/Host starts with ``http://test``
        — the old sentinel, still fully attacker-controllable — is now RATE
        LIMITED with the flag off; (2) flipping the explicit flag on bypasses.
        The exploit-shaped case is (1): a forged ``Host`` can no longer disable
        the limiter.
        """
        import api.middleware.auth_rate_limits as arlimits

        limiter = arl.RateLimiter()

        # (1) Exploit shape: forged Host ``http://testanything`` no longer bypasses.
        assert arlimits.is_test_bypass_enabled() is False, "flag must default OFF"
        req = _make_request(client_host="198.51.100.9", base_url="http://testanything.example/")
        assert await limiter.check_rate_limit(req, limit=1, window=60) is True
        # Second request over the limit: the forged Host does NOT save it.
        assert await limiter.check_rate_limit(req, limit=1, window=60) is False

        # (2) The explicit flag is the only bypass; with it on, nothing throttles.
        arlimits.set_test_bypass(True)
        try:
            req2 = _make_request(client_host="198.51.100.10", base_url="http://app.example.local/")
            for _ in range(50):
                assert await limiter.check_rate_limit(req2, limit=1, window=60, raise_on_limit=True) is True
        finally:
            arlimits.set_test_bypass(False)


class _YieldingAtomicBackend:
    """CacheBackend whose get/set YIELD to the event loop (like a real Redis
    round trip) but whose ``incr`` is atomic.

    This is the regression harness for BE-6006: with a backend that yields
    between operations, the old ``get()``-check-``set()`` read-modify-write would
    interleave under concurrency and admit MORE than ``limit`` requests. The
    new code uses the single atomic ``incr``, so the limit holds exactly. A
    revert to the racy path makes ``test_concurrent_admission_holds_exact_limit``
    over-admit and fail.
    """

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
        # Atomic: no await between the read and the write, so concurrent callers
        # never observe the same pre-increment value.
        storage = self._k(tenant_key, key)
        value = int(self._d.get(storage, 0)) + 1
        self._d[storage] = str(value)
        return value


class TestConcurrentAdmissionIsRaceFree:
    """BE-6006 — the atomic counter holds the limit under concurrent admission."""

    @pytest.mark.asyncio
    async def test_concurrent_admission_holds_exact_limit(self):
        """Fire many concurrent requests for one IP; EXACTLY `limit` are admitted.

        The backend yields in get/set to expose any read-modify-write window;
        because the limiter increments atomically, no more than `limit` of the
        concurrent callers see an allowed decision.
        """
        register_cache_backend(AUTH_RATE_LIMIT_BACKEND_NAME, _YieldingAtomicBackend())
        limiter = arl.RateLimiter()
        req = _make_request(client_host="198.51.100.77")

        limit = 5
        results = await asyncio.gather(*(limiter.check_rate_limit(req, limit=limit, window=60) for _ in range(40)))

        assert sum(1 for allowed in results if allowed) == limit, results
        assert sum(1 for allowed in results if not allowed) == 40 - limit, results
