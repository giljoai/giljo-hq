# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import time
from dataclasses import dataclass

from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from giljo_mcp.services.cache_backends import (
    GLOBAL_RATE_LIMIT_BACKEND_NAME,
    get_cache_backend,
)

from ._proxy_aware_ip import ProxyAwareIpResolver


logger = logging.getLogger(__name__)


_RATE_LIMIT_TENANT_SENTINEL = "_ratelimit"


class _TestBypass:

    enabled: bool = False


def set_test_bypass(enabled: bool) -> None:
    _TestBypass.enabled = bool(enabled)


def is_test_bypass_enabled() -> bool:
    return _TestBypass.enabled


@dataclass(frozen=True, slots=True)
class RateLimitDecision:

    allowed: bool
    limit: int
    remaining: int
    reset_time: float


class RateLimiter:

    def __init__(self, requests_per_minute: int = 100, *, scope: str = "global"):
        self.requests_per_minute = requests_per_minute
        self.window_size = 60
        self._scope = scope
        logger.debug(f"RateLimiter initialized: {requests_per_minute} req/min, scope={scope}")

    def _bucket_key(self, key: str, now: float) -> str:
        slot = int(now) // self.window_size
        return f"{self._scope}:{key}:{slot}"

    def _reset_time(self, now: float) -> float:
        return ((int(now) // self.window_size) + 1) * self.window_size

    async def hit(self, key: str) -> RateLimitDecision:
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
        return (await self.hit(key)).allowed


class RateLimitMiddleware:

    def __init__(self, app: ASGIApp, requests_per_minute: int = 100, exempt_paths: list = None):
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
        return self._ip_resolver.resolve(request)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _TestBypass.enabled:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        path = request.url.path
        if path in {"/", "/index.html", "/favicon.ico"} or path.startswith("/assets/"):
            await self.app(scope, receive, send)
            return

        if path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        client_ip = self._get_client_ip(request)

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
                    "Retry-After": str(max(1, retry_after)),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(decision.reset_time)),
                },
            )
            await response(scope, receive, send)
            return

        async def send_with_rate_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message["headers"])
                headers["X-RateLimit-Limit"] = str(decision.limit)
                headers["X-RateLimit-Remaining"] = str(decision.remaining)
                headers["X-RateLimit-Reset"] = str(int(decision.reset_time))
            await send(message)

        await self.app(scope, receive, send_with_rate_headers)
