# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pytest
import pytest_asyncio

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache
from giljo_mcp.tenant import TenantManager


_REFRESH_URL = "/api/auth/refresh"


async def _seed_user(db_manager) -> dict:
    suffix = uuid.uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"BE6025 Org {suffix}",
            slug=f"be6025-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"be6025_user_{suffix}",
            email=f"be6025_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.commit()
        user_id = user.id

    token = JWTManager.create_access_token(
        user_id=user_id,
        username=f"be6025_user_{suffix}",
        role="developer",
        tenant_key=tenant_key,
    )
    return {"tenant_key": tenant_key, "user_id": user_id, "username": f"be6025_user_{suffix}", "token": token}


def _expired_token(user_id: str, username: str, tenant_key: str, hours_ago: int) -> str:
    secret_key = JWTManager._get_secret_key()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": "developer",
        "tenant_key": tenant_key,
        "exp": now - timedelta(hours=hours_ago),
        "iat": now - timedelta(hours=hours_ago + JWTManager.ACCESS_TOKEN_EXPIRE_HOURS),
        "type": "access",
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret_key, algorithm=JWTManager.ALGORITHM)


@pytest_asyncio.fixture(scope="function")
async def seeded_user(db_manager) -> dict:
    return await _seed_user(db_manager)


@pytest.mark.asyncio
async def test_refresh_valid_token_returns_200_under_enforce(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    api_client.cookies.set("access_token", seeded_user["token"])
    resp = await api_client.post(_REFRESH_URL)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "Token refreshed"
    assert body["username"] == seeded_user["username"]

    set_cookie = resp.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie


@pytest.mark.asyncio
async def test_refresh_missing_token_returns_401_under_enforce(api_client, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    api_client.cookies.clear()
    resp = await api_client.post(_REFRESH_URL)

    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_refresh_expired_beyond_grace_returns_401_under_enforce(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    stale = _expired_token(
        seeded_user["user_id"],
        seeded_user["username"],
        seeded_user["tenant_key"],
        hours_ago=JWTManager.REFRESH_GRACE_PERIOD_HOURS + 2,
    )
    api_client.cookies.set("access_token", stale)
    resp = await api_client.post(_REFRESH_URL)

    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_refresh_rejects_revoked_token(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    clear_revocation_cache()
    token = seeded_user["token"]


    api_client.cookies.clear()
    api_client.cookies.set("access_token", token)
    ok = await api_client.post(_REFRESH_URL)
    assert ok.status_code == 200, ok.text

    api_client.cookies.clear()
    api_client.cookies.set("access_token", token)
    out = await api_client.post("/api/auth/logout")
    assert out.status_code == 200, out.text

    api_client.cookies.clear()
    api_client.cookies.set("access_token", token)
    blocked = await api_client.post(_REFRESH_URL)
    assert blocked.status_code == 401, blocked.text
    assert "revoked" in blocked.text.lower(), blocked.text
    assert "set-cookie" not in {k.lower() for k in blocked.headers}, "revoked refresh must not mint a new cookie"


@pytest.mark.asyncio
async def test_me_org_loading_returns_200_under_enforce(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    api_client.cookies.set("access_token", seeded_user["token"])
    resp = await api_client.get("/api/auth/me")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == seeded_user["username"]
    assert body["org_name"] is not None
