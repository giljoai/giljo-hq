# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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


__all__ = [
    "AUTH_RATE_LIMIT_BACKEND_NAME",
    "RateLimiter",
    "enforce_api_key_auth_failure",
    "get_rate_limiter",
]

_RATE_LIMIT_TENANT_SENTINEL = "_ratelimit"

_TRUSTED_PROXIES_ENV = TRUSTED_PROXIES_ENV


class RateLimiter:

    def __init__(self):
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
        bucket = int(time.time()) // window
        return f"{ip}:{bucket}"

    async def check_rate_limit(
        self, request: Request, limit: int, window: int = 60, raise_on_limit: bool = False
    ) -> bool:
        if is_test_bypass_enabled():
            return True

        ip = self._get_client_ip(request)

        if is_exempt_ip(ip):
            return True

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


class _RateLimiterHolder:

    _instance: RateLimiter | None = None

    @classmethod
    def get_instance(cls) -> RateLimiter:
        if cls._instance is None:
            cls._instance = RateLimiter()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        cls._instance = None


def get_rate_limiter() -> RateLimiter:
    return _RateLimiterHolder.get_instance()


async def enforce_api_key_auth_failure(request: Request) -> None:
    limiter = get_rate_limiter()
    await limiter.check_rate_limit(
        request,
        limit=limit_for("api_key_auth_failed"),
        window=60,
        raise_on_limit=True,
    )
