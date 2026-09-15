# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints import auth as auth_endpoints
from api.endpoints import users as users_endpoints
from api.endpoints.dependencies import get_auth_service, get_user_service
from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import (
    get_current_active_user,
    get_db_session,
    require_admin,
)


pytestmark = pytest.mark.asyncio

_ADMIN_ID = "11111111-1111-1111-1111-111111111111"


def _admin_user() -> SimpleNamespace:
    return SimpleNamespace(
        id=_ADMIN_ID,
        username="solo_admin",
        role="admin",
        tenant_key="tk_test_solo",
    )


def _fake_created_user() -> SimpleNamespace:
    return SimpleNamespace(
        id="22222222-2222-2222-2222-222222222222",
        username="newseat",
        email="seat@example.com",
        first_name="New",
        last_name="Seat",
        full_name="New Seat",
        role="developer",
        tenant_key="tk_test_solo",
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_login=None,
    )


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(users_endpoints.router, prefix="/api/v1/users")
    app.include_router(auth_endpoints.router, prefix="/api/auth")
    register_exception_handlers(app)

    admin = _admin_user()

    async def _override_admin() -> SimpleNamespace:
        return admin

    user_service = MagicMock()
    user_service.create_user = AsyncMock(return_value=_fake_created_user())
    user_service.auth = MagicMock()
    user_service.auth.change_password = AsyncMock(return_value=None)

    auth_service = MagicMock()
    auth_service.register_user = AsyncMock(return_value=_fake_created_user())

    async def _override_db():
        yield MagicMock()

    app.dependency_overrides[require_admin] = _override_admin
    app.dependency_overrides[get_current_active_user] = _override_admin
    app.dependency_overrides[get_user_service] = lambda: user_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_db_session] = _override_db

    app.state._user_service = user_service
    app.state._auth_service = auth_service
    return app




@pytest.mark.parametrize("mode", ["ce", "saas"])
async def test_create_user_endpoint_is_403_in_all_shipping_editions(mode: str) -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    with patch("api.app_state.GILJO_MODE", mode):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/users/",
                json={"username": "newseat", "password": "ValidPass123", "role": "developer"},
            )
    assert resp.status_code == 403, resp.text
    detail = (resp.json().get("detail") or resp.json().get("message") or "").lower()
    assert "available" in detail
    app.state._user_service.create_user.assert_not_awaited()


@pytest.mark.parametrize("mode", ["ce", "saas"])
async def test_register_endpoint_is_403_in_all_shipping_editions(mode: str) -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    with patch("api.app_state.GILJO_MODE", mode):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/register",
                json={"username": "newseat", "password": "ValidPass123", "role": "developer"},
            )
    assert resp.status_code == 403, resp.text
    detail = (resp.json().get("detail") or resp.json().get("message") or "").lower()
    assert "available" in detail
    app.state._auth_service.register_user.assert_not_awaited()




async def test_create_user_proceeds_when_member_management_enabled() -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    with patch("api.app_state.member_management_enabled", return_value=True):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/users/",
                json={"username": "newseat", "password": "ValidPass123", "role": "developer"},
            )
    assert resp.status_code != 403, resp.text
    app.state._user_service.create_user.assert_awaited_once()


async def test_register_proceeds_when_member_management_enabled() -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    fake_limiter = MagicMock()
    fake_limiter.check_rate_limit = AsyncMock(return_value=None)
    with (
        patch("api.app_state.member_management_enabled", return_value=True),
        patch("api.endpoints.auth.registration.get_rate_limiter", return_value=fake_limiter),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/register",
                json={"username": "newseat", "password": "ValidPass123", "role": "developer"},
            )
    assert resp.status_code != 403, resp.text
    app.state._auth_service.register_user.assert_awaited_once()




async def test_self_password_change_is_not_gated() -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    with patch("api.app_state.GILJO_MODE", "saas"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/users/{_ADMIN_ID}/password",
                json={"old_password": "OldPass123", "new_password": "NewPass456"},
            )
    assert resp.status_code == 200, resp.text
    app.state._user_service.auth.change_password.assert_awaited_once()




async def test_member_management_disabled_for_all_current_editions() -> None:
    from api.app_state import member_management_enabled

    assert member_management_enabled() is False
