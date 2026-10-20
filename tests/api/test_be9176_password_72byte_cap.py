# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
from uuid import uuid4

import bcrypt
import pytest
from pydantic import ValidationError

from giljo_mcp.auth.jwt_manager import JWTManager


OLD_PASSWORD = "OldPassword1!"
RECOVERY_PIN = "4242"

LONG_ASCII_100 = "Aa1!" + "x" * 96
EMOJI_OVER_72_BYTES = "Aa1!" + "\U0001f600" * 20
ASCII_73_BYTES = "Aa1!" + "x" * 69
MULTIBYTE_73_BYTES = "Aa1!" + "\u00e4" * 34 + "x"
EXACT_72_BYTES_ASCII = "Aa1!" + "x" * 68
EXACT_72_BYTES_EMOJI = "Aa1!" + "\U0001f600" * 17

OVERSIZED = [LONG_ASCII_100, EMOJI_OVER_72_BYTES, ASCII_73_BYTES, MULTIBYTE_73_BYTES]
OVERSIZED_IDS = ["ascii-100", "emoji-84-bytes", "ascii-73", "multibyte-73"]
EXACTLY_72 = [EXACT_72_BYTES_ASCII, EXACT_72_BYTES_EMOJI]

_CSRF = secrets.token_urlsafe(32)


def test_password_constants_byte_math():
    assert len(LONG_ASCII_100) == 100 and len(LONG_ASCII_100.encode("utf-8")) == 100
    assert len(EMOJI_OVER_72_BYTES) <= 72 and len(EMOJI_OVER_72_BYTES.encode("utf-8")) == 84
    assert len(EXACT_72_BYTES_ASCII.encode("utf-8")) == 72
    assert len(EXACT_72_BYTES_EMOJI) <= 72 and len(EXACT_72_BYTES_EMOJI.encode("utf-8")) == 72
    assert len(ASCII_73_BYTES) == 73 and len(ASCII_73_BYTES.encode("utf-8")) == 73
    assert len(MULTIBYTE_73_BYTES) <= 72 and len(MULTIBYTE_73_BYTES.encode("utf-8")) == 73




async def _seed_user(
    db_manager, *, with_pin: bool = False, must_change_password: bool = False, role: str = "developer"
) -> tuple[str, str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"be9176_user_{unique}"

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"BE9176 Org {unique}",
            slug=f"be9176-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"be9176_{unique}@example.com",
                password_hash=bcrypt.hashpw(OLD_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
                recovery_pin_hash=(
                    bcrypt.hashpw(RECOVERY_PIN.encode("utf-8"), bcrypt.gensalt()).decode("utf-8") if with_pin else None
                ),
                tenant_key=tk,
                role=role,
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
                must_change_password=must_change_password,
                must_set_pin=False,
            )
        )
        await session.commit()

    return user_id, username, tk


def _cookie_headers(token: str) -> dict:
    return {
        "Cookie": f"access_token={token}; csrf_token={_CSRF}",
        "X-CSRF-Token": _CSRF,
    }


def _mint(user_id: str, username: str, tenant_key: str, role: str = "developer") -> str:
    return JWTManager.create_access_token(
        user_id=user_id,
        username=username,
        role=role,
        tenant_key=tenant_key,
        revocation_epoch=0,
    )


class _NoopRateLimiter:
    async def check_rate_limit(self, *args, **kwargs):
        return None


def _pin_route_patches(monkeypatch) -> None:
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.GILJO_MODE", "")
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.get_rate_limiter", _NoopRateLimiter)


def _spy_hashpw(monkeypatch) -> list:
    calls: list = []
    real = bcrypt.hashpw
    monkeypatch.setattr(bcrypt, "hashpw", lambda pw, salt: calls.append(len(pw)) or real(pw, salt))
    return calls


def _assert_refused_on_password_fields(resp) -> None:
    fields = {err["loc"][-1] for err in resp.json()["errors"]}
    assert fields and fields <= {"password", "new_password", "confirm_password"}, fields


async def _persisted_password_hash(db_manager, *, tenant_key: str, user_id: str) -> str:
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        user = await session.get(User, user_id)
        return user.password_hash




@pytest.mark.asyncio
@pytest.mark.parametrize("bad_password", OVERSIZED, ids=OVERSIZED_IDS)
async def test_change_password_route_over_72_bytes_is_422(api_client, db_manager, monkeypatch, bad_password):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)

    hashpw_calls = _spy_hashpw(monkeypatch)
    resp = await api_client.put(
        f"/api/v1/users/{user_id}/password",
        json={"old_password": OLD_PASSWORD, "new_password": bad_password},
        headers=_cookie_headers(_mint(user_id, username, tk)),
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    _assert_refused_on_password_fields(resp)
    assert hashpw_calls == []


@pytest.mark.asyncio
async def test_change_password_route_exactly_72_bytes_succeeds(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)

    resp = await api_client.put(
        f"/api/v1/users/{user_id}/password",
        json={"old_password": OLD_PASSWORD, "new_password": EXACT_72_BYTES_ASCII},
        headers=_cookie_headers(_mint(user_id, username, tk)),
    )
    assert resp.status_code == 200, resp.text

    password_hash = await _persisted_password_hash(db_manager, tenant_key=tk, user_id=user_id)
    assert bcrypt.checkpw(EXACT_72_BYTES_ASCII.encode("utf-8"), password_hash.encode("utf-8"))
    assert not bcrypt.checkpw(OLD_PASSWORD.encode("utf-8"), password_hash.encode("utf-8"))




@pytest.mark.asyncio
@pytest.mark.parametrize("bad_password", OVERSIZED, ids=OVERSIZED_IDS)
async def test_pin_reset_route_over_72_bytes_is_422(api_client, db_manager, monkeypatch, bad_password):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    _pin_route_patches(monkeypatch)
    _, username, _ = await _seed_user(db_manager, with_pin=True)

    hashpw_calls = _spy_hashpw(monkeypatch)
    resp = await api_client.post(
        "/api/auth/verify-pin-and-reset-password",
        json={
            "username": username,
            "recovery_pin": RECOVERY_PIN,
            "new_password": bad_password,
            "confirm_password": bad_password,
        },
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    _assert_refused_on_password_fields(resp)
    assert hashpw_calls == []


@pytest.mark.asyncio
async def test_pin_reset_route_exactly_72_bytes_succeeds(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    _pin_route_patches(monkeypatch)
    user_id, username, tk = await _seed_user(db_manager, with_pin=True)

    resp = await api_client.post(
        "/api/auth/verify-pin-and-reset-password",
        json={
            "username": username,
            "recovery_pin": RECOVERY_PIN,
            "new_password": EXACT_72_BYTES_EMOJI,
            "confirm_password": EXACT_72_BYTES_EMOJI,
        },
    )
    assert resp.status_code == 200, resp.text

    password_hash = await _persisted_password_hash(db_manager, tenant_key=tk, user_id=user_id)
    assert bcrypt.checkpw(EXACT_72_BYTES_EMOJI.encode("utf-8"), password_hash.encode("utf-8"))




@pytest.mark.asyncio
@pytest.mark.parametrize("bad_password", OVERSIZED, ids=OVERSIZED_IDS)
async def test_complete_first_login_over_72_bytes_is_422(api_client, db_manager, monkeypatch, bad_password):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager, must_change_password=True)

    hashpw_calls = _spy_hashpw(monkeypatch)
    resp = await api_client.post(
        "/api/auth/complete-first-login",
        json={
            "current_password": OLD_PASSWORD,
            "new_password": bad_password,
            "confirm_password": bad_password,
        },
        headers=_cookie_headers(_mint(user_id, username, tk)),
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    _assert_refused_on_password_fields(resp)
    assert hashpw_calls == []




@pytest.mark.asyncio
@pytest.mark.parametrize("bad_password", OVERSIZED, ids=OVERSIZED_IDS)
async def test_update_user_route_password_over_72_bytes_is_422(api_client, db_manager, monkeypatch, bad_password):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)
    hashpw_calls = _spy_hashpw(monkeypatch)

    resp = await api_client.put(
        f"/api/v1/users/{user_id}",
        json={"password": bad_password},
        headers=_cookie_headers(_mint(user_id, username, tk)),
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    _assert_refused_on_password_fields(resp)
    assert hashpw_calls == []


@pytest.mark.asyncio
async def test_update_user_route_exactly_72_bytes_reaches_the_hash(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)
    hashpw_calls = _spy_hashpw(monkeypatch)

    resp = await api_client.put(
        f"/api/v1/users/{user_id}",
        json={"password": EXACT_72_BYTES_EMOJI},
        headers=_cookie_headers(_mint(user_id, username, tk)),
    )
    assert resp.status_code == 200, resp.text
    assert hashpw_calls == [72]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/users/", "/api/auth/register"], ids=["users-create", "auth-register"])
@pytest.mark.parametrize("bad_password", OVERSIZED, ids=OVERSIZED_IDS)
async def test_admin_create_user_routes_over_72_bytes_are_422(api_client, db_manager, monkeypatch, path, bad_password):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    admin_id, admin_name, tk = await _seed_user(db_manager, role="admin")
    hashpw_calls = _spy_hashpw(monkeypatch)

    resp = await api_client.post(
        path,
        json={"username": f"sec9803_{uuid4().hex[:8]}", "password": bad_password},
        headers=_cookie_headers(_mint(admin_id, admin_name, tk, role="admin")),
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    _assert_refused_on_password_fields(resp)
    assert hashpw_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_password", OVERSIZED, ids=OVERSIZED_IDS)
async def test_create_first_admin_route_over_72_bytes_is_422(api_client, monkeypatch, bad_password):
    hashpw_calls = _spy_hashpw(monkeypatch)

    resp = await api_client.post(
        "/api/auth/create-first-admin",
        json={"username": f"sec9803_{uuid4().hex[:8]}", "password": bad_password},
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    _assert_refused_on_password_fields(resp)
    assert hashpw_calls == []




def _schema_cases():
    from api.endpoints.auth.models import PasswordChangeRequest, RegisterUserRequest
    from api.endpoints.auth_models import CompleteFirstLoginRequest, PinPasswordResetRequest
    from api.endpoints.users import PasswordChange, UserCreate, UserUpdate

    def build(schema, password):
        if schema is UserCreate:
            return schema(username="be9176user", password=password)
        if schema is UserUpdate:
            return schema(password=password)
        if schema is PasswordChange:
            return schema(old_password=OLD_PASSWORD, new_password=password)
        if schema is RegisterUserRequest:
            return schema(username="be9176user", password=password)
        if schema is PinPasswordResetRequest:
            return schema(
                username="be9176user",
                recovery_pin=RECOVERY_PIN,
                new_password=password,
                confirm_password=password,
            )
        if schema is CompleteFirstLoginRequest:
            return schema(current_password=OLD_PASSWORD, new_password=password, confirm_password=password)
        if schema is PasswordChangeRequest:
            return schema(current_password=OLD_PASSWORD, new_password=password, confirm_password=password)
        raise AssertionError(f"unmapped schema {schema}")

    schemas = [
        UserCreate,
        UserUpdate,
        PasswordChange,
        RegisterUserRequest,
        PinPasswordResetRequest,
        CompleteFirstLoginRequest,
        PasswordChangeRequest,
    ]
    return build, schemas


@pytest.mark.parametrize("bad_password", OVERSIZED, ids=OVERSIZED_IDS)
def test_all_password_set_schemas_reject_over_72_bytes(bad_password):
    build, schemas = _schema_cases()
    for schema in schemas:
        with pytest.raises(ValidationError):
            build(schema, bad_password)


@pytest.mark.parametrize("good_password", EXACTLY_72, ids=["ascii-72", "emoji-72-bytes"])
def test_all_password_set_schemas_accept_exactly_72_bytes(good_password):
    build, schemas = _schema_cases()
    for schema in schemas:
        built = build(schema, good_password)
        assert built is not None, schema.__name__
