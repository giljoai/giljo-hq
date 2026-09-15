# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
import uuid

import bcrypt
import pytest
from httpx import AsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed_tenant(db_manager) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
            first_name="Test",
            last_name=f"User{suffix}",
        )
        session.add(user)
        await session.flush()
        await session.commit()
        token = JWTManager.create_access_token(
            user_id=user.id, username=user.username, role="developer", tenant_key=tenant_key
        )
        return {
            "tenant_key": tenant_key,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
        }


async def _seed_connection(db_manager, tenant_key: str, client_name: str) -> None:
    from api.endpoints.mcp_session import MCPSessionManager

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await MCPSessionManager(session).create_session(
                tenant_key=tenant_key,
                user_id=None,
                client_info={"name": client_name, "version": "1.0.0"},
                auth_method="oauth_jwt",
            )
            await session.commit()


async def _harnesses(api_client: AsyncClient, headers: dict) -> dict:
    resp = await api_client.get("/api/connect/credential-status", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json().get("connected_harnesses") or {}


async def test_removing_a_tool_clears_it_from_credential_status(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    await _seed_connection(db_manager, seed["tenant_key"], "claude-code")
    assert "claude-code" in await _harnesses(api_client, seed["headers"])

    resp = await api_client.delete("/api/connect/connections/claude-code", headers=seed["headers"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] == 1
    assert "claude-code" not in await _harnesses(api_client, seed["headers"])


async def test_removing_one_tool_leaves_the_rest(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    await _seed_connection(db_manager, seed["tenant_key"], "claude-code")
    await _seed_connection(db_manager, seed["tenant_key"], "opencode")

    await api_client.delete("/api/connect/connections/claude-code", headers=seed["headers"])

    remaining = await _harnesses(api_client, seed["headers"])
    assert "opencode" in remaining
    assert "claude-code" not in remaining


async def test_one_tenant_cannot_remove_anothers_connection(api_client: AsyncClient, db_manager) -> None:
    a = await _seed_tenant(db_manager)
    b = await _seed_tenant(db_manager)
    await _seed_connection(db_manager, a["tenant_key"], "claude-code")

    resp = await api_client.delete("/api/connect/connections/claude-code", headers=b["headers"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] == 0
    assert "claude-code" in await _harnesses(api_client, a["headers"])


async def test_removal_requires_authentication(api_client: AsyncClient) -> None:
    resp = await api_client.delete("/api/connect/connections/claude-code")

    assert resp.status_code in (401, 403), resp.text
