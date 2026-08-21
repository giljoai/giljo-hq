# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression: /privacy and /terms must be reachable without a session.

Both routes are declared in the Vue router as public
(``frontend/src/router/index.js``, ``requiresAuth: false``), but the server-side
SPA allowlist in ``AuthMiddleware._is_public_endpoint`` did not list them, so
``AuthMiddleware`` rejected the request *before* the SPA shell could be served.

Scope of the observed defect: the middleware's SPA fallback already returns
index.html for a GET carrying ``Accept: text/html``, so ordinary browsers were
unaffected. Any client that does not send that header -- curl, link checkers,
crawlers, compliance scanners -- got a 401 on two documents that are public by
definition. That is the case these tests pin.

The tests drive requests through ``AuthMiddleware`` itself, which is the layer
the bug lived at: they assert the middleware now lets the request reach the
downstream app instead of short-circuiting it. Rendering the shell is
``api/app.py``'s SPA fallback and is not restated here.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient

from api.middleware.auth import AuthMiddleware


SHELL_MARKER = "spa-shell-reached"


def _build_app() -> FastAPI:
    """An app behind ``AuthMiddleware`` whose auth manager always rejects, so
    every response proves whether the middleware allowlisted the path."""
    app = FastAPI()
    app.state.auth = MagicMock()
    app.state.auth.authenticate_request = AsyncMock(
        return_value={"authenticated": False, "error": "No credentials provided"}
    )

    # Stand-ins for whatever the app serves once auth has been passed. Reaching
    # one of these means the middleware did not reject the request.
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
    """GET through the middleware with no credentials and no Accept header, so
    the SPA-fallback-on-401 path cannot mask the allowlist behaviour."""
    transport = ASGITransport(app=_build_app())
    async with HTTPXAsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/privacy", "/terms"])
async def test_policy_routes_reachable_without_a_session(path):
    """The defect: an unauthenticated request for a public policy document was
    rejected by auth before anything could serve it."""
    response = await _get(path)
    assert response.status_code == 200
    assert response.json()["shell"] == SHELL_MARKER


@pytest.mark.asyncio
async def test_protected_path_still_rejected_without_a_session():
    """The allowlist widened by exactly two documents -- guarded surface is
    untouched."""
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
    """The SPA allowlist is an exact-match set, not a prefix match: neighbouring
    or traversal-shaped paths gain nothing from the two new entries."""
    middleware = AuthMiddleware(MagicMock())
    assert middleware._is_public_endpoint(path) is False


def test_policy_routes_are_read_only_surface():
    """The bypass is path-scoped, not method-scoped (the existing idiom for
    every SPA route). That is only safe because no backend route is mounted at
    either path -- assert that, so adding one later fails here first."""
    from api.app import app as real_app

    mounted = {getattr(route, "path", None) for route in real_app.routes}
    assert "/privacy" not in mounted
    assert "/terms" not in mounted
