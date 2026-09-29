# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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


pytestmark = pytest.mark.usefixtures("real_rate_limiter")

_SEC0002_AUDIT = Path(__file__).resolve().parents[2] / "handovers" / "security" / "SEC-0002_passive_server_audit.md"


@pytest.fixture(autouse=True)
def _isolated_rate_limit_backend():
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
    monkeypatch.delenv(TRUSTED_PROXIES_ENV, raising=False)




def _make_request(
    *,
    path: str = "/api/v1/projects",
    method: str = "GET",
    forwarded_for: str | None = None,
    client_host: str | None = "127.0.0.1",
) -> SimpleNamespace:
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




@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_same_key_shares_bucket():
    limiter = RateLimiter(requests_per_minute=2)

    assert await limiter.is_allowed("1.1.1.1") is True
    assert await limiter.is_allowed("1.1.1.1") is True
    assert await limiter.is_allowed("1.1.1.1") is False


@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_distinct_keys_have_independent_buckets():
    limiter = RateLimiter(requests_per_minute=2)

    assert await limiter.is_allowed("1.1.1.1") is True
    assert await limiter.is_allowed("1.1.1.1") is True
    assert await limiter.is_allowed("1.1.1.1") is False

    assert await limiter.is_allowed("2.2.2.2") is True
    assert await limiter.is_allowed("2.2.2.2") is True
    assert await limiter.is_allowed("2.2.2.2") is False


@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_hit_reports_remaining():
    limiter = RateLimiter(requests_per_minute=3)

    assert (await limiter.hit("1.1.1.1")).remaining == 2
    assert (await limiter.hit("1.1.1.1")).remaining == 1
    assert (await limiter.hit("1.1.1.1")).remaining == 0
    assert (await limiter.hit("1.1.1.1")).remaining == 0


@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_one_combined_limit_across_workers():
    worker_a = RateLimiter(requests_per_minute=2)
    worker_b = RateLimiter(requests_per_minute=2)

    assert await worker_a.is_allowed("9.9.9.9") is True
    assert await worker_b.is_allowed("9.9.9.9") is True
    assert await worker_a.is_allowed("9.9.9.9") is False
    assert await worker_b.is_allowed("9.9.9.9") is False


@pytest.mark.security
@pytest.mark.asyncio
async def test_rate_limiter_fails_open_on_backend_error():

    class _BrokenBackend:
        async def incr(self, tenant_key, key, *, ttl_seconds):
            raise ConnectionError("store down")

    register_cache_backend(GLOBAL_RATE_LIMIT_BACKEND_NAME, _BrokenBackend())
    limiter = RateLimiter(requests_per_minute=1)

    assert await limiter.is_allowed("8.8.8.8") is True
    assert await limiter.is_allowed("8.8.8.8") is True




@pytest.mark.security
def test_get_client_ip_ignores_xff_when_no_trusted_proxy_configured():
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(
        forwarded_for="203.0.113.7, 198.51.100.1, 198.51.100.2",
        client_host="198.51.100.250",
    )
    assert middleware._get_client_ip(req) == "198.51.100.250"


@pytest.mark.security
def test_get_client_ip_honors_xff_first_hop_when_peer_is_trusted_proxy(monkeypatch):
    monkeypatch.setenv(TRUSTED_PROXIES_ENV, "198.51.100.0/24")
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(
        forwarded_for="203.0.113.7, 198.51.100.1, 198.51.100.2",
        client_host="198.51.100.250",
    )
    assert middleware._get_client_ip(req) == "203.0.113.7"


@pytest.mark.security
def test_get_client_ip_ignores_spoofed_xff_from_untrusted_peer(monkeypatch):
    monkeypatch.setenv(TRUSTED_PROXIES_ENV, "192.0.2.1")
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(forwarded_for="203.0.113.7", client_host="198.51.100.250")
    assert middleware._get_client_ip(req) == "198.51.100.250"


@pytest.mark.security
def test_get_client_ip_trusted_peer_without_xff_falls_back_to_peer(monkeypatch):
    monkeypatch.setenv(TRUSTED_PROXIES_ENV, "198.51.100.0/24")
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(client_host="198.51.100.250")
    assert middleware._get_client_ip(req) == "198.51.100.250"


@pytest.mark.security
def test_get_client_ip_returns_unknown_when_no_client():
    middleware = RateLimitMiddleware(app=None, requests_per_minute=300)

    req = _make_request(client_host=None, forwarded_for="203.0.113.7")
    assert middleware._get_client_ip(req) == "unknown"




@pytest.mark.security
@pytest.mark.asyncio
async def test_middleware_allows_under_limit_and_sets_headers():
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
    middleware = RateLimitMiddleware(app=None, requests_per_minute=2)

    await _drive(middleware, client_host="203.0.113.20")
    await _drive(middleware, client_host="203.0.113.20")

    driven = await _drive(middleware, client_host="203.0.113.20")

    assert driven.status_code == 429
    assert "Retry-After" in driven.headers
    assert int(driven.headers["Retry-After"]) >= 1
    assert driven.headers["X-RateLimit-Limit"] == "2"
    assert driven.headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in driven.headers
    assert driven.downstream_called is False


@pytest.mark.security
@pytest.mark.asyncio
async def test_middleware_distinct_ips_do_not_share_bucket_at_dispatch_level():
    middleware = RateLimitMiddleware(app=None, requests_per_minute=1)

    await _drive(middleware, client_host="203.0.113.30")
    driven_a = await _drive(middleware, client_host="203.0.113.30")
    assert driven_a.status_code == 429

    driven_b = await _drive(middleware, client_host="203.0.113.31")
    assert driven_b.status_code == 200


@pytest.mark.security
@pytest.mark.asyncio
async def test_middleware_rotating_spoofed_xff_cannot_evade_limit():
    middleware = RateLimitMiddleware(app=None, requests_per_minute=2)

    for i in range(2):
        driven = await _drive(middleware, client_host="203.0.113.99", forwarded_for=f"192.0.2.{i}")
        assert driven.status_code == 200

    driven = await _drive(middleware, client_host="203.0.113.99", forwarded_for="192.0.2.250")
    assert driven.status_code == 429




@pytest.mark.security
@pytest.mark.asyncio
@pytest.mark.parametrize("exempt_path", ["/api/health", "/api/metrics"])
async def test_middleware_exempt_paths_bypass_rate_limiter(exempt_path):
    middleware = RateLimitMiddleware(app=None, requests_per_minute=1)

    await _drive(middleware, path="/api/v1/projects", client_host="203.0.113.40")
    blocked = await _drive(middleware, path="/api/v1/projects", client_host="203.0.113.40")
    assert blocked.status_code == 429

    driven = await _drive(middleware, path=exempt_path, client_host="203.0.113.40")
    assert driven.status_code == 200


@pytest.mark.security
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "static_path",
    ["/", "/index.html", "/favicon.ico", "/assets/main.js", "/assets/nested/deep/chunk.css"],
)
async def test_middleware_static_paths_bypass_rate_limiter(static_path):
    middleware = RateLimitMiddleware(app=None, requests_per_minute=1)

    await _drive(middleware, path="/api/v1/projects", client_host="203.0.113.50")
    blocked = await _drive(middleware, path="/api/v1/projects", client_host="203.0.113.50")
    assert blocked.status_code == 429

    driven = await _drive(middleware, path=static_path, client_host="203.0.113.50")
    assert driven.status_code == 200




@pytest.mark.asyncio
async def test_rate_limiter_counters_carry_window_ttl(monkeypatch):
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
    import api.middleware.rate_limiter as rl

    clock = {"now": 5000.0}
    monkeypatch.setattr(rl.time, "time", lambda: clock["now"])

    limiter = rl.RateLimiter(requests_per_minute=2)
    assert await limiter.is_allowed("198.51.100.9") is True
    assert await limiter.is_allowed("198.51.100.9") is True
    assert await limiter.is_allowed("198.51.100.9") is False

    clock["now"] = 5000.0 + (limiter.window_size / 2) - 1
    assert await limiter.is_allowed("198.51.100.9") is False

    clock["now"] = 5000.0 + limiter.window_size + 1
    assert await limiter.is_allowed("198.51.100.9") is True


@pytest.mark.security
@pytest.mark.skipif(
    not _SEC0002_AUDIT.exists(),
    reason="SEC-0002 audit is a private handover doc, stripped from the CE export; corroborated on private CI only.",
)
def test_sec_0002_audit_artifact_exists():
    assert _SEC0002_AUDIT.is_file(), (
        f"Missing SEC-0002 audit artifact at {_SEC0002_AUDIT}. The rate-limit "
        "verification test is the behavioral complement to that document; "
        "removing the document without updating this test breaks the "
        "passive-server trust model."
    )
