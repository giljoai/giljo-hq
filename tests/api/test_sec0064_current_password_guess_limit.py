# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import select, update

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models.auth import LoginLockout, User


PASSWORD = "Password1!"
WRONG = "NotThePassword9!"
NEW_PASSWORD = "NewPassword2@"
PIN = "4242"
NEW_PIN = "1357"
_CSRF = secrets.token_urlsafe(32)


@pytest.fixture
def community(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setenv("GILJO_MODE", "ce")
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.GILJO_MODE", "ce")


async def _seed(db_manager, *, role: str = "developer", tenant_key: str | None = None) -> dict:
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = tenant_key or TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user = {
        "id": str(uuid4()),
        "username": f"sec0064_{unique}",
        "tenant_key": tenant_key,
        "role": role,
    }
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(name=f"SEC0064 {unique}", slug=f"sec0064-{unique}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user["id"],
                username=user["username"],
                email=f"sec0064_{unique}@example.com",
                password_hash=bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode(),
                recovery_pin_hash=bcrypt.hashpw(PIN.encode(), bcrypt.gensalt(rounds=4)).decode(),
                tenant_key=tenant_key,
                role=role,
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()
    return user


def _cookie(user: dict) -> dict:
    token = JWTManager.create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        tenant_key=user["tenant_key"],
        revocation_epoch=0,
    )
    return {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


async def _password_door(api_client, user: dict, guess: str):
    return await api_client.put(
        f"/api/v1/users/{user['id']}/password",
        json={"old_password": guess, "new_password": NEW_PASSWORD},
        headers=_cookie(user),
    )


async def _pin_door(api_client, user: dict, guess: str):
    return await api_client.put(
        f"/api/v1/users/{user['id']}",
        json={"recovery_pin": NEW_PIN, "current_password": guess},
        headers=_cookie(user),
    )


async def _first_login_door(api_client, user: dict, guess: str):
    return await api_client.post(
        "/api/auth/complete-first-login",
        json={
            "current_password": guess,
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
            "recovery_pin": NEW_PIN,
            "confirm_pin": NEW_PIN,
        },
        headers=_cookie(user),
    )


async def _password_hash(db_manager, user: dict) -> str:
    async with db_manager.get_session_async(tenant_key=user["tenant_key"]) as session:
        row = await session.execute(
            select(User.password_hash).where(User.id == user["id"], User.tenant_key == user["tenant_key"])
        )
        return row.scalar_one()


async def _lock_row(db_manager, user: dict) -> LoginLockout:
    async with db_manager.get_session_async() as session:
        return (
            await session.execute(select(LoginLockout).where(LoginLockout.identifier.contains(user["id"])))
        ).scalar_one()


async def _expire_lock(db_manager, user: dict) -> None:
    async with db_manager.get_session_async() as session:
        await session.execute(
            update(LoginLockout)
            .where(LoginLockout.identifier.contains(user["id"]))
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("door", [_password_door, _pin_door, _first_login_door])
async def test_fifth_wrong_guess_locks_and_the_right_password_then_waits(api_client, db_manager, community, door):
    user = await _seed(db_manager)
    before = await _password_hash(db_manager, user)

    statuses = [(await door(api_client, user, WRONG)).status_code for _ in range(5)]
    right = await door(api_client, user, PASSWORD)

    assert statuses[:4] == [statuses[0]] * 4 and statuses[0] in (400, 401), statuses
    assert statuses[4] == 429, statuses
    assert right.status_code == 429, right.text
    assert "Retry-After" in right.headers
    assert await _password_hash(db_manager, user) == before


@pytest.mark.asyncio
async def test_all_doors_share_one_count(api_client, db_manager, community):
    user = await _seed(db_manager)

    for door in (_password_door, _pin_door, _first_login_door, _password_door):
        assert (await door(api_client, user, WRONG)).status_code in (400, 401)
    locked = await _pin_door(api_client, user, WRONG)

    assert locked.status_code == 429, locked.text


@pytest.mark.asyncio
async def test_each_failure_after_a_lock_expires_locks_for_longer(api_client, db_manager, community):
    user = await _seed(db_manager)
    for _ in range(5):
        await _password_door(api_client, user, WRONG)

    await _expire_lock(db_manager, user)
    sixth = await _password_door(api_client, user, WRONG)

    assert sixth.status_code == 429, sixth.text
    row = await _lock_row(db_manager, user)
    assert row.failed_count == 6
    assert row.locked_until - datetime.now(UTC) >= timedelta(minutes=59)


@pytest.mark.asyncio
async def test_the_right_password_clears_the_count(api_client, db_manager, community):
    user = await _seed(db_manager)
    for _ in range(4):
        await _pin_door(api_client, user, WRONG)

    assert (await _pin_door(api_client, user, PASSWORD)).status_code == 200
    statuses = [(await _pin_door(api_client, user, WRONG)).status_code for _ in range(4)]

    assert statuses == [400] * 4


@pytest.mark.asyncio
async def test_a_burst_at_the_threshold_gets_one_guess(api_client, db_manager, community):
    user = await _seed(db_manager)
    for _ in range(4):
        await _password_door(api_client, user, WRONG)

    burst = await asyncio.gather(*(_password_door(api_client, user, WRONG) for _ in range(4)))

    assert sorted(r.status_code for r in burst) == [429, 429, 429, 429]
    assert (await _lock_row(db_manager, user)).failed_count == 5


@pytest.mark.asyncio
async def test_one_users_lock_does_not_touch_another(api_client, db_manager, community):
    locked = await _seed(db_manager)
    other = await _seed(db_manager, tenant_key=locked["tenant_key"])
    for _ in range(5):
        await _pin_door(api_client, locked, WRONG)

    assert (await _pin_door(api_client, other, PASSWORD)).status_code == 200


@pytest.mark.asyncio
async def test_control_admin_still_resets_a_locked_members_password(api_client, db_manager, community):
    admin = await _seed(db_manager, role="admin")
    member = await _seed(db_manager, tenant_key=admin["tenant_key"])
    for _ in range(5):
        await _pin_door(api_client, member, WRONG)

    resp = await api_client.put(
        f"/api/v1/users/{member['id']}/password", json={"new_password": NEW_PASSWORD}, headers=_cookie(admin)
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_a_pin_password_reset_clears_the_lock(db_manager, community):
    from giljo_mcp.services.user_auth_service import reset_password_via_pin, verify_current_password

    user = await _seed(db_manager)
    async with db_manager.get_session_async(tenant_key=user["tenant_key"]) as session:
        row = (await session.execute(select(User).where(User.id == user["id"]))).scalar_one()
        for _ in range(4):
            assert await verify_current_password(session, row, WRONG) is False
        await reset_password_via_pin(session, row, NEW_PASSWORD)

    async with db_manager.get_session_async() as session:
        remaining = await session.execute(select(LoginLockout).where(LoginLockout.identifier.contains(user["id"])))
        assert remaining.first() is None


_WRONG_CURRENT_ANSWER = json.loads(
    (
        Path(__file__).resolve().parents[2] / "frontend/tests/services/fixtures/change_password_wrong_current.json"
    ).read_text()
)


@pytest.mark.asyncio
async def test_wrong_current_password_answers_400_with_the_pinned_body(api_client, db_manager, community):
    user = await _seed(db_manager)

    resp = await _password_door(api_client, user, WRONG)

    assert resp.status_code == _WRONG_CURRENT_ANSWER["status"] == 400, resp.text
    body = resp.json()
    assert body["error_code"] == _WRONG_CURRENT_ANSWER["error_code"]
    assert body["message"] == _WRONG_CURRENT_ANSWER["message"]
    row = await _lock_row(db_manager, user)
    assert row.failed_count == 1


@pytest.mark.asyncio
async def test_a_missing_current_password_is_a_plain_400_and_counts_no_guess(api_client, db_manager, community):
    user = await _seed(db_manager)

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}/password",
        json={"new_password": NEW_PASSWORD},
        headers=_cookie(user),
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error_code"] != _WRONG_CURRENT_ANSWER["error_code"]
    async with db_manager.get_session_async() as session:
        rows = (
            (await session.execute(select(LoginLockout).where(LoginLockout.identifier.contains(user["id"]))))
            .scalars()
            .all()
        )
    assert rows == []


def test_the_wrong_password_code_is_the_same_in_the_server_and_the_page():
    root = Path(__file__).resolve().parents[2]
    service = (root / "src/giljo_mcp/services/user_auth_service.py").read_text()
    page = (root / "frontend/src/views/account/ProfilePage.vue").read_text()

    server_code = re.search(r'error_code="([A-Z_]+)"\s*,\s*context=\{"user_id"', service)
    page_code = re.search(r"WRONG_CURRENT_PASSWORD_CODE\s*=\s*'([A-Z_]+)'", page)

    assert server_code and page_code
    assert server_code.group(1) == page_code.group(1) == _WRONG_CURRENT_ANSWER["error_code"]
