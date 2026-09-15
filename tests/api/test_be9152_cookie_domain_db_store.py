# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.tenant import TenantManager


_REFRESH_URL = "/api/auth/refresh"
_WHITELISTED_HOST = "myapp.example.com"


async def _seed_user(db_manager) -> dict:
    suffix = uuid.uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"BE9152 Org {suffix}",
            slug=f"be9152-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"be9152_user_{suffix}",
            email=f"be9152_{suffix}@example.com",
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
        username=f"be9152_user_{suffix}",
        role="developer",
        tenant_key=tenant_key,
    )
    return {"tenant_key": tenant_key, "user_id": user_id, "token": token}


async def _write_whitelist(db_manager, tenant_key: str, domains: list[str]) -> None:
    async with db_manager.get_session_async() as session:
        service = SettingsService(session, tenant_key)
        await service.update_settings("security", {"cookie_domain_whitelist": domains})


def _domain_in_set_cookie(set_cookie: str) -> str | None:
    for part in set_cookie.split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() == "domain":
            return value.lower()
    return None


@pytest.mark.asyncio
async def test_db_whitelisted_domain_is_honored_by_enforcement(api_client, db_manager) -> None:
    seeded = await _seed_user(db_manager)
    await _write_whitelist(db_manager, seeded["tenant_key"], [_WHITELISTED_HOST])

    api_client.cookies.set("access_token", seeded["token"])
    resp = await api_client.post(_REFRESH_URL, headers={"host": _WHITELISTED_HOST})

    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie, set_cookie
    assert _domain_in_set_cookie(set_cookie) == _WHITELISTED_HOST, (
        f"DB-store whitelist must drive the cookie Domain; got: {set_cookie!r}"
    )


@pytest.mark.asyncio
async def test_untouched_panel_leaves_default_behavior_unchanged(api_client, db_manager) -> None:
    seeded = await _seed_user(db_manager)

    api_client.cookies.set("access_token", seeded["token"])
    resp = await api_client.post(_REFRESH_URL, headers={"host": _WHITELISTED_HOST})

    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie, set_cookie
    assert _domain_in_set_cookie(set_cookie) is None, (
        f"an untouched panel must not scope the cookie to any domain; got: {set_cookie!r}"
    )
