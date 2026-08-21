# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Rate Limiting Middleware

Implements per-IP rate limiting to prevent abuse and DoS attacks.

Created in Handover 0129c - Security Hardening & OWASP Compliance.

INF-3009d — shared-store rewrite. The limiter's counters live in the
``CacheBackend`` registry (``GLOBAL_RATE_LIMIT_BACKEND_NAME``) instead of a
per-process ``dict[str, deque]``:

* Multi-worker correctness: under ``WEB_CONCURRENCY=N`` the old per-process
  dict silently multiplied every limit by N (each worker kept its own bucket).
  With the shared store (SaaS registers Redis at startup) all workers consume
  ONE combined budget. CE (no Redis) transparently falls back to the registry's
  in-process default — identical single-worker behavior, zero new config.
* Bounded memory: counters are TTL-evicted by the backend (one window), so the
  old leak-one-entry-per-IP-forever bug (BE-6073) is structurally gone.
* Atomic admission: the window is a fixed-window counter incremented through
  the backend's atomic ``incr`` (a server-side Lua INCR+EXPIRE on Redis), not a
  read-modify-write — the same BE-6006 pattern the pre-auth limiter uses. The
  sliding window is traded for a fixed window (up to 2x burst at a boundary),
  the trade-off both existing shared-store limiters already make.
"""

import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from giljo_mcp.services.cache_backends import (
    GLOBAL_RATE_LIMIT_BACKEND_NAME,
    get_cache_backend,
)

from ._proxy_aware_ip import ProxyAwareIpResolver


logger = logging.getLogger(__name__)


# The limiter runs before authentication, so there is no tenant context. The
# CacheBackend contract scopes every key by tenant_key; a fixed sentinel gives
# the counters one logical namespace (same pattern as the auth limiter).
_RATE_LIMIT_TENANT_SENTINEL = "_ratelimit"


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Outcome of one admission check, carrying everything the headers need."""

    allowed: bool
    limit: int
    remaining: int
    reset_time: float


class RateLimiter:
    """
    Fixed-window rate limiter over the shared ``CacheBackend``.

    One atomic ``incr`` per admission: the returned count is this caller's
    exact position in the window, so the limit holds across workers and
    concurrent requests. Encoding the window slot in the key makes a new
    window a new counter — the backend's TTL garbage-collects the old slot.
    """

    def __init__(self, requests_per_minute: int = 100, *, scope: str = "global"):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per window (default: 100)
            scope: Key prefix separating independent limiters that share the
                backend (the global middleware vs. a per-endpoint decorator).
        """
        self.requests_per_minute = requests_per_minute
        self.window_size = 60  # 1 minute in seconds
        self._scope = scope
        logger.debug(f"RateLimiter initialized: {requests_per_minute} req/min, scope={scope}")

    def _bucket_key(self, key: str, now: float) -> str:
        slot = int(now) // self.window_size
        return f"{self._scope}:{key}:{slot}"

    def _reset_time(self, now: float) -> float:
        return ((int(now) // self.window_size) + 1) * self.window_size

    async def hit(self, key: str) -> RateLimitDecision:
        """Consume one slot for ``key`` and return the admission decision.

        The backend is resolved per call (a dict lookup) so the SaaS Redis
        registration at lifespan startup is picked up even though the
        middleware itself is constructed earlier, at app wiring.

        A backend error degrades to availability, logged with a warning: this
        limiter fronts every request of the app, so a degraded store must cost
        throttling accuracy, not availability. (The auth limiter's stricter posture guards only the
        credential endpoints.)
        """
        now = time.time()
        reset_time = self._reset_time(now)
        try:
            count = await get_cache_backend(GLOBAL_RATE_LIMIT_BACKEND_NAME).incr(
                _RATE_LIMIT_TENANT_SENTINEL,
                self._bucket_key(key, now),
                ttl_seconds=self.window_size,
            )
        except Exception:  # noqa: BLE001 — availability over throttling accuracy
            logger.warning("rate_limiter_backend_error scope=%s — failing open", self._scope, exc_info=True)
            return RateLimitDecision(
                allowed=True,
                limit=self.requests_per_minute,
                remaining=max(0, self.requests_per_minute - 1),
                reset_time=reset_time,
            )
        return RateLimitDecision(
            allowed=count <= self.requests_per_minute,
            limit=self.requests_per_minute,
            remaining=max(0, self.requests_per_minute - count),
            reset_time=reset_time,
        )

    async def is_allowed(self, key: str) -> bool:
        """
        Check if request is allowed for given key (e.g., IP address).

        Consumes one slot (thin wrapper over ``hit``).
        """
        return (await self.hit(key)).allowed


class RateLimitMiddleware:
    """
    Rate limiting middleware.

    Applies rate limits per IP address to prevent abuse and DoS attacks.

    Features:
    - Per-IP rate limiting, one combined budget across workers (shared store)
    - Configurable exempt paths (health checks, metrics)
    - X-RateLimit-* headers for client information
    - Trusted-proxy-gated X-Forwarded-For resolution (SEC-6010): XFF is honored
      only when the immediate peer is in GILJO_TRUSTED_PROXIES, else ignored
    """

    def __init__(self, app: ASGIApp, requests_per_minute: int = 100, exempt_paths: list = None):
        """
        Initialize rate limit middleware.

        Args:
            app: FastAPI application instance
            requests_per_minute: Global rate limit (default: 100 req/min)
            exempt_paths: Paths excluded from rate limiting (default: /api/health, /api/metrics)
        """
        self.app = app
        self.rate_limiter = RateLimiter(requests_per_minute)
        self.exempt_paths = exempt_paths or ["/api/health", "/api/metrics"]
        self._ip_resolver = ProxyAwareIpResolver()
        logger.info(
            f"RateLimitMiddleware initialized: {requests_per_minute} req/min, "
            f"exempt paths: {self.exempt_paths}, "
            f"trusted_proxies={self._ip_resolver.trusted_proxy_count}"
        )

    def _get_client_ip(self, request: Request) -> str:
        """
        Resolve the client IP used for rate-limit keying.

        Trusted-proxy gated (SEC-6010): the ``X-Forwarded-For`` first hop is
        honored ONLY when the immediate peer is in the ``GILJO_TRUSTED_PROXIES``
        allowlist. From an untrusted peer, XFF is a spoofable header and is
        ignored — keying falls back to the direct peer IP. This is the same
        single-source-of-truth resolver the auth limiter uses.
        """
        return self._ip_resolver.resolve(request)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Apply rate limiting to the request.

        Pure-ASGI (BE-6063c): on limit exceed, emits a 429 with body
        ``{"detail": "Rate limit exceeded. Please try again later."}`` plus the
        Retry-After / X-RateLimit-* headers — identical to the shape FastAPI's
        handler produced for the prior ``raise HTTPException(429, ...)``. On the
        allow path, the X-RateLimit-* headers are injected onto the downstream
        response's ``http.response.start`` (body forwarded untouched, so /mcp
        streaming is unaffected). One atomic backend ``incr`` per request; the
        headers are computed from that single decision.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # Skip rate limiting for static file requests (production frontend serving)
        path = request.url.path
        if path in {"/", "/index.html", "/favicon.ico"} or path.startswith("/assets/"):
            await self.app(scope, receive, send)
            return

        # Exempt certain paths (health checks, metrics, etc.)
        if path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        # Get client IP
        client_ip = self._get_client_ip(request)

        # Check rate limit (single atomic incr; decision carries the header values)
        decision = await self.rate_limiter.hit(client_ip)
        if not decision.allowed:
            logger.warning(
                f"Rate limit exceeded for IP: {client_ip}, path: {request.url.path}, method: {request.method}"
            )

            retry_after = int(decision.reset_time - time.time())

            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please try again later."},
                headers={
                    "Retry-After": str(max(1, retry_after)),  # At least 1 second
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(decision.reset_time)),
                },
            )
            await response(scope, receive, send)
            return

        # Allow: inject rate-limit headers onto the downstream response.
        async def send_with_rate_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message["headers"])
                headers["X-RateLimit-Limit"] = str(decision.limit)
                headers["X-RateLimit-Remaining"] = str(decision.remaining)
                headers["X-RateLimit-Reset"] = str(int(decision.reset_time))
            await send(message)

        await self.app(scope, receive, send_with_rate_headers)


class EndpointRateLimiter:
    """
    Decorator for per-endpoint rate limiting.

    Allows stricter rate limits on specific endpoints (e.g., login, signup).

    Usage:
        from api.middleware.rate_limiter import EndpointRateLimiter

        @router.post("/login")
        @EndpointRateLimiter(requests_per_minute=10)
        async def login(request: Request, credentials: LoginCredentials):
            # Login logic...
            pass

    This is ADDITIONAL to global rate limiting (both limits apply).
    """

    def __init__(self, requests_per_minute: int):
        """
        Initialize endpoint rate limiter.

        Args:
            requests_per_minute: Rate limit for this specific endpoint
        """
        self.requests_per_minute = requests_per_minute

    def __call__(self, func):
        """
        Decorate endpoint function with rate limiting.

        The limiter scope is derived from the decorated function's qualified
        name — stable across workers, so all workers share one bucket per
        endpoint, and distinct endpoints never share counters.

        Args:
            func: Endpoint function to decorate

        Returns:
            Wrapped function with rate limiting
        """
        rate_limiter = RateLimiter(
            self.requests_per_minute,
            scope=f"endpoint:{func.__module__}.{func.__qualname__}",
        )

        async def wrapper(*args, **kwargs):
            # Extract request from args or kwargs
            request = kwargs.get("request") or (args[0] if args else None)

            if not request or not isinstance(request, Request):
                logger.error("EndpointRateLimiter: Could not extract Request object")
                return await func(*args, **kwargs)

            # Get client IP
            client_ip = request.client.host if request.client else "unknown"

            # Check endpoint-specific rate limit
            decision = await rate_limiter.hit(client_ip)
            if not decision.allowed:
                logger.warning(
                    f"Endpoint rate limit exceeded for IP: {client_ip}, "
                    f"endpoint: {request.url.path}, limit: {self.requests_per_minute}/min"
                )

                retry_after = int(decision.reset_time - time.time())

                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded for this endpoint. Limit: {self.requests_per_minute}/min",
                    headers={
                        "Retry-After": str(max(1, retry_after)),
                        "X-RateLimit-Limit": str(self.requests_per_minute),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(decision.reset_time)),
                    },
                )

            return await func(*args, **kwargs)

        return wrapper
