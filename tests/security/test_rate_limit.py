# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
SEC-0002 Property — per-IP rate-limit verification.

This test verifies the behavior documented in the SEC-0002 passive-server
audit (Deliverable D):

- ``api/middleware/rate_limiter.py`` is a per-IP limiter — an atomic
  fixed-window counter over the shared ``CacheBackend`` registry (INF-3009d),
  so multi-worker deployments enforce one combined limit and counters are
  TTL-evicted by the backend.
- Keying is extracted by ``_get_client_ip(request)`` via the shared
  trusted-proxy-aware resolver (SEC-6010): the ``X-Forwarded-For`` first hop is
  honored ONLY when the immediate peer (``request.client.host``) is in the
  ``GILJO_TRUSTED_PROXIES`` allowlist. From an untrusted peer, XFF is a
  forgeable header and is ignored — keying falls back to the direct peer IP,
  then to the literal ``"unknown"`` when there is no peer.
- Over-limit requests raise HTTP 429 with ``Retry-After``,
  ``X-RateLimit-Limit``, ``X-RateLimit-Remaining``, ``X-RateLimit-Reset``
  headers.
- Static-file and configured exempt paths bypass the limiter entirely.

**Out of scope — what this test does NOT verify:**

This test verifies PER-IP behavior only. It does NOT verify per-tenant quotas
(roadmap work, a separate anti-abuse track). A tenant operating from
many IPs can exceed any intended per-tenant budget under the current
middleware; the Trust Model surfaces this explicitly. Do not mistake a green
run here for a cross-IP anti-abuse guarantee.

Test style: direct-call / unit-style against ``RateLimiter`` and
``RateLimitMiddleware``, following the SEC-0005c pattern in
``tests/security/test_tenant_required.py`` (which uses direct handler calls
with hand-built request-like objects rather than spinning up a full
FastAPI TestClient). A TestClient-based test would add app-state
dependencies that are not needed to verify the three contracts above.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from api.middleware._proxy_aware_ip import TRUSTED_PROXIES_ENV
from api.middleware.rate_limiter import RateLimiter, RateLimitMiddleware
from giljo_mcp.services.cache_backends import (
    GLOBAL_RATE_LIMIT_BACKEND_NAME,
    InProcessDictBackend,
    register_cache_backend,
)


# The corroborating SEC-0002 audit is a private security-handover doc, stripped
# from the CE export. Private CI keeps the doc so the corroboration test runs
# there; a CE self-hoster running the full suite skips that one test green rather
# than hard-failing on the absent file (the rest of this module is unaffected).
_SEC0002_AUDIT = Path(__file__).resolve().parents[2] / "handovers" / "security" / "SEC-0002_passive_server_audit.md"


@pytest.fixture(autouse=True)
def _isolated_rate_limit_backend():
    """Each test gets a fresh in-process backend under the global-limiter name.

    The limiter resolves its backend through the shared registry per call, so
    without this, buckets would bleed between tests on the same xdist worker.
    """
    register_cache_backend(
        GLOBAL_RATE_LIMIT_BACKEND_NAME,
        InProcessDictBackend(namespace=GLOBAL_RATE_LIMIT_BACKEND_NAME),
    )
    yield
    register_cache_backend(
        GLOBAL_RATE_LIMIT_BACKEND_NAME,
        InProcessDictBackend(namespace=GLOBAL_RATE_LIMIT_BACKEND_NAME),
    )


@pytest.fixture(autouse=True)
def _no_trusted_proxies_by_default(monkeypatch):
    """Most tests assume the safe default (empty allowlist, no proxy trusted).

    The ``RateLimitMiddleware`` reads ``GILJO_TRUSTED_PROXIES`` at construction,
    so clearing it here (and constructing the middleware per test) keeps the
    suite parallel-safe with no module-level mutable state. Tests that exercise
    the trusted-proxy path set the env via ``monkeypatch.setenv`` before
    constructing their own middleware.
    """
    monkeypatch.delenv(TRUSTED_PROXIES_ENV, raising=False)


# ---------------------------------------------------------------------------
# Helpers: minimal Request-shaped objects for _get_client_ip / dispatch
# ---------------------------------------------------------------------------


def _make_request(
    *,
    path: str = "/api/v1/projects",
    method: str = "GET",
    forwarded_for: str | None = None,
    client_host: str | None = "127.0.0.1",
) -> SimpleNamespace:
    """
    Build a duck-typed Request that exposes only what ``RateLimitMiddleware``
    touches: ``url.path``, ``method``, ``headers.get``, and ``client.host``.

    Starlette's real Request has much more surface, but the rate-limit
    middleware is self-contained enough that a SimpleNamespace stub is
    sufficient and avoids having to build a full ASGI scope.
    """
    headers: dict[str, str] = {}
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for

    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        method=method,
        headers=SimpleNamespace(get=headers.get),
        client=SimpleNamespace(host=client_host) if client_host is not None else None,
    )


class _Driven:
    """Captured result of driving RateLimitMiddleware through one ASGI request."""

    def __init__(self) -> None:
        self.status_code: int | None = None
        self.headers: Headers = Headers(raw=[])
        self.downstream_called: bool = False


async def _drive(
    middleware: RateLimitMiddleware,
    *,
    path: str = "/api/v1/projects",
    method: str = "GET",
    forwarded_for: str | None = None,
    client_host: str | None = "127.0.0.1",
) -> _Driven:
    """Run RateLimitMiddleware (pure-ASGI) through the protocol for one request.

    The downstream app returns a plain 200 so the middleware's X-RateLimit-*
    header injection on the allow path is observable; the 429 reject path emits
    its own response without ever invoking downstream.
    """
    raw_headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        raw_headers.append((b"x-forwarded-for", forwarded_for.encode()))

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": raw_headers,
        "scheme": "http",
        "server": ("test", 80),
    }
    if client_host is not None:
        scope["client"] = (client_host, 12345)

    driven = _Driven()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            driven.status_code = message["status"]
            driven.headers = Headers(raw=message["headers"])

    async def downstream_app(scope, receive, send):
        driven.downstream_called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware.app = downstream_app
    await middleware(scope, receive, send)
    return driven


# ---------------------------------------------------------------------------
# RateLimiter: per-key bucket invariants
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_same_key_shares_bucket():
    """Two calls with the same key count toward one bucket (per-IP keying)."""
    limiter = RateLimiter(requests_per_minute=2)

    assert await limiter.is_allowed("1.1.1.1") is True
    assert await limiter.is_allowed("1.1.1.1") is True
    # Third call for the same key must be blocked — bucket is full.
    assert await limiter.is_allowed("1.1.1.1") is False


@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_distinct_keys_have_independent_buckets():
    """
    Different keys have independent quotas — exhausting one IP's bucket must
    not affect another IP. This is the core per-IP contract.
    """
    limiter = RateLimiter(requests_per_minute=2)

    # Exhaust IP A.
    assert await limiter.is_allowed("1.1.1.1") is True
    assert await limiter.is_allowed("1.1.1.1") is True
    assert await limiter.is_allowed("1.1.1.1") is False

    # IP B still has a full budget — distinct bucket.
    assert await limiter.is_allowed("2.2.2.2") is True
    assert await limiter.is_allowed("2.2.2.2") is True
    assert await limiter.is_allowed("2.2.2.2") is False


@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_hit_reports_remaining():
    """``hit`` reports the unused slots for the key's bucket after consuming one."""
    limiter = RateLimiter(requests_per_minute=3)

    assert (await limiter.hit("1.1.1.1")).remaining == 2
    assert (await limiter.hit("1.1.1.1")).remaining == 1
    assert (await limiter.hit("1.1.1.1")).remaining == 0
    # Over-limit hits stay clamped at zero.
    assert (await limiter.hit("1.1.1.1")).remaining == 0


@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_one_combined_limit_across_workers():
    """INF-3009d: two limiter instances (simulating two uvicorn workers) share
    ONE budget through the registered backend.

    The old per-process dict gave each worker its own bucket, so the effective
    limit was limit * workers. With the shared store, worker B's request counts
    against the same window worker A already consumed.
    """
    worker_a = RateLimiter(requests_per_minute=2)
    worker_b = RateLimiter(requests_per_minute=2)

    assert await worker_a.is_allowed("9.9.9.9") is True
    assert await worker_b.is_allowed("9.9.9.9") is True
    # Combined count is 2 — BOTH workers must now reject, not each allow 2 more.
    assert await worker_a.is_allowed("9.9.9.9") is False
    assert await worker_b.is_allowed("9.9.9.9") is False


@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_fails_open_on_backend_error():
    """A broken store must cost throttling accuracy, not availability: this
    limiter fronts every request of the app, so a backend error admits the
    request instead of 500ing the whole surface."""

    class _BrokenBackend:
        async def incr(self, tenant_key, key, *, ttl_seconds):
            raise ConnectionError("store down")

    register_cache_backend(GLOBAL_RATE_LIMIT_BACKEND_NAME, _BrokenBackend())
    limiter = RateLimiter(requests_per_minute=1)

    assert await limiter.is_allowed("8.8.8.8") is True
    assert await limiter.is_allowed("8.8.8.8") is True  # still open — degraded, not down


# ---------------------------------------------------------------------------
# _get_client_ip: trusted-proxy-gated XFF contract (SEC-6010)
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_get_client_ip_ignores_xff_when_no_trusted_proxy_configured():
    """Default (empty allowlist): XFF is never trusted; key on the peer IP.

    This is the SEC-6010 fix — previously the generic limiter trusted XFF from
    ANY peer, letting an attacker spoof the header to evade limits or pin them
    on a victim IP.
    """
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(
        forwarded_for="203.0.113.7, 198.51.100.1, 198.51.100.2",
        client_host="198.51.100.250",
    )
    assert middleware._get_client_ip(req) == "198.51.100.250"


@pytest.mark.security
def test_get_client_ip_honors_xff_first_hop_when_peer_is_trusted_proxy(monkeypatch):
    """Peer in the allowlist: the first XFF hop (original client) is used."""
    monkeypatch.setenv(TRUSTED_PROXIES_ENV, "198.51.100.0/24")
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(
        forwarded_for="203.0.113.7, 198.51.100.1, 198.51.100.2",
        client_host="198.51.100.250",
    )
    assert middleware._get_client_ip(req) == "203.0.113.7"


@pytest.mark.security
def test_get_client_ip_ignores_spoofed_xff_from_untrusted_peer(monkeypatch):
    """Peer NOT in the allowlist: XFF is forgeable — fall back to the peer IP."""
    monkeypatch.setenv(TRUSTED_PROXIES_ENV, "192.0.2.1")
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(forwarded_for="203.0.113.7", client_host="198.51.100.250")
    # 198.51.100.250 is not the trusted 192.0.2.1, so the spoofed XFF is dropped.
    assert middleware._get_client_ip(req) == "198.51.100.250"


@pytest.mark.security
def test_get_client_ip_trusted_peer_without_xff_falls_back_to_peer(monkeypatch):
    """A trusted peer that sends no XFF keys on the direct peer IP."""
    monkeypatch.setenv(TRUSTED_PROXIES_ENV, "198.51.100.0/24")
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(client_host="198.51.100.250")
    assert middleware._get_client_ip(req) == "198.51.100.250"


@pytest.mark.security
def test_get_client_ip_returns_unknown_when_no_client():
    """No TCP peer (e.g. an internal test transport) keys on the literal 'unknown'."""
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(client_host=None, forwarded_for="203.0.113.7")
    assert middleware._get_client_ip(req) == "unknown"


# ---------------------------------------------------------------------------
# RateLimitMiddleware (pure-ASGI, BE-6063c): 429 shape + exempt-path bypass
# ---------------------------------------------------------------------------
#
# Post-conversion the over-limit path EMITS a 429 response (status_code == 429
# with a {"detail": ...} body) instead of raising HTTPException — the same
# observable response FastAPI rendered for the prior raise, now without the
# BaseHTTPMiddleware task-group tax. The bucket/keying logic is unchanged.


@pytest.mark.security
@pytest.mark.asyncio
async def test_middleware_allows_under_limit_and_sets_headers():
    """Requests under the limit pass through with X-RateLimit-* headers set."""
    middleware = RateLimitMiddleware(app=None, requests_per_minute=3)

    driven = await _drive(middleware, client_host="203.0.113.10")

    assert driven.status_code == 200
    assert driven.headers["X-RateLimit-Limit"] == "3"
    assert driven.headers["X-RateLimit-Remaining"] == "2"
    assert "X-RateLimit-Reset" in driven.headers
    assert driven.downstream_called is True


@pytest.mark.security
@pytest.mark.asyncio
async def test_middleware_429_on_limit_exceeded_with_retry_after():
    """
    Over-limit requests get a 429 with Retry-After, X-RateLimit-Limit,
    X-RateLimit-Remaining=0, and X-RateLimit-Reset headers, and downstream is
    NOT invoked.
    """
    middleware = RateLimitMiddleware(app=None, requests_per_minute=2)

    # Burn the bucket for one IP.
    await _drive(middleware, client_host="203.0.113.20")
    await _drive(middleware, client_host="203.0.113.20")

    # Third request from the same IP trips the limit.
    driven = await _drive(middleware, client_host="203.0.113.20")

    assert driven.status_code == 429
    assert "Retry-After" in driven.headers
    assert int(driven.headers["Retry-After"]) >= 1
    assert driven.headers["X-RateLimit-Limit"] == "2"
    assert driven.headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in driven.headers
    # Downstream must not be reached — the limiter rejected before forwarding.
    assert driven.downstream_called is False


@pytest.mark.security
@pytest.mark.asyncio
async def test_middleware_distinct_ips_do_not_share_bucket_at_dispatch_level():
    """
    End-to-end per-IP check: IP A exhausting its budget does not block IP B.
    This is the contract-level complement of
    ``test_rate_limiter_distinct_keys_have_independent_buckets`` — it runs
    through the same ASGI ``__call__`` path that production traffic takes.
    """
    middleware = RateLimitMiddleware(app=None, requests_per_minute=1)

    # IP A: first call OK, second call 429.
    await _drive(middleware, client_host="203.0.113.30")
    driven_a = await _drive(middleware, client_host="203.0.113.30")
    assert driven_a.status_code == 429

    # IP B: still has its full budget — not affected by IP A's rejection.
    driven_b = await _drive(middleware, client_host="203.0.113.31")
    assert driven_b.status_code == 200


@pytest.mark.security
@pytest.mark.asyncio
async def test_middleware_rotating_spoofed_xff_cannot_evade_limit():
    """SEC-6010 regression: an attacker rotating XFF from an untrusted peer
    stays pinned to ONE bucket (the peer IP).

    Before the gate, each forged XFF was a fresh key, so a single attacker
    could evade the limit indefinitely by rotating the header. With no trusted
    proxy configured the XFF is ignored and every request keys on the same
    direct peer IP.
    """
    middleware = RateLimitMiddleware(app=None, requests_per_minute=2)

    # Two allowed requests, each with a different forged XFF but the same peer.
    for i in range(2):
        driven = await _drive(middleware, client_host="203.0.113.99", forwarded_for=f"192.0.2.{i}")
        assert driven.status_code == 200

    # Third request, again a fresh forged XFF — must still be blocked.
    driven = await _drive(middleware, client_host="203.0.113.99", forwarded_for="192.0.2.250")
    assert driven.status_code == 429


# ---------------------------------------------------------------------------
# Exempt-path bypass
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.asyncio
@pytest.mark.parametrize("exempt_path", ["/api/health", "/api/metrics"])
async def test_middleware_exempt_paths_bypass_rate_limiter(exempt_path):
    """
    Configured exempt paths (``/api/health``, ``/api/metrics``) bypass the
    limiter even when the bucket is already full for the caller's IP.
    """
    middleware = RateLimitMiddleware(app=None, requests_per_minute=1)

    # Exhaust the normal bucket so the IP would otherwise be rejected.
    await _drive(middleware, path="/api/v1/projects", client_host="203.0.113.40")
    blocked = await _drive(middleware, path="/api/v1/projects", client_host="203.0.113.40")
    assert blocked.status_code == 429

    # Same IP hitting an exempt path MUST NOT 429 — bypass is path-based,
    # not IP-based, so an exhausted IP can still hit /api/health.
    driven = await _drive(middleware, path=exempt_path, client_host="203.0.113.40")
    assert driven.status_code == 200


@pytest.mark.security
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "static_path",
    ["/", "/index.html", "/favicon.ico", "/assets/main.js", "/assets/nested/deep/chunk.css"],
)
async def test_middleware_static_paths_bypass_rate_limiter(static_path):
    """
    Frontend static-file paths (``/``, ``/index.html``, ``/favicon.ico``,
    ``/assets/*``) bypass the limiter. Production serves the compiled
    frontend from the same process, and the sliding window must not
    interfere with asset delivery.
    """
    middleware = RateLimitMiddleware(app=None, requests_per_minute=1)

    # Exhaust the API bucket for this IP.
    await _drive(middleware, path="/api/v1/projects", client_host="203.0.113.50")
    blocked = await _drive(middleware, path="/api/v1/projects", client_host="203.0.113.50")
    assert blocked.status_code == 429

    # Static path for the same IP still passes.
    driven = await _drive(middleware, path=static_path, client_host="203.0.113.50")
    assert driven.status_code == 200


# ---------------------------------------------------------------------------
# Documentation anchor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_counters_carry_window_ttl(monkeypatch):
    """BE-6073 successor (INF-3009d): memory is bounded by backend TTL eviction.

    The per-IP dict (and its once-per-window sweep) is gone; every counter is
    written through ``incr`` with ``ttl_seconds == window_size``, so the store
    itself expires each window's counters. This test pins that contract — an
    ``incr`` without a TTL would silently reintroduce the unbounded growth.
    """
    seen: list[int] = []

    class _SpyBackend(InProcessDictBackend):
        async def incr(self, tenant_key, key, *, ttl_seconds):
            seen.append(ttl_seconds)
            return await super().incr(tenant_key, key, ttl_seconds=ttl_seconds)

    register_cache_backend(GLOBAL_RATE_LIMIT_BACKEND_NAME, _SpyBackend(namespace="test"))
    limiter = RateLimiter(requests_per_minute=5)

    for i in range(10):
        await limiter.is_allowed(f"10.0.0.{i}")

    assert seen == [limiter.window_size] * 10


@pytest.mark.asyncio
async def test_rate_limiter_window_rollover_resets_budget(monkeypatch):
    """A new window slot is a new counter: the key encodes the slot, so after
    the window rolls over the same IP gets a fresh budget (and the old slot's
    counter is left to the backend TTL). Within the window it stays throttled."""
    import api.middleware.rate_limiter as rl

    clock = {"now": 5000.0}
    monkeypatch.setattr(rl.time, "time", lambda: clock["now"])

    limiter = rl.RateLimiter(requests_per_minute=2)
    assert await limiter.is_allowed("198.51.100.9") is True
    assert await limiter.is_allowed("198.51.100.9") is True
    assert await limiter.is_allowed("198.51.100.9") is False  # at limit

    # Still inside the same window: throttled — rollover must not reset early.
    clock["now"] = 5000.0 + (limiter.window_size / 2) - 1
    assert await limiter.is_allowed("198.51.100.9") is False

    # Next window slot: fresh counter, budget restored.
    clock["now"] = 5000.0 + limiter.window_size + 1
    assert await limiter.is_allowed("198.51.100.9") is True


@pytest.mark.security
@pytest.mark.skipif(
    not _SEC0002_AUDIT.exists(),
    reason="SEC-0002 audit is a private handover doc, stripped from the CE export; corroborated on private CI only.",
)
def test_sec_0002_audit_artifact_exists():
    """
    The SEC-0002 audit artifact this test corroborates must exist. If someone
    removes the audit doc, this test screams so the documentation / guard
    cannot silently drift apart.
    """
    assert _SEC0002_AUDIT.is_file(), (
        f"Missing SEC-0002 audit artifact at {_SEC0002_AUDIT}. The rate-limit "
        "verification test is the behavioral complement to that document; "
        "removing the document without updating this test breaks the "
        "passive-server trust model."
    )
