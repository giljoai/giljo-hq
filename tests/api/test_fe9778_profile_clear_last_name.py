# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager


_CSRF = secrets.token_urlsafe(32)


async def _seed_user(db_manager, *, first_name: str = "Ada", last_name: str | None = "Lovelace"):
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"fe9778_user_{unique}"

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"FE9778 Org {unique}", slug=f"fe9778-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"fe9778_{unique}@example.com",
                first_name=first_name,
                last_name=last_name,
                full_name=" ".join(p for p in (first_name, last_name) if p),
                password_hash=bcrypt.hashpw(b"Password1!", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()

    return user_id, username, tk


def _headers(user_id: str, username: str, tenant_key: str) -> dict:
    claims = {"user_id": user_id, "username": username, "role": "developer", "revocation_epoch": 0}
    token = JWTManager.create_access_token(tenant_key=tenant_key, **claims)
    return {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


async def _put_then_get(api_client, user_id: str, headers: dict, payload: dict):
    put = await api_client.put(f"/api/v1/users/{user_id}", json=payload, headers=headers)
    get = await api_client.get(f"/api/v1/users/{user_id}", headers=headers)
    assert get.status_code == 200, get.text
    return put, get.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("cleared_value", [None, "", "   "], ids=["null", "empty", "blank"])
async def test_clearing_last_name_persists(api_client, db_manager, monkeypatch, cleared_value):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)
    headers = _headers(user_id, username, tk)

    put, body = await _put_then_get(api_client, user_id, headers, {"first_name": "Ada", "last_name": cleared_value})

    assert put.status_code == 200, put.text
    assert put.json()["last_name"] is None
    assert body["last_name"] is None
    assert body["first_name"] == "Ada"
    assert body["full_name"] == "Ada"


@pytest.mark.asyncio
async def test_omitted_last_name_is_left_unchanged(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)
    headers = _headers(user_id, username, tk)

    put, body = await _put_then_get(api_client, user_id, headers, {"first_name": "Augusta"})

    assert put.status_code == 200, put.text
    assert body["first_name"] == "Augusta"
    assert body["last_name"] == "Lovelace"
    assert body["full_name"] == "Augusta Lovelace"


@pytest.mark.asyncio
async def test_setting_last_name_after_clear_round_trips(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager, last_name=None)
    headers = _headers(user_id, username, tk)

    put, body = await _put_then_get(api_client, user_id, headers, {"last_name": "  Byron "})

    assert put.status_code == 200, put.text
    assert body["last_name"] == "Byron"
    assert body["first_name"] == "Ada"


@pytest.mark.asyncio
async def test_empty_first_name_is_still_rejected(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)
    headers = _headers(user_id, username, tk)

    put, body = await _put_then_get(api_client, user_id, headers, {"first_name": "", "last_name": None})

    assert put.status_code == 422, put.text
    assert body["first_name"] == "Ada"
    assert body["last_name"] == "Lovelace"


@pytest.mark.asyncio
async def test_null_first_name_does_not_clear_it(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)
    headers = _headers(user_id, username, tk)

    put, body = await _put_then_get(api_client, user_id, headers, {"first_name": None})

    assert put.status_code == 200, put.text
    assert body["first_name"] == "Ada"
    assert body["last_name"] == "Lovelace"
