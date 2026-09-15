# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
import pytest_asyncio
from sqlalchemy import update

from giljo_mcp.models import User
from giljo_mcp.models.auth import LoginLockout
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.login_lockout_service import MAX_FAILED_ATTEMPTS
from giljo_mcp.tenant import TenantManager


_LOGIN_URL = "/api/auth/login"
_PASSWORD = "test_password"


async def _seed_user(db_manager) -> dict:
    suffix = uuid.uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    password_hash = bcrypt.hashpw(_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    username = f"ll_user_{suffix}"

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"LL Org {suffix}",
            slug=f"ll-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=username,
            email=f"ll_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.commit()
    return {"username": username, "tenant_key": tenant_key}


@pytest_asyncio.fixture(scope="function")
async def seeded_user(db_manager) -> dict:
    return await _seed_user(db_manager)


@pytest.mark.asyncio
async def test_login_lockout_blocks_then_auto_unlocks(api_client, seeded_user, db_manager, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_RL_LOGIN", "10000")
    username = seeded_user["username"]

    for i in range(MAX_FAILED_ATTEMPTS - 1):
        resp = await api_client.post(_LOGIN_URL, json={"username": username, "password": "wrong-password"})
        assert resp.status_code == 401, f"attempt {i + 1}: {resp.text}"

    tripped = await api_client.post(_LOGIN_URL, json={"username": username, "password": "wrong-password"})
    assert tripped.status_code == 429, tripped.text

    locked = await api_client.post(_LOGIN_URL, json={"username": username, "password": _PASSWORD})
    assert locked.status_code == 429, locked.text
    assert locked.headers.get("Retry-After")

    async with db_manager.get_session_async() as session:
        await session.execute(
            update(LoginLockout)
            .where(LoginLockout.identifier == username.lower())
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()

    ok = await api_client.post(_LOGIN_URL, json={"username": username, "password": _PASSWORD})
    assert ok.status_code == 200, ok.text
    assert ok.json()["username"] == username


@pytest.mark.asyncio
async def test_successful_login_does_not_accumulate_lock(api_client, seeded_user, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_RL_LOGIN", "10000")
    username = seeded_user["username"]

    for _ in range(MAX_FAILED_ATTEMPTS - 2):
        resp = await api_client.post(_LOGIN_URL, json={"username": username, "password": "nope"})
        assert resp.status_code == 401, resp.text

    ok = await api_client.post(_LOGIN_URL, json={"username": username, "password": _PASSWORD})
    assert ok.status_code == 200, ok.text

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        resp = await api_client.post(_LOGIN_URL, json={"username": username, "password": "nope"})
        assert resp.status_code == 401, resp.text
    final = await api_client.post(_LOGIN_URL, json={"username": username, "password": _PASSWORD})
    assert final.status_code == 200, final.text
