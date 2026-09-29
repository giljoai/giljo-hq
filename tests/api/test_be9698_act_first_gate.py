# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_PASSWORD = "old_password_12345"
_CSRF_TOKEN = "be9698-test-csrf-token"


async def _seed_user(db_manager, *, must_change_password: bool) -> tuple[str, str, str, str]:
    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]
    username = f"be9698_user_{suffix}"
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(
            name=f"BE-9698 Org {suffix}",
            slug=f"be9698-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        user = User(
            username=username,
            email=f"be9698_{suffix}@example.com",
            password_hash=bcrypt.hashpw(_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
            must_change_password=must_change_password,
        )
        session.add(user)
        await session.commit()
        user_id = user.id

    token = JWTManager.create_access_token(
        user_id=user_id,
        username=username,
        role="developer",
        tenant_key=tenant_key,
    )
    return token, user_id, tenant_key, username


def _auth_headers(token: str) -> dict:
    return {
        "Cookie": f"access_token={token}; csrf_token={_CSRF_TOKEN}",
        "X-CSRF-Token": _CSRF_TOKEN,
    }


class TestPasswordChangeGateBlocksOrdinaryRoutes:
    async def test_gated_user_gets_403_password_change_required_on_normal_route(self, api_client, db_manager):
        token, _user_id, _tenant_key, _username = await _seed_user(db_manager, must_change_password=True)

        response = await api_client.get("/api/v1/users/me/field-priority", headers=_auth_headers(token))

        assert response.status_code == 403, response.text
        body = response.json()
        assert body["error_code"] == "PASSWORD_CHANGE_REQUIRED", body

    async def test_ungated_user_reaches_normal_route(self, api_client, db_manager):
        token, _user_id, _tenant_key, _username = await _seed_user(db_manager, must_change_password=False)

        response = await api_client.get("/api/v1/users/me/field-priority", headers=_auth_headers(token))

        assert response.status_code == 200, response.text


class TestPasswordChangeGateAllowsTheChangePasswordRoute:
    async def test_gated_user_can_still_change_their_own_password(self, api_client, db_manager):
        token, user_id, _tenant_key, _username = await _seed_user(db_manager, must_change_password=True)

        response = await api_client.put(
            f"/api/v1/users/{user_id}/password",
            headers=_auth_headers(token),
            json={"old_password": _PASSWORD, "new_password": "brand_new_password_999"},
        )

        assert response.status_code == 200, response.text

    async def test_after_changing_password_the_same_normal_route_succeeds(self, api_client, db_manager):
        token, user_id, tenant_key, username = await _seed_user(db_manager, must_change_password=True)

        change_response = await api_client.put(
            f"/api/v1/users/{user_id}/password",
            headers=_auth_headers(token),
            json={"old_password": _PASSWORD, "new_password": "brand_new_password_999"},
        )
        assert change_response.status_code == 200, change_response.text

        fresh_token = JWTManager.create_access_token(
            user_id=user_id,
            username=username,
            role="developer",
            tenant_key=tenant_key,
            revocation_epoch=1,
        )
        response = await api_client.get("/api/v1/users/me/field-priority", headers=_auth_headers(fresh_token))

        assert response.status_code == 200, response.text


class TestActFirstGateAllowlist:
    async def test_allowlist_exact_content(self):
        from giljo_mcp.auth.dependencies import ACT_FIRST_GATE_ALLOWLIST

        assert (
            frozenset(
                {
                    "complete_first_login",
                    "change_password",
                    "reaccept_terms",
                    "get_account_status",
                    "health_check",
                }
            )
            == ACT_FIRST_GATE_ALLOWLIST
        )
