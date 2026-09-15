# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient

from api.middleware.auth import AuthMiddleware


SHELL_MARKER = "spa-shell-reached"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.auth = MagicMock()
    app.state.auth.authenticate_request = AsyncMock(
        return_value={"authenticated": False, "error": "No credentials provided"}
    )

    @app.get("/privacy")
    async def privacy():
        return {"shell": SHELL_MARKER}

    @app.get("/terms")
    async def terms():
        return {"shell": SHELL_MARKER}

    @app.get("/api/projects")
    async def protected():  # pragma: no cover - must never be reached
        return {"shell": SHELL_MARKER}

    app.add_middleware(AuthMiddleware)
    return app


async def _get(path: str, **kwargs):
    transport = ASGITransport(app=_build_app())
    async with HTTPXAsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/privacy", "/terms"])
async def test_policy_routes_reachable_without_a_session(path):
    response = await _get(path)
    assert response.status_code == 200
    assert response.json()["shell"] == SHELL_MARKER


@pytest.mark.asyncio
async def test_protected_path_still_rejected_without_a_session():
    response = await _get("/api/projects")
    assert response.status_code == 401
    assert response.json()["error"] == "Authentication required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/privacy-something",
        "/privacyx",
        "/terms-of-someone-elses",
        "/privacy/admin",
        "/terms/../admin",
    ],
)
async def test_allowlist_matches_exactly_and_does_not_extend_by_prefix(path):
    middleware = AuthMiddleware(MagicMock())
    assert middleware._is_public_endpoint(path) is False


def test_policy_routes_are_read_only_surface():
    from api.app import app as real_app

    mounted = {getattr(route, "path", None) for route in real_app.routes}
    assert "/privacy" not in mounted
    assert "/terms" not in mounted
