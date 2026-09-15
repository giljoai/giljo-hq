# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import uuid

import bcrypt
import pytest
import pytest_asyncio

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services import oauth_revocation_service
from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache
from giljo_mcp.tenant import TenantManager


_REFRESH_URL = "/api/auth/refresh"
_ME_URL = "/api/auth/me"
_LOGOUT_URL = "/api/auth/logout"


async def _seed_user(db_manager) -> dict:
    suffix = uuid.uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"TSK9005 Org {suffix}",
            slug=f"tsk9005-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"tsk9005_user_{suffix}",
            email=f"tsk9005_{suffix}@example.com",
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
        username=f"tsk9005_user_{suffix}",
        role="developer",
        tenant_key=tenant_key,
    )
    return {"tenant_key": tenant_key, "user_id": user_id, "username": f"tsk9005_user_{suffix}", "token": token}


@pytest_asyncio.fixture(scope="function")
async def seeded_user(db_manager) -> dict:
    return await _seed_user(db_manager)


def _pin(api_client, token: str) -> None:
    api_client.cookies.clear()
    api_client.cookies.set("access_token", token)


@pytest.mark.asyncio
async def test_old_jti_rejected_after_rotation(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    monkeypatch.setattr(oauth_revocation_service, "ROTATION_GRACE_SECONDS", 0)
    clear_revocation_cache()
    token = seeded_user["token"]

    _pin(api_client, token)
    ok = await api_client.post(_REFRESH_URL)
    assert ok.status_code == 200, ok.text
    assert "access_token=" in ok.headers.get("set-cookie", "")

    clear_revocation_cache()
    _pin(api_client, token)
    blocked = await api_client.post(_REFRESH_URL)
    assert blocked.status_code == 401, blocked.text
    assert "revoked" in blocked.text.lower(), blocked.text
    assert "set-cookie" not in {k.lower() for k in blocked.headers}, "rotated refresh must not mint a new cookie"

    clear_revocation_cache()
    _pin(api_client, token)
    me = await api_client.get(_ME_URL)
    assert me.status_code == 401, me.text


@pytest.mark.asyncio
async def test_concurrent_refresh_within_grace_not_locked_out(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    monkeypatch.setattr(oauth_revocation_service, "ROTATION_GRACE_SECONDS", 30)
    clear_revocation_cache()
    token = seeded_user["token"]

    _pin(api_client, token)
    first = await api_client.post(_REFRESH_URL)
    assert first.status_code == 200, first.text

    clear_revocation_cache()
    _pin(api_client, token)
    overlap_refresh = await api_client.post(_REFRESH_URL)
    assert overlap_refresh.status_code == 200, overlap_refresh.text

    clear_revocation_cache()
    _pin(api_client, token)
    overlap_me = await api_client.get(_ME_URL)
    assert overlap_me.status_code == 200, overlap_me.text
    assert overlap_me.json()["username"] == seeded_user["username"]


@pytest.mark.asyncio
async def test_truly_concurrent_double_refresh_no_lockout(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    monkeypatch.setattr(oauth_revocation_service, "ROTATION_GRACE_SECONDS", 30)
    clear_revocation_cache()
    token = seeded_user["token"]

    _pin(api_client, token)
    r1, r2 = await asyncio.gather(
        api_client.post(_REFRESH_URL),
        api_client.post(_REFRESH_URL),
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text


@pytest.mark.asyncio
async def test_happy_path_new_jti_authenticates(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    monkeypatch.setattr(oauth_revocation_service, "ROTATION_GRACE_SECONDS", 0)
    clear_revocation_cache()

    _pin(api_client, seeded_user["token"])
    refreshed = await api_client.post(_REFRESH_URL)
    assert refreshed.status_code == 200, refreshed.text

    clear_revocation_cache()
    me = await api_client.get(_ME_URL)
    assert me.status_code == 200, me.text
    assert me.json()["username"] == seeded_user["username"]


@pytest.mark.asyncio
async def test_logout_revocation_stays_immediate_despite_grace(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    monkeypatch.setattr(oauth_revocation_service, "ROTATION_GRACE_SECONDS", 30)
    clear_revocation_cache()
    token = seeded_user["token"]

    _pin(api_client, token)
    out = await api_client.post(_LOGOUT_URL)
    assert out.status_code == 200, out.text

    clear_revocation_cache()
    _pin(api_client, token)
    blocked = await api_client.post(_REFRESH_URL)
    assert blocked.status_code == 401, blocked.text
    assert "revoked" in blocked.text.lower(), blocked.text
