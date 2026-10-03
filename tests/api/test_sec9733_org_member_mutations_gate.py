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

from api.endpoints.organizations import members as members_endpoints
from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import get_current_active_user


pytestmark = pytest.mark.asyncio

_ORG_ID = "org-aaaa"
_OWNER_ID = "11111111-1111-1111-1111-111111111111"
_GATE_MESSAGE = "Adding additional users isn't available on this plan."

_MUTATIONS = [
    ("POST", f"/api/organizations/{_ORG_ID}/members", {"user_id": "victim-user", "role": "admin"}),
    ("PUT", f"/api/organizations/{_ORG_ID}/members/victim-user", {"role": "viewer"}),
    ("DELETE", f"/api/organizations/{_ORG_ID}/members/victim-user", None),
    ("POST", f"/api/organizations/{_ORG_ID}/transfer", {"new_owner_id": "victim-user"}),
]


def _membership() -> SimpleNamespace:
    return SimpleNamespace(
        id="m-1",
        user_id="victim-user",
        role="admin",
        joined_at=datetime(2026, 1, 1, tzinfo=UTC),
        invited_by=_OWNER_ID,
    )


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(members_endpoints.router, prefix="/api/organizations")
    app.include_router(members_endpoints.transfer_router, prefix="/api/organizations")
    register_exception_handlers(app)

    owner = SimpleNamespace(id=_OWNER_ID, username="owner", role="admin", tenant_key="tk_owner")
    service = MagicMock()
    service.can_manage_members = AsyncMock(return_value=True)
    service.can_delete_org = AsyncMock(return_value=True)
    service.can_view_org = AsyncMock(return_value=True)
    service.invite_member = AsyncMock(return_value=_membership())
    service.change_member_role = AsyncMock(return_value=_membership())
    service.remove_member = AsyncMock(return_value=None)
    service.transfer_ownership = AsyncMock(return_value=None)
    service.list_members = AsyncMock(return_value=[_membership()])

    app.dependency_overrides[get_current_active_user] = lambda: owner
    app.dependency_overrides[members_endpoints.get_org_service] = lambda: service
    app.state._service = service
    return app


async def _call(app: FastAPI, method: str, path: str, body: dict | None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, json=body)


@pytest.mark.parametrize("mode", ["ce", "saas"])
async def test_org_owner_invite_is_403_in_all_shipping_editions(mode: str) -> None:
    app = _build_app()
    with patch("api.app_state.GILJO_MODE", mode):
        resp = await _call(app, "POST", f"/api/organizations/{_ORG_ID}/members", _MUTATIONS[0][2])
    assert resp.status_code == 403, resp.text
    assert _GATE_MESSAGE in (resp.json().get("detail") or resp.json().get("message") or "")
    app.state._service.invite_member.assert_not_awaited()


@pytest.mark.parametrize(("method", "path", "body"), _MUTATIONS)
async def test_every_member_mutation_is_403_and_never_reaches_the_service(method: str, path: str, body) -> None:
    app = _build_app()
    resp = await _call(app, method, path, body)
    assert resp.status_code == 403, resp.text
    assert _GATE_MESSAGE in (resp.json().get("detail") or resp.json().get("message") or "")
    svc = app.state._service
    for name in ("invite_member", "change_member_role", "remove_member", "transfer_ownership"):
        getattr(svc, name).assert_not_awaited()


async def test_member_listing_stays_open() -> None:
    app = _build_app()
    resp = await _call(app, "GET", f"/api/organizations/{_ORG_ID}/members", None)
    assert resp.status_code == 200, resp.text


async def test_invite_proceeds_when_member_management_enabled() -> None:
    app = _build_app()
    with patch("api.app_state.member_management_enabled", return_value=True):
        resp = await _call(app, "POST", f"/api/organizations/{_ORG_ID}/members", _MUTATIONS[0][2])
    assert resp.status_code == 201, resp.text
    app.state._service.invite_member.assert_awaited_once()
