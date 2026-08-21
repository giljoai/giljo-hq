# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9420 item 4: /robots.txt must be reachable without a session.

The defect, measured: ``AuthMiddleware._is_public_endpoint("/robots.txt")``
returned ``False``, so a crawler's very first request -- the one whose entire
purpose is to be read before anything else -- got a 401. The cause was narrow:
the static-asset carve-out lists ``.svg .png .jpg .ico .woff .woff2 .ttf .eot
.css`` and not ``.txt``. ``/favicon.ico``, the other root file crawlers fetch
unauthenticated, was already carved out, which is what makes robots.txt's
absence an oversight rather than a posture.

The fix is a LITERAL path entry, deliberately not a ``.txt`` extension: admitting
the extension would make every future text file under the SPA root world-readable.

Modelled on ``test_policy_routes_public_allowlist.py`` -- same defect class (a
public-by-definition document rejected by auth), same layer, same harness.
"""

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
    """An app behind ``AuthMiddleware`` whose auth manager always rejects, so any
    2xx proves the middleware allowlisted the path rather than that a session worked."""
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
    """GET with no credentials and no ``Accept`` header, so the SPA-fallback-on-401
    path cannot mask the allowlist behaviour."""
    transport = ASGITransport(app=_build_app())
    async with HTTPXAsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_robots_txt_is_reachable_without_a_session():
    """The defect, pinned at the layer it lived at.

    Asserted over HTTP rather than by calling ``_is_public_endpoint`` directly:
    the predicate returning True is necessary but not sufficient -- the request
    also has to survive the middleware and reach something.
    """
    response = await _get("/robots.txt")
    assert response.status_code == 200, f"a crawler still cannot read robots.txt: {response.status_code}"
    assert response.json()["served"] == SERVED_MARKER


@pytest.mark.asyncio
async def test_protected_paths_are_untouched_by_the_carve_out():
    """The allowlist widened by exactly one document."""
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
    """The guard that keeps this fix small.

    ``/secrets.txt`` and ``/config.txt`` are the reason: the tempting fix was to
    add ``.txt`` to the static-extension tuple, which would have made every text
    file under the SPA root publicly readable. These stay non-public.
    """
    middleware = AuthMiddleware(MagicMock())
    assert middleware._is_public_endpoint(path) is False


def test_the_file_the_route_serves_actually_exists_and_says_something():
    """Without this, the carve-out could ship green while serving a 404.

    Vite copies ``frontend/public/`` into the ``dist`` the app mounts, so this
    file IS what ``/robots.txt`` resolves to in a built deployment.
    """
    assert ROBOTS_SOURCE.is_file(), f"{ROBOTS_SOURCE} is missing -- the public path serves nothing"
    body = ROBOTS_SOURCE.read_text(encoding="utf-8")
    assert "User-agent:" in body, "a robots.txt without a User-agent line is not a robots.txt"
    # The machine surfaces the ruled posture keeps crawlers off.
    for machine_surface in ("/api/", "/mcp", "/oauth/", "/.well-known/"):
        assert f"Disallow: {machine_surface}" in body, f"{machine_surface} is no longer disallowed"
