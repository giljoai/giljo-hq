# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from api.endpoints.auth_models import PinPasswordResetRequest
from api.endpoints.auth_pin_recovery import VerifyPinRequest, verify_pin, verify_pin_and_reset_password
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models.auth import User
from giljo_mcp.repositories.auth_repository import AuthRepository


PASSWORD = "Password1!"
PIN = "4242"
WRONG_PIN = "0000"
NEW_PIN = "1357"
NEW_PASSWORD = "NewPassword2@"
_CSRF = secrets.token_urlsafe(32)
_REMOTE_IP = "198.51.100.23"


async def _seed(
    db_manager,
    *,
    role: str = "admin",
    tenant_key: str | None = None,
    failed_pin_attempts: int = 0,
    pin_lockout_until: datetime | None = None,
    must_change_password: bool = False,
) -> dict:
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = tenant_key or TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user = {
        "id": str(uuid4()),
        "username": f"sec0060_{unique}",
        "email": f"sec0060_{unique}@example.com",
        "tenant_key": tenant_key,
        "role": role,
    }
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(name=f"SEC0060 {unique}", slug=f"sec0060-{unique}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user["id"],
                username=user["username"],
                email=user["email"],
                password_hash=bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode(),
                recovery_pin_hash=bcrypt.hashpw(PIN.encode(), bcrypt.gensalt(rounds=4)).decode(),
                tenant_key=tenant_key,
                role=role,
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
                failed_pin_attempts=failed_pin_attempts,
                pin_lockout_until=pin_lockout_until,
                must_change_password=must_change_password,
            )
        )
        await session.commit()
    return user


async def _row(db_manager, user: dict) -> User:
    async with db_manager.get_session_async(tenant_key=user["tenant_key"]) as session:
        return (
            await session.execute(select(User).where(User.id == user["id"], User.tenant_key == user["tenant_key"]))
        ).scalar_one()


def _request(ip: str = _REMOTE_IP, headers: dict | None = None):
    return SimpleNamespace(
        url=SimpleNamespace(path="/api/auth/verify-pin"),
        client=SimpleNamespace(host=ip),
        headers=headers or {},
        scope={},
    )


async def _verify(db_manager, user: dict, pin: str, *, ip: str = _REMOTE_IP, headers: dict | None = None):
    async with db_manager.get_session_async() as session:
        return await verify_pin(
            http_request=_request(ip, headers),
            request_data=VerifyPinRequest(username=user["username"], recovery_pin=pin),
            db=session,
        )


def _cookie(user: dict) -> dict:
    token = JWTManager.create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        tenant_key=user["tenant_key"],
        revocation_epoch=0,
    )
    return {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


@pytest.fixture
def community(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setenv("GILJO_MODE", "ce")
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.GILJO_MODE", "ce")
    monkeypatch.delenv("GILJO_TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)


def _expired() -> datetime:
    return datetime.now(UTC) - timedelta(seconds=1)




@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prior_failures", "minimum_lock"),
    [(5, timedelta(minutes=59)), (6, timedelta(hours=3, minutes=59)), (7, timedelta(hours=23, minutes=59))],
)
async def test_a_guess_after_each_lock_expiry_locks_for_longer(db_manager, community, prior_failures, minimum_lock):
    user = await _seed(db_manager, failed_pin_attempts=prior_failures, pin_lockout_until=_expired())

    resp = await _verify(db_manager, user, WRONG_PIN)

    assert resp.valid is False
    row = await _row(db_manager, user)
    assert row.failed_pin_attempts == prior_failures + 1
    assert row.pin_lockout_until - datetime.now(UTC) >= minimum_lock


@pytest.mark.asyncio
async def test_the_lock_stays_at_one_day_after_many_failures(db_manager, community):
    user = await _seed(db_manager, failed_pin_attempts=40, pin_lockout_until=_expired())

    await _verify(db_manager, user, WRONG_PIN)

    remaining = (await _row(db_manager, user)).pin_lockout_until - datetime.now(UTC)
    assert timedelta(hours=23, minutes=59) <= remaining <= timedelta(hours=24)


@pytest.mark.asyncio
async def test_a_burst_of_guesses_at_lock_expiry_gets_one_guess(db_manager, community, monkeypatch):
    user = await _seed(db_manager, failed_pin_attempts=5, pin_lockout_until=_expired())
    real_lookup = AuthRepository.get_user_by_username_or_email
    barrier = asyncio.Barrier(2)

    async def _lookup_then_rendezvous(self, db, identifier):
        found = await real_lookup(self, db, identifier)
        await asyncio.wait_for(barrier.wait(), timeout=30)
        return found

    monkeypatch.setattr(AuthRepository, "get_user_by_username_or_email", _lookup_then_rendezvous)

    await asyncio.wait_for(
        asyncio.gather(_verify(db_manager, user, WRONG_PIN), _verify(db_manager, user, "1111")), timeout=30
    )

    assert (await _row(db_manager, user)).failed_pin_attempts == 6


@pytest.mark.asyncio
async def test_console_caller_is_never_locked_out(db_manager, community):
    user = await _seed(db_manager, failed_pin_attempts=9, pin_lockout_until=datetime.now(UTC) + timedelta(hours=20))

    resp = await _verify(db_manager, user, PIN, ip="127.0.0.1")

    assert resp.valid is True


@pytest.mark.asyncio
async def test_console_caller_can_reset_the_password_while_locked(db_manager, community):
    user = await _seed(db_manager, failed_pin_attempts=9, pin_lockout_until=datetime.now(UTC) + timedelta(hours=20))

    async with db_manager.get_session_async() as session:
        resp = await verify_pin_and_reset_password(
            http_request=_request("127.0.0.1"),
            request_data=PinPasswordResetRequest(
                username=user["username"],
                recovery_pin=PIN,
                new_password=NEW_PASSWORD,
                confirm_password=NEW_PASSWORD,
            ),
            db=session,
        )

    assert resp.message == "Password reset successful"
    row = await _row(db_manager, user)
    assert row.failed_pin_attempts == 0
    assert row.pin_lockout_until is None


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["X-Forwarded-For", "Forwarded", "X-Real-IP"])
async def test_loopback_through_a_local_proxy_is_still_locked(db_manager, community, header):
    user = await _seed(db_manager, failed_pin_attempts=9, pin_lockout_until=datetime.now(UTC) + timedelta(hours=20))

    resp = await _verify(db_manager, user, PIN, ip="127.0.0.1", headers={header: "203.0.113.9"})

    assert resp.valid is False


@pytest.mark.asyncio
async def test_remote_reset_while_locked_is_refused(db_manager, community):
    user = await _seed(db_manager, failed_pin_attempts=9, pin_lockout_until=datetime.now(UTC) + timedelta(hours=20))

    async with db_manager.get_session_async() as session:
        with pytest.raises(HTTPException) as exc:
            await verify_pin_and_reset_password(
                http_request=_request(),
                request_data=PinPasswordResetRequest(
                    username=user["username"],
                    recovery_pin=PIN,
                    new_password=NEW_PASSWORD,
                    confirm_password=NEW_PASSWORD,
                ),
                db=session,
            )

    assert exc.value.status_code == 429
    assert (await _row(db_manager, user)).failed_pin_attempts == 9


@pytest.mark.asyncio
async def test_password_sign_in_resets_the_pin_lockout(api_client, db_manager, community):
    user = await _seed(db_manager, failed_pin_attempts=7, pin_lockout_until=datetime.now(UTC) + timedelta(hours=4))

    resp = await api_client.post("/api/auth/login", json={"username": user["username"], "password": PASSWORD})

    assert resp.status_code == 200, resp.text
    row = await _row(db_manager, user)
    assert row.failed_pin_attempts == 0
    assert row.pin_lockout_until is None




async def _pin_matches(db_manager, user: dict, pin: str) -> bool:
    stored = (await _row(db_manager, user)).recovery_pin_hash
    return bcrypt.checkpw(pin.encode(), stored.encode())


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "developer"])
async def test_own_pin_change_without_the_current_password_is_refused(api_client, db_manager, community, role):
    user = await _seed(db_manager, role=role)

    resp = await api_client.put(f"/api/v1/users/{user['id']}", json={"recovery_pin": NEW_PIN}, headers=_cookie(user))

    assert resp.status_code == 403, resp.text
    assert await _pin_matches(db_manager, user, PIN)


@pytest.mark.asyncio
async def test_own_pin_change_with_a_wrong_current_password_is_refused(api_client, db_manager, community):
    user = await _seed(db_manager)

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}",
        json={"recovery_pin": NEW_PIN, "current_password": "NotThePassword9!"},
        headers=_cookie(user),
    )

    assert resp.status_code == 400, resp.text
    assert await _pin_matches(db_manager, user, PIN)


@pytest.mark.asyncio
async def test_own_pin_change_with_the_current_password_works(api_client, db_manager, community):
    user = await _seed(db_manager, role="developer")

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}",
        json={"recovery_pin": NEW_PIN, "current_password": PASSWORD},
        headers=_cookie(user),
    )

    assert resp.status_code == 200, resp.text
    assert await _pin_matches(db_manager, user, NEW_PIN)


@pytest.mark.asyncio
async def test_control_admin_still_sets_another_users_pin(api_client, db_manager, community):
    admin = await _seed(db_manager, role="admin")
    member = await _seed(db_manager, role="developer", tenant_key=admin["tenant_key"])

    resp = await api_client.put(f"/api/v1/users/{member['id']}", json={"recovery_pin": NEW_PIN}, headers=_cookie(admin))

    assert resp.status_code == 200, resp.text
    assert await _pin_matches(db_manager, member, NEW_PIN)




@pytest.mark.asyncio
async def test_check_first_login_tells_another_tenants_user_nothing(api_client, db_manager, community):
    target = await _seed(db_manager, must_change_password=True)
    stranger = await _seed(db_manager, role="developer")

    known = await api_client.post(
        "/api/auth/check-first-login", json={"username": target["username"]}, headers=_cookie(stranger)
    )
    unknown = await api_client.post(
        "/api/auth/check-first-login", json={"username": f"ghost_{uuid4().hex[:8]}"}, headers=_cookie(stranger)
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {"must_change_password": False, "must_set_pin": False}


@pytest.mark.asyncio
async def test_check_first_login_answers_the_signed_in_caller(api_client, db_manager, community):
    user = await _seed(db_manager, must_change_password=True)

    resp = await api_client.post(
        "/api/auth/check-first-login", json={"username": user["username"]}, headers=_cookie(user)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["must_change_password"] is True


@pytest.mark.asyncio
async def test_check_first_login_needs_a_session(api_client, db_manager, community):
    user = await _seed(db_manager, must_change_password=True)

    resp = await api_client.post("/api/auth/check-first-login", json={"username": user["username"]})

    assert resp.status_code == 401
