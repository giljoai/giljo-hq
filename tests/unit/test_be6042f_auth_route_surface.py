# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints import auth as auth_endpoints
from api.endpoints.dependencies import get_auth_service
from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import (
    get_db_session,
    require_admin,
)
from tests.helpers.route_surface import route_signatures


pytestmark = pytest.mark.asyncio


EXPECTED_AUTH_ROUTE_SIGNATURES = frozenset(
    {
        ("/login", frozenset({"POST"})),
        ("/logout", frozenset({"POST"})),
        ("/refresh", frozenset({"POST"})),
        ("/me", frozenset({"GET"})),
        ("/me/setup-state", frozenset({"PATCH"})),
        ("/api-keys/active", frozenset({"GET"})),
        ("/api-keys", frozenset({"GET"})),
        ("/api-keys", frozenset({"POST"})),
        ("/api-keys/{key_id}", frozenset({"DELETE"})),
        ("/register", frozenset({"POST"})),
        ("/create-first-admin", frozenset({"POST"})),
    }
)


def _route_signatures(router) -> set[tuple[str, frozenset]]:
    return route_signatures(router.routes)




def test_full_auth_route_signature_set_equality():
    assert _route_signatures(auth_endpoints.router) == EXPECTED_AUTH_ROUTE_SIGNATURES




def test_load_bearing_symbols_importable():
    from api.endpoints.auth import (  # noqa: F401
        LoginRequest,
        SetupStateUpdate,
        _build_cookie_params,
        router,
    )

    assert router is auth_endpoints.router
    assert hasattr(auth_endpoints, "create_first_admin_user")




def _auth_result() -> SimpleNamespace:
    return SimpleNamespace(
        token="test.jwt.token",
        user_id="33333333-3333-3333-3333-333333333333",
        username="alice",
        role="admin",
        tenant_key="tk_test",
    )


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_endpoints.router, prefix="/api/auth")
    register_exception_handlers(app)

    auth_service = MagicMock()
    auth_service.authenticate_user = AsyncMock(return_value=_auth_result())
    auth_service.update_last_login = AsyncMock(return_value=None)
    auth_service.register_user = AsyncMock(return_value=_auth_result())

    async def _override_db():
        session = MagicMock()
        _not_locked = MagicMock()
        _not_locked.first.return_value = None
        session.execute = AsyncMock(return_value=_not_locked)
        session.commit = AsyncMock(return_value=None)
        yield session

    async def _override_admin() -> SimpleNamespace:
        return SimpleNamespace(
            id="44444444-4444-4444-4444-444444444444",
            username="admin",
            role="admin",
            tenant_key="tk_test",
        )

    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[require_admin] = _override_admin

    app.state._auth_service = auth_service
    return app


async def test_login_sets_httponly_access_token_cookie():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "whatever"},
        )

    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie
    lowered = set_cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert "max-age=86400" in lowered
    assert "secure" not in lowered


async def test_unauthenticated_me_returns_401():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/auth/me")

    assert resp.status_code == 401, resp.text
    assert "detail" in resp.json()


async def test_register_forbidden_under_member_management_gate():
    app = _build_app()
    transport = ASGITransport(app=app)
    with patch("api.app_state.member_management_enabled", return_value=False):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/auth/register",
                json={"username": "newseat", "password": "ValidPass123", "role": "developer"},
            )

    assert resp.status_code == 403, resp.text
