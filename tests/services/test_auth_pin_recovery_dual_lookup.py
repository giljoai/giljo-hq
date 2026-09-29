# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio
from fastapi import HTTPException

from api.endpoints.auth_models import (
    CheckFirstLoginRequest,
    PinPasswordResetRequest,
)
from api.endpoints.auth_pin_recovery import (
    VerifyPinRequest,
    check_first_login,
    verify_pin,
    verify_pin_and_reset_password,
)
from giljo_mcp.models.auth import User
from giljo_mcp.repositories.auth_repository import AuthRepository




@pytest_asyncio.fixture
async def pin_user(db_session, auth_test_org):
    suffix = uuid4().hex[:6]
    password = "Pin1234!A"
    pin = "4242"
    user = User(
        id=str(uuid4()),
        username=f"pinuser_{suffix}",
        email=f"pu_{suffix}@ex.com",
        full_name="Pin User",
        password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        recovery_pin_hash=bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key=auth_test_org.tenant_key,
        org_id=auth_test_org.id,
        is_active=True,
        must_change_password=True,
        must_set_pin=False,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, password, pin


def _fake_request():
    return SimpleNamespace(
        base_url="http://test/",
        url=SimpleNamespace(path="/api/auth/verify-pin-and-reset-password"),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
    )




class TestRepoDualLookupHelper:

    @pytest.mark.asyncio
    async def test_resolves_by_username(self, db_session, pin_user):
        user, _, _ = pin_user
        repo = AuthRepository()

        found = await repo.get_user_by_username_or_email(db_session, user.username)

        assert found is not None
        assert found.id == user.id

    @pytest.mark.asyncio
    async def test_resolves_by_email(self, db_session, pin_user):
        user, _, _ = pin_user
        repo = AuthRepository()

        found = await repo.get_user_by_username_or_email(db_session, user.email)

        assert found is not None
        assert found.id == user.id

    @pytest.mark.asyncio
    async def test_email_lookup_is_case_insensitive(self, db_session, pin_user):
        user, _, _ = pin_user
        repo = AuthRepository()

        found = await repo.get_user_by_username_or_email(db_session, user.email.upper())

        assert found is not None
        assert found.id == user.id

    @pytest.mark.asyncio
    async def test_unknown_returns_none(self, db_session):
        repo = AuthRepository()

        found = await repo.get_user_by_username_or_email(db_session, "nobody_xyz")

        assert found is None

    @pytest.mark.asyncio
    async def test_username_match_wins_over_email_match(self, db_session, auth_test_org):
        shared = f"collide_{uuid4().hex[:8]}"
        u1 = User(
            id=str(uuid4()),
            username=shared,
            email=f"{shared}_u1@ex.com",
            password_hash="x",
            role="developer",
            tenant_key=auth_test_org.tenant_key,
            org_id=auth_test_org.id,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        u2 = User(
            id=str(uuid4()),
            username=f"other_{uuid4().hex[:6]}",
            email=shared,
            password_hash="x",
            role="developer",
            tenant_key=auth_test_org.tenant_key,
            org_id=auth_test_org.id,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add_all([u1, u2])
        await db_session.commit()

        repo = AuthRepository()
        found = await repo.get_user_by_username_or_email(db_session, shared)

        assert found is not None
        assert found.id == u1.id




class TestVerifyPinDualLookup:
    @pytest.mark.asyncio
    async def test_by_username(self, db_session, pin_user):
        user, _, pin = pin_user
        req = VerifyPinRequest(username=user.username, recovery_pin=pin)

        resp = await verify_pin(http_request=_fake_request(), request_data=req, db=db_session)

        assert resp.valid is True

    @pytest.mark.asyncio
    async def test_by_email(self, db_session, pin_user):
        user, _, pin = pin_user
        req = VerifyPinRequest(username=user.email, recovery_pin=pin)

        resp = await verify_pin(http_request=_fake_request(), request_data=req, db=db_session)

        assert resp.valid is True

    @pytest.mark.asyncio
    async def test_unknown_identifier_returns_invalid(self, db_session):
        req = VerifyPinRequest(username="ghost_abc", recovery_pin="0000")

        resp = await verify_pin(http_request=_fake_request(), request_data=req, db=db_session)

        assert resp.valid is False
        assert "Invalid username or PIN" in resp.message




class TestVerifyPinAndResetDualLookup:
    @pytest.mark.asyncio
    async def test_by_username(self, db_session, pin_user):
        user, _, pin = pin_user
        new_password = "NewPwd123!Z"
        req = PinPasswordResetRequest(
            username=user.username,
            recovery_pin=pin,
            new_password=new_password,
            confirm_password=new_password,
        )

        resp = await verify_pin_and_reset_password(http_request=_fake_request(), request_data=req, db=db_session)

        assert "successful" in resp.message.lower()
        await db_session.refresh(user)
        assert bcrypt.checkpw(new_password.encode("utf-8"), user.password_hash.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_by_email(self, db_session, pin_user):
        user, _, pin = pin_user
        new_password = "NewPwd456!Y"
        req = PinPasswordResetRequest(
            username=user.email,
            recovery_pin=pin,
            new_password=new_password,
            confirm_password=new_password,
        )

        resp = await verify_pin_and_reset_password(http_request=_fake_request(), request_data=req, db=db_session)

        assert "successful" in resp.message.lower()
        await db_session.refresh(user)
        assert bcrypt.checkpw(new_password.encode("utf-8"), user.password_hash.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_unknown_identifier_raises_generic_error(self, db_session):
        req = PinPasswordResetRequest(
            username="ghost_xyz",
            recovery_pin="0000",
            new_password="SomePwd9!A",
            confirm_password="SomePwd9!A",
        )

        with pytest.raises(HTTPException) as exc:
            await verify_pin_and_reset_password(http_request=_fake_request(), request_data=req, db=db_session)

        assert exc.value.status_code == 400
        assert "Invalid username or PIN" in exc.value.detail




class TestCheckFirstLoginDualLookup:
    @pytest.mark.asyncio
    async def test_by_username(self, db_session, pin_user):
        user, _, _ = pin_user
        req = CheckFirstLoginRequest(username=user.username)

        resp = await check_first_login(request_data=req, db=db_session)

        assert resp.must_change_password is True
        assert resp.must_set_pin is False

    @pytest.mark.asyncio
    async def test_by_email(self, db_session, pin_user):
        user, _, _ = pin_user
        req = CheckFirstLoginRequest(username=user.email)

        resp = await check_first_login(request_data=req, db=db_session)

        assert resp.must_change_password is True
        assert resp.must_set_pin is False

    @pytest.mark.asyncio
    async def test_unknown_identifier_returns_safe_defaults(self, db_session):
        req = CheckFirstLoginRequest(username="ghost_ident")

        resp = await check_first_login(request_data=req, db=db_session)

        assert resp.must_change_password is False
        assert resp.must_set_pin is False
