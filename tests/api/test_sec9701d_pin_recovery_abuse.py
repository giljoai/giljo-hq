# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import pytest

from api.endpoints.auth_pin_recovery import VerifyPinRequest, verify_pin
from giljo_mcp.models.auth import User
from giljo_mcp.repositories.auth_repository import AuthRepository


PIN = "4242"
WRONG_PIN = "0000"


async def _seed_pin_user(db_manager) -> tuple[str, str, str]:
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"sec9701d_pin_user_{unique}"

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"SEC9701d PIN Org {unique}",
            slug=f"sec9701d-pin-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"sec9701d_pin_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"SeedPassword1!A", bcrypt.gensalt()).decode("utf-8"),
                recovery_pin_hash=bcrypt.hashpw(PIN.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
                failed_pin_attempts=0,
            )
        )
        await session.commit()

    return user_id, username, tk


def _fake_request(ip: str = "127.0.0.1", path: str = "/api/auth/verify-pin"):
    return SimpleNamespace(
        base_url="http://test/",
        url=SimpleNamespace(path=path),
        client=SimpleNamespace(host=ip),
        headers={},
    )


async def _get_failed_pin_attempts(db_manager, *, tenant_key: str, user_id: str) -> int:
    from sqlalchemy import select

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        return user.failed_pin_attempts




@pytest.mark.asyncio
async def test_unknown_user_and_wrong_pin_get_byte_identical_responses(db_manager):
    _user_id, username, tk = await _seed_pin_user(db_manager)

    async with db_manager.get_session_async(tenant_key=tk) as session:
        unknown_resp = await verify_pin(
            http_request=_fake_request(),
            request_data=VerifyPinRequest(username="ghost_nonexistent", recovery_pin=WRONG_PIN),
            db=session,
        )

    async with db_manager.get_session_async(tenant_key=tk) as session:
        wrong_pin_resp = await verify_pin(
            http_request=_fake_request(),
            request_data=VerifyPinRequest(username=username, recovery_pin=WRONG_PIN),
            db=session,
        )

    assert unknown_resp.valid is False
    assert wrong_pin_resp.valid is False
    assert unknown_resp.message == wrong_pin_resp.message == "Invalid username or PIN"


@pytest.mark.asyncio
async def test_locked_out_user_gets_the_same_generic_message(db_manager, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    from api.endpoints import auth_pin_recovery

    user_id, username, tk = await _seed_pin_user(db_manager)

    async with db_manager.get_session_async(tenant_key=tk) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        user.pin_lockout_until = datetime.now(UTC) + timedelta(minutes=15)
        await session.commit()

    real_verify = auth_pin_recovery.async_verify_password
    verify_spy = AsyncMock(side_effect=real_verify)
    monkeypatch.setattr(auth_pin_recovery, "async_verify_password", verify_spy)

    async with db_manager.get_session_async(tenant_key=tk) as session:
        resp = await verify_pin(
            http_request=_fake_request(),
            request_data=VerifyPinRequest(username=username, recovery_pin=PIN),
            db=session,
        )

    assert resp.valid is False
    assert resp.message == "Invalid username or PIN"
    verify_spy.assert_awaited_once()


@pytest.mark.asyncio
async def test_fourth_verify_pin_call_per_minute_from_same_ip_gets_429(db_manager, real_auth_rate_limiter):
    from fastapi import HTTPException

    _user_id, _username, tk = await _seed_pin_user(db_manager)
    ip = f"198.51.100.{uuid4().int % 250 + 1}"

    async def _call():
        async with db_manager.get_session_async(tenant_key=tk) as session:
            return await verify_pin(
                http_request=_fake_request(ip=ip),
                request_data=VerifyPinRequest(username="ghost_rate_limit_probe", recovery_pin=WRONG_PIN),
                db=session,
            )

    for _ in range(3):
        resp = await _call()
        assert resp.valid is False

    with pytest.raises(HTTPException) as exc:
        await _call()
    assert exc.value.status_code == 429




@pytest.mark.asyncio
async def test_parallel_wrong_pin_attempts_counter_equals_number_of_attempts(db_manager, monkeypatch):
    _user_id, username, tk = await _seed_pin_user(db_manager)

    real_lookup = AuthRepository.get_user_by_username_or_email
    barrier = asyncio.Barrier(2)

    async def _lookup_with_rendezvous(self, db, identifier):
        user = await real_lookup(self, db, identifier)
        await asyncio.wait_for(barrier.wait(), timeout=30)
        return user

    monkeypatch.setattr(AuthRepository, "get_user_by_username_or_email", _lookup_with_rendezvous)

    async def _call():
        async with db_manager.get_session_async(tenant_key=tk) as session:
            return await verify_pin(
                http_request=_fake_request(),
                request_data=VerifyPinRequest(username=username, recovery_pin=WRONG_PIN),
                db=session,
            )

    resp_a, resp_b = await asyncio.wait_for(asyncio.gather(_call(), _call()), timeout=30)

    assert resp_a.valid is False
    assert resp_b.valid is False

    final_count = await _get_failed_pin_attempts(db_manager, tenant_key=tk, user_id=_user_id)
    assert final_count == 2, f"expected both concurrent wrong guesses to be counted, got {final_count}"
