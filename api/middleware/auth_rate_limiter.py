# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Rate Limiting for Authentication Endpoints (Handover 1009, SEC-6001).

Implements per-IP sliding-window rate limiting for sensitive auth endpoints:
- Login: 5 attempts/minute
- Register: 3 attempts/minute
- Password Reset: 3 attempts/minute

SEC-6001 hardening (Edition Scope: Both):

Unit 1 — proxy-aware client IP. Behind a reverse proxy (the hosted platform, nginx) the
TCP peer (`request.client.host`) is the proxy's shared IP, so naive per-IP
keying collapses every caller into one bucket. We honor the FIRST-HOP
`X-Forwarded-For` entry ONLY when the immediate peer is in the
operator-configured trusted-proxy allowlist (`GILJO_TRUSTED_PROXIES`,
comma-separated CIDR or exact IPs). When the peer is untrusted, XFF is a
forgeable client header and is ignored entirely — the allowlist gate IS the
spoofing protection. Default (empty allowlist) preserves the pre-SEC-6001
behavior: no proxy trusted, key on `request.client.host`.

Unit 2 — shared limiter store. The counters live in the `CacheBackend`
registry instead of a per-process dict, so multi-worker deployments enforce
ONE combined limit rather than `limit * workers`. CE (no Redis) transparently
falls back to the registry's default `InProcessDictBackend` (single-process);
hosted SaaS registers a shared Redis backend under the same name at startup.
This CE module never imports the Redis adapter — the registry decouples them.

BE-6006 — atomic counter. The window is a fixed-window counter incremented
through the backend's atomic `incr` (a single Redis Lua INCR+EXPIRE on SaaS),
NOT a get()+modify+set() of a timestamp list. The old read-modify-write raced
across workers/concurrent requests: N callers could each read the same
sub-limit count and all be admitted, so the effective ceiling drifted above
`limit`. `incr` returns a distinct monotonic count per caller, so the limit
holds exactly. Fixed-window carries the usual up-to-2x burst at a window
boundary — the same trade-off the SaaS per-tenant RateLimitStore already makes.

SEC-9227 (H4) — the test bypass is no longer request-derived. It used to read
``request.base_url`` and exempt requests whose base URL carried a fixed test
prefix, which made it forgeable: because ``base_url`` is built from the inbound
``Host`` header, a client sending ``Host: testanything`` disabled every
pre-auth limit for itself. The bypass is now an explicit process-local flag
(``auth_rate_limits.set_test_bypass``) that defaults to OFF and takes no
request input, so a test can bypass but an inbound request never can.
"""

import logging
import time

from fastapi import HTTPException, Request, status

from giljo_mcp.services.cache_backends import (
    AUTH_RATE_LIMIT_BACKEND_NAME,
    get_cache_backend,
)
from giljo_mcp.utils.log_sanitizer import sanitize

from ._proxy_aware_ip import TRUSTED_PROXIES_ENV, ProxyAwareIpResolver
from .auth_rate_limits import is_exempt_ip, is_test_bypass_enabled, limit_for


logger = logging.getLogger(__name__)


# AUTH_RATE_LIMIT_BACKEND_NAME now lives in cache_backends.py (BE-6063f) so the
# SaaS Redis adapter can register a shared backend under it without an
# api/ -> saas/ import. Re-exported here for back-compat with existing imports.
__all__ = [
    "AUTH_RATE_LIMIT_BACKEND_NAME",
    "RateLimiter",
    "enforce_api_key_auth_failure",
    "get_rate_limiter",
]

# Rate limiting runs BEFORE authentication, so there is no tenant context. The
# CacheBackend contract scopes every key by tenant_key; we pass a fixed sentinel
# so the auth-limiter counters share one logical namespace without colliding
# with any real tenant's data.
_RATE_LIMIT_TENANT_SENTINEL = "_ratelimit"

# Backwards-compatible alias: the trusted-proxy env name now lives in the shared
# resolver module (SEC-6010). Re-exported so existing imports keep working.
_TRUSTED_PROXIES_ENV = TRUSTED_PROXIES_ENV


class RateLimiter:
    """
    Rate limiter using a sliding window over a shared CacheBackend.

    Features:
    - IP-based isolation (separate counters per resolved client IP)
    - Proxy-aware IP resolution gated on a trusted-proxy allowlist
    - Atomic fixed-window counter (backend `incr`) — race-free across workers
    - Shared store (multi-worker safe) via the CacheBackend registry
    - HTTP 429 responses with Retry-After header
    - Logging of violations for monitoring
    """

    def __init__(self):
        """Initialize the limiter against the shared auth-limiter backend.

        Trusted proxies are resolved once at construction from
        ``GILJO_TRUSTED_PROXIES``. The limiter is a process-lifetime singleton
        (see ``get_rate_limiter``), so a deploy-time env change is picked up on
        the next boot — the expected lifecycle for an infrastructure setting.
        """
        self._backend = get_cache_backend(AUTH_RATE_LIMIT_BACKEND_NAME)
        self._ip_resolver = ProxyAwareIpResolver()
        logger.info(
            "RateLimiter initialized (shared CacheBackend, trusted_proxies=%d)",
            self._ip_resolver.trusted_proxy_count,
        )

    def _get_client_ip(self, request: Request) -> str:
        return self._ip_resolver.resolve(request)

    @staticmethod
    def _bucket_key(ip: str, window: int) -> str:
        """Per-IP fixed-window bucket key: distinct per IP and per window slot.

        Encoding the window slot in the key means a new window is simply a new
        counter — no reset bookkeeping — and the backend's `ttl_seconds` expiry
        garbage-collects the previous slot.
        """
        bucket = int(time.time()) // window
        return f"{ip}:{bucket}"

    async def check_rate_limit(
        self, request: Request, limit: int, window: int = 60, raise_on_limit: bool = False
    ) -> bool:
        """
        Check if request is within rate limit.

        Args:
            request: FastAPI request object
            limit: Maximum requests allowed in window
            window: Time window in seconds (default: 60)
            raise_on_limit: If True, raise HTTPException when limit exceeded

        Returns:
            True if request is allowed, False if blocked

        Raises:
            HTTPException: 429 if limit exceeded and raise_on_limit=True
        """
        # SEC-9227 (H4): the ONLY bypass is an explicit, process-local test
        # flag — never anything derived from the request. The check this
        # replaced read ``request.base_url`` (the inbound Host header), so any
        # client could exempt itself from every pre-auth limit by sending
        # ``Host: testanything``. Defaults to OFF: production never bypasses.
        if is_test_bypass_enabled():
            return True

        ip = self._get_client_ip(request)

        # CE-only loopback exemption (BE-6063f): a self-hosted single-operator
        # install must not lock its own operator out of localhost login. SaaS
        # never exempts — is_exempt_ip returns False there unconditionally.
        if is_exempt_ip(ip):
            return True

        # BE-6006: one atomic INCR replaces the get()+modify+set() that raced
        # across workers. The returned count is this caller's exact position in
        # the window, so the limit holds even under concurrent admission.
        count = await self._backend.incr(
            _RATE_LIMIT_TENANT_SENTINEL,
            self._bucket_key(ip, window),
            ttl_seconds=window,
        )

        if count <= limit:
            return True

        endpoint = request.url.path if hasattr(request.url, "path") else "unknown"
        logger.warning(
            f"Rate limit exceeded - IP: {sanitize(ip)}, Endpoint: {sanitize(endpoint)}, "
            f"Limit: {limit}/{window}s, Count: {count}"
        )

        now = time.time()
        reset_time = ((int(now) // window) + 1) * window
        retry_after = max(1, int(reset_time - now))

        if raise_on_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Limit: {limit} per {window} seconds. Try again later.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Window": str(window),
                },
            )

        return False


# Module-level rate limiter instance (initialized lazily)
class _RateLimiterHolder:
    """Lazy singleton holder to avoid global statement."""

    _instance: RateLimiter | None = None

    @classmethod
    def get_instance(cls) -> RateLimiter:
        if cls._instance is None:
            cls._instance = RateLimiter()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """Test-only: drop the cached singleton so the next call rebuilds it.

        Lets a test change ``GILJO_TRUSTED_PROXIES`` and observe a fresh
        limiter. Production code MUST NOT call this.
        """
        cls._instance = None


def get_rate_limiter() -> RateLimiter:
    """
    Get or create global rate limiter instance.

    Returns:
        RateLimiter instance
    """
    return _RateLimiterHolder.get_instance()


async def enforce_api_key_auth_failure(request: Request) -> None:
    """Record a FAILED API-key authentication for this IP; raise 429 if over budget.

    BE-6060b. Call this ONLY after a verification failure (no matching key), so a
    valid key never accrues against the limit. It reuses the shared per-IP
    sliding-window limiter — proxy-aware client IP, multi-worker-safe store, and
    the CE loopback exemption all apply unchanged — and the
    ``api_key_auth_failed`` policy limit. The first N failures in the window are
    recorded and return normally; the (N+1)th raises ``HTTPException(429)`` with a
    ``Retry-After`` header.

    Rationale: even with the prefix-narrowed candidate gate (verify is unreachable
    without a key_prefix index hit) a client that knows a displayed prefix could
    spray bcrypt verifies against legacy rows. Throttling failed attempts per IP
    caps that, and brute-force in general, without ever touching the happy path.

    Args:
        request: The inbound request (used to resolve the client IP).

    Raises:
        HTTPException: 429 once the IP exceeds its failed-auth budget.
    """
    limiter = get_rate_limiter()
    await limiter.check_rate_limit(
        request,
        limit=limit_for("api_key_auth_failed"),
        window=60,
        raise_on_limit=True,
    )
