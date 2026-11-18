# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import hashlib
import logging
import os
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

LOGIN_ACCOUNT_WINDOW_SECONDS = 300
_LOGIN_ATTEMPTS_PER_ADDRESS_PAST_CEILING = 1
PER_ADDRESS_PAST_CEILING_ENV = "GILJO_LOGIN_PER_ADDRESS_PAST_CEILING"
_TRUTHY = {"1", "true", "yes", "on"}


def _per_address_hold_enabled() -> bool:
    return os.getenv(PER_ADDRESS_PAST_CEILING_ENV, "").strip().lower() in _TRUTHY


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

    def _admission_ip(self, request: Request) -> str | None:
        ip, from_header = self._ip_resolver.resolve_with_origin(request)
        if not from_header and is_exempt_ip(ip):
            return None
        return ip

    @staticmethod
    def _bucket_key(subject: str, window: int) -> str:
        bucket = int(time.time()) // window
        return f"{subject}:{bucket}"

    @staticmethod
    def _policy_key(request: Request, policy: str | None) -> str:
        if policy:
            return policy
        route = (getattr(request, "scope", None) or {}).get("route")
        return getattr(route, "path", None) or request.url.path

    async def check_rate_limit(
        self,
        request: Request,
        limit: int | None = None,
        window: int = 60,
        raise_on_limit: bool = False,
        *,
        policy: str | None = None,
    ) -> bool:
        if is_test_bypass_enabled():
            return True

        ip = self._admission_ip(request)
        if ip is None:
            return True
        if limit is None:
            limit = limit_for(policy)

        count = await self._backend.incr(
            _RATE_LIMIT_TENANT_SENTINEL,
            self._bucket_key(f"{self._policy_key(request, policy)}:{ip}", window),
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

    async def check_login_account_ceiling(self, request: Request, identifier: str) -> None:
        if is_test_bypass_enabled():
            return
        ip = self._admission_ip(request)
        if ip is None:
            return

        window = LOGIN_ACCOUNT_WINDOW_SECONDS
        account = hashlib.sha256(identifier.strip().lower().encode()).hexdigest()[:32]
        attempts = await self._backend.incr(
            _RATE_LIMIT_TENANT_SENTINEL,
            self._bucket_key(f"login_account:{account}", window),
            ttl_seconds=window,
        )
        if attempts <= limit_for("login_account"):
            return
        logger.warning("Login account ceiling exceeded - account=%s attempts=%d", account, attempts)
        if not _per_address_hold_enabled():
            return
        from_this_address = await self._backend.incr(
            _RATE_LIMIT_TENANT_SENTINEL,
            self._bucket_key(f"login_account_ip:{account}:{ip}", window),
            ttl_seconds=window,
        )
        if from_this_address <= _LOGIN_ATTEMPTS_PER_ADDRESS_PAST_CEILING:
            return

        logger.warning("Login account ceiling hold - IP: %s, account=%s", sanitize(ip), account)
        retry_after = max(1, int((int(time.time()) // window + 1) * window - time.time()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts for this account. Try again in a few minutes.",
            headers={"Retry-After": str(retry_after)},
        )


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
        policy="api_key_auth_failed",
    )
