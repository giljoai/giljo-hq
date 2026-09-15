# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import contextlib

import bcrypt
import pytest
from fastapi import HTTPException

from api.endpoints.auth_models import (
    CheckFirstLoginRequest,
    CompleteFirstLoginRequest,
    PinPasswordResetRequest,
)
from api.endpoints.auth_pin_recovery import (
    VerifyPinRequest,
    check_first_login,
    complete_first_login,
    verify_pin,
    verify_pin_and_reset_password,
)
from giljo_mcp.repositories.auth_repository import AuthRepository


_GILJO_MODE_ATTR = "api.endpoints.auth_pin_recovery.GILJO_MODE"


class _NoopRateLimiter:

    async def check_rate_limit(self, *args, **kwargs):
        return None


class _FakeUser:
    def __init__(self, must_set_pin: bool, must_change_password: bool, password_hash: str | None = None):
        self.must_set_pin = must_set_pin
        self.must_change_password = must_change_password
        self.password_hash = password_hash
        self.recovery_pin_hash = None
        self.username = "first_login_user"
        self.id = "fake-user-id"
        self.tenant_key = "fake-tenant"
        self.token_revocation_epoch = 0


class _FakeDB:
    async def commit(self):
        return None


def _patch_repo_user(monkeypatch, user):

    async def _fake_lookup(self, db, identifier):
        return user

    monkeypatch.setattr(AuthRepository, "get_user_by_username_or_email", _fake_lookup)




@pytest.mark.asyncio
async def test_verify_pin_reset_hidden_in_saas(monkeypatch):
    monkeypatch.setattr(_GILJO_MODE_ATTR, "saas")
    req = PinPasswordResetRequest(
        username="someuser", recovery_pin="1234", new_password="NewPass1!B", confirm_password="NewPass1!B"
    )
    with pytest.raises(HTTPException) as exc:
        await verify_pin_and_reset_password(http_request=None, request_data=req, db=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_verify_pin_reset_reachable_in_ce_empty(monkeypatch):
    monkeypatch.setattr(_GILJO_MODE_ATTR, "")
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.get_rate_limiter", _NoopRateLimiter)
    req = PinPasswordResetRequest(
        username="someuser", recovery_pin="1234", new_password="NewPass1!B", confirm_password="Different1!C"
    )
    with pytest.raises(HTTPException) as exc:
        await verify_pin_and_reset_password(http_request=object(), request_data=req, db=object())
    assert exc.value.status_code == 400
    assert "do not match" in exc.value.detail.lower()




@pytest.mark.asyncio
async def test_verify_pin_hidden_in_saas(monkeypatch):
    monkeypatch.setattr(_GILJO_MODE_ATTR, "saas")
    req = VerifyPinRequest(username="someuser", recovery_pin="1234")
    with pytest.raises(HTTPException) as exc:
        await verify_pin(request_data=req, db=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_verify_pin_reachable_in_ce_empty(monkeypatch):
    monkeypatch.setattr(_GILJO_MODE_ATTR, "")
    _patch_repo_user(monkeypatch, None)
    resp = await verify_pin(request_data=VerifyPinRequest(username="ghost", recovery_pin="1234"), db=object())
    assert resp.valid is False




@pytest.mark.asyncio
async def test_check_first_login_requires_pin_setup_in_ce_empty(monkeypatch):
    monkeypatch.setattr(_GILJO_MODE_ATTR, "")
    _patch_repo_user(monkeypatch, _FakeUser(must_set_pin=True, must_change_password=True))
    resp = await check_first_login(request_data=CheckFirstLoginRequest(username="first_login_user"), db=object())
    assert resp.must_set_pin is True
    assert resp.must_change_password is True


@pytest.mark.asyncio
async def test_check_first_login_suppresses_pin_setup_in_saas(monkeypatch):
    monkeypatch.setattr(_GILJO_MODE_ATTR, "saas")
    _patch_repo_user(monkeypatch, _FakeUser(must_set_pin=True, must_change_password=True))
    resp = await check_first_login(request_data=CheckFirstLoginRequest(username="first_login_user"), db=object())
    assert resp.must_set_pin is False
    assert resp.must_change_password is True




def _complete_request(with_pin: bool) -> CompleteFirstLoginRequest:
    kwargs = {
        "current_password": "OldPass1!A",
        "new_password": "NewPass1!B",
        "confirm_password": "NewPass1!B",
    }
    if with_pin:
        kwargs.update({"recovery_pin": "4242", "confirm_pin": "4242"})
    return CompleteFirstLoginRequest(**kwargs)


def _user_with_password(password: str) -> _FakeUser:
    return _FakeUser(
        must_set_pin=True,
        must_change_password=True,
        password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
    )


@pytest.mark.asyncio
async def test_complete_first_login_requires_pin_in_ce_empty(monkeypatch):
    monkeypatch.setattr(_GILJO_MODE_ATTR, "")
    user = _user_with_password("OldPass1!A")
    with pytest.raises(HTTPException) as exc:
        await complete_first_login(request_data=_complete_request(with_pin=False), current_user=user, db=_FakeDB())
    assert exc.value.status_code == 400
    assert "pin is required" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_complete_first_login_ignores_missing_pin_in_saas(monkeypatch):
    monkeypatch.setattr(_GILJO_MODE_ATTR, "saas")

    @contextlib.contextmanager
    def _noop_tenant_ctx(db, tenant_key):
        yield

    async def _fake_revoke(db, *, user_id, tenant_key):
        return 0

    monkeypatch.setattr("api.endpoints.auth_pin_recovery.tenant_session_context", _noop_tenant_ctx)
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.revoke_all_refresh_tokens_for_user", _fake_revoke)

    user = _user_with_password("OldPass1!A")
    resp = await complete_first_login(request_data=_complete_request(with_pin=False), current_user=user, db=_FakeDB())
    assert resp is not None
    assert user.must_change_password is False
    assert user.must_set_pin is False
    assert user.recovery_pin_hash is None
    assert user.token_revocation_epoch == 1
