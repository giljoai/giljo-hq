# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient

from api.middleware.auth import AuthMiddleware


SERVED_MARKER = "robots-txt-served"
ROBOTS_SOURCE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "robots.txt"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.auth = MagicMock()
    app.state.auth.authenticate_request = AsyncMock(
        return_value={"authenticated": False, "error": "No credentials provided"}
    )

    @app.get("/robots.txt")
    async def robots():
        return {"served": SERVED_MARKER}

    @app.get("/api/projects")
    async def protected():  # pragma: no cover - must never be reached
        return {"served": SERVED_MARKER}

    app.add_middleware(AuthMiddleware)
    return app


async def _get(path: str):
    transport = ASGITransport(app=_build_app())
    async with HTTPXAsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_robots_txt_is_reachable_without_a_session():
    response = await _get("/robots.txt")
    assert response.status_code == 200, f"a crawler still cannot read robots.txt: {response.status_code}"
    assert response.json()["served"] == SERVED_MARKER


@pytest.mark.asyncio
async def test_protected_paths_are_untouched_by_the_carve_out():
    response = await _get("/api/projects")
    assert response.status_code == 401
    assert response.json()["error"] == "Authentication required"


@pytest.mark.parametrize(
    "path",
    [
        "/robots.txt.bak",
        "/robotstxt",
        "/secrets.txt",
        "/config.txt",
        "/robots.txt/../.env",
        "/admin/robots.txt",
    ],
)
def test_the_carve_out_is_one_literal_path_and_not_an_extension(path):
    middleware = AuthMiddleware(MagicMock())
    assert middleware._is_public_endpoint(path) is False


def test_the_file_the_route_serves_actually_exists_and_says_something():
    assert ROBOTS_SOURCE.is_file(), f"{ROBOTS_SOURCE} is missing -- the public path serves nothing"
    body = ROBOTS_SOURCE.read_text(encoding="utf-8")
    assert "User-agent:" in body, "a robots.txt without a User-agent line is not a robots.txt"
    for machine_surface in ("/api/", "/mcp", "/oauth/", "/.well-known/"):
        assert f"Disallow: {machine_surface}" in body, f"{machine_surface} is no longer disallowed"
