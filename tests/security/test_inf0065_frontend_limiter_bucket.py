# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient

from api.middleware.rate_limiter import RateLimitMiddleware, is_frontend_request
from giljo_mcp.services.cache_backends import reset_registry_for_tests


pytestmark = pytest.mark.usefixtures("real_rate_limiter")

LIMIT = 3
FRONTEND_FILES = ["/home", "/splash.css", "/icons/Giljo_YW_Face.svg", "/giljo_logo.png"]


class _AnonymousAuth:
    async def authenticate_request(self, request):
        return {"authenticated": False}


@pytest.fixture
def wired_app(monkeypatch) -> FastAPI:
    import api.wiring.middleware as wiring
    from api.app_state import state

    monkeypatch.setattr(state, "auth", _AnonymousAuth(), raising=False)
    monkeypatch.setattr("api.app.GILJO_MODE", "", raising=False)
    monkeypatch.setenv("API_RATE_LIMIT", str(LIMIT))
    monkeypatch.delenv("DISABLE_RATE_LIMIT", raising=False)
    monkeypatch.delenv("GILJO_TRUSTED_PROXIES", raising=False)
    reset_registry_for_tests()

    app = FastAPI()

    @app.get("/api/probe")
    async def probe():
        return {"ok": True}

    @app.get("/{path:path}")
    async def frontend_file(path: str):
        return PlainTextResponse("file")

    wiring.configure_middleware(app)
    yield app
    reset_registry_for_tests()


def _client(app: FastAPI, ip: str = "198.51.100.65") -> HTTPXAsyncClient:
    return HTTPXAsyncClient(transport=ASGITransport(app=app, client=(ip, 4242)), base_url="http://test")


@pytest.mark.asyncio
async def test_a_page_load_does_not_use_up_the_api_budget(wired_app):
    async with _client(wired_app) as client:
        for path in FRONTEND_FILES:
            await client.get(path)
        api_refused = [(await client.get("/api/probe")).status_code == 429 for _ in range(LIMIT + 1)]

    assert api_refused == [False] * LIMIT + [True]


@pytest.mark.asyncio
async def test_frontend_files_are_still_metered_per_ip(wired_app):
    async with _client(wired_app) as client:
        refused = [(await client.get("/splash.css")).status_code == 429 for _ in range(LIMIT + 1)]
        api_after = (await client.get("/api/probe")).status_code

    assert refused == [False] * LIMIT + [True]
    assert api_after != 429


@pytest.mark.asyncio
async def test_a_write_to_a_page_path_counts_against_the_api_budget(monkeypatch):
    monkeypatch.delenv("GILJO_TRUSTED_PROXIES", raising=False)
    reset_registry_for_tests()
    statuses = []

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    limiter = RateLimitMiddleware(downstream, requests_per_minute=LIMIT)
    for method, path in [("POST", "/home")] * LIMIT + [("GET", "/api/probe")]:
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("198.51.100.66", 4242),
        }
        await limiter(scope, receive, send)
    reset_registry_for_tests()

    assert statuses == [200] * LIMIT + [429]


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/home", True),
        ("HEAD", "/projects/0b7c", True),
        ("GET", "/splash.css", True),
        ("GET", "/icons/Giljo_YW_Face.svg", True),
        ("POST", "/home", False),
        ("GET", "/api/v1/projects/", False),
        ("GET", "/api", False),
        ("GET", "/ws/client_1", False),
        ("GET", "/mcp", False),
        ("GET", "/health", False),
        ("GET", "/docs", False),
        ("GET", "/openapi.json", False),
        ("GET", "/.well-known/oauth-authorization-server", False),
        ("GET", "/connect.md", False),
    ],
)
def test_bucket_choice(method, path, expected):
    assert is_frontend_request(method, path) is expected


NO_DIST_ROOT = {("GET", "/")}


def _non_mount_route_paths(routes, prefix=""):
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            include_prefix = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            yield from _non_mount_route_paths(original.routes, prefix + include_prefix)
        elif getattr(route, "methods", None):
            yield sorted(route.methods), prefix + route.path


def test_every_backend_route_of_the_real_app_uses_the_api_budget(monkeypatch):
    monkeypatch.setattr("api.app.GILJO_MODE", "", raising=False)
    from api.app import create_app

    routes = list(_non_mount_route_paths(create_app().routes))

    assert len(routes) > 100
    leaking = [
        (methods, path)
        for methods, path in routes
        for m in methods
        if is_frontend_request(m, path) and (m, path) not in NO_DIST_ROOT
    ]
    assert leaking == []
