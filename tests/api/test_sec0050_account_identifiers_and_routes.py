# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.exceptions import ValidationError


PASSWORD = "Password1!"
NEW_PASSWORD = "NewPassword2@"
_CSRF = secrets.token_urlsafe(32)


async def _seed(db_manager, *, tenant_key: str | None = None, role: str = "admin", username=None, email=None) -> dict:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = tenant_key or TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user = {
        "id": str(uuid4()),
        "username": username or f"sec0050_{unique}",
        "email": email if email is not None else f"sec0050_{unique}@example.com",
        "tenant_key": tenant_key,
        "role": role,
    }
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(name=f"SEC0050 {unique}", slug=f"sec0050-{unique}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user["id"],
                username=user["username"],
                email=user["email"],
                password_hash=bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode(),
                tenant_key=tenant_key,
                role=role,
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()
    return user


def _refusal(resp, value: str) -> dict:
    body = resp.json()
    return {"status": resp.status_code, "code": body.get("error_code"), "message": body["message"].replace(value, "X")}


def _cookie(user: dict) -> dict:
    token = JWTManager.create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        tenant_key=user["tenant_key"],
        revocation_epoch=0,
    )
    return {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


async def _row(db_manager, user: dict):
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async(tenant_key=user["tenant_key"]) as session:
        return (
            await session.execute(select(User).where(User.id == user["id"], User.tenant_key == user["tenant_key"]))
        ).scalar_one()


def _auth_service(db_manager):
    from giljo_mcp.services.auth_service import AuthService

    return AuthService(db_manager=db_manager)


@pytest.fixture
def community(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setenv("GILJO_MODE", "ce")




@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "developer"])
async def test_generic_route_refuses_a_new_password_for_the_callers_own_account(
    api_client, db_manager, community, role
):
    user = await _seed(db_manager, role=role)
    before = await _row(db_manager, user)

    resp = await api_client.put(f"/api/v1/users/{user['id']}", json={"password": NEW_PASSWORD}, headers=_cookie(user))

    assert resp.status_code == 403, resp.text
    after = await _row(db_manager, user)
    assert after.password_hash == before.password_hash
    assert after.token_revocation_epoch == before.token_revocation_epoch


@pytest.mark.asyncio
async def test_control_admin_still_sets_another_users_password_and_evicts_them(api_client, db_manager, community):
    admin = await _seed(db_manager, role="admin")
    member = await _seed(db_manager, tenant_key=admin["tenant_key"], role="developer")
    before = await _row(db_manager, member)

    resp = await api_client.put(
        f"/api/v1/users/{member['id']}", json={"password": NEW_PASSWORD}, headers=_cookie(admin)
    )

    assert resp.status_code == 200, resp.text
    after = await _row(db_manager, member)
    assert after.password_hash != before.password_hash
    assert after.token_revocation_epoch == before.token_revocation_epoch + 1


@pytest.mark.asyncio
async def test_control_own_password_change_with_the_current_password_still_works(api_client, db_manager, community):
    user = await _seed(db_manager, role="admin")

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}/password",
        json={"old_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=_cookie(user),
    )

    assert resp.status_code == 200, resp.text
    assert (await _auth_service(db_manager).authenticate_user(user["username"], NEW_PASSWORD)).user_id == user["id"]




@pytest.mark.asyncio
async def test_username_containing_at_is_refused_on_update(api_client, db_manager, community):
    user = await _seed(db_manager)
    target = f"someone_{uuid4().hex[:8]}@example.com"

    resp = await api_client.put(f"/api/v1/users/{user['id']}", json={"username": target}, headers=_cookie(user))

    assert resp.status_code == 400, resp.text
    assert (await _row(db_manager, user)).username == user["username"]


@pytest.mark.asyncio
async def test_existing_username_containing_at_can_be_resubmitted_unchanged(api_client, db_manager, community):
    legacy = f"legacy_{uuid4().hex[:8]}@example.org"
    user = await _seed(db_manager, username=legacy)

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}", json={"username": legacy, "first_name": "Kept"}, headers=_cookie(user)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["first_name"] == "Kept"


@pytest.mark.asyncio
async def test_username_containing_at_is_refused_on_create(db_manager, community):
    from giljo_mcp.services.auth_service import AuthService
    from giljo_mcp.services.user_service import UserService
    from giljo_mcp.tenant import TenantManager

    name = f"new_{uuid4().hex[:8]}@example.com"
    with pytest.raises(ValidationError):
        await UserService(db_manager, TenantManager.generate_tenant_key()).create_user(username=name, password=PASSWORD)
    with pytest.raises(ValidationError):
        await AuthService(db_manager).register_user(name, None, PASSWORD, "developer", str(uuid4()))


@pytest.mark.asyncio
async def test_login_by_email_is_not_shadowed_by_another_tenants_username(db_manager, community):
    victim = await _seed(db_manager)
    await _seed(db_manager, username=victim["email"], email=f"attacker_{uuid4().hex[:8]}@example.com")

    result = await _auth_service(db_manager).authenticate_user(victim["email"], PASSWORD)

    assert result.user_id == victim["id"]


@pytest.mark.asyncio
async def test_control_login_by_username_by_email_and_by_legacy_at_username(db_manager, community):
    service = _auth_service(db_manager)
    user = await _seed(db_manager)
    legacy = await _seed(db_manager, username=f"legacy_{uuid4().hex[:8]}@example.org")

    assert (await service.authenticate_user(user["username"], PASSWORD)).user_id == user["id"]
    assert (await service.authenticate_user(user["email"], PASSWORD)).user_id == user["id"]
    assert (await service.authenticate_user(user["email"].upper(), PASSWORD)).user_id == user["id"]
    assert (await service.authenticate_user(legacy["username"], PASSWORD)).user_id == legacy["id"]




@pytest.mark.asyncio
async def test_case_variant_of_another_tenants_email_is_refused(api_client, db_manager, community):
    victim = await _seed(db_manager)
    attacker = await _seed(db_manager)

    resp = await api_client.put(
        f"/api/v1/users/{attacker['id']}", json={"email": victim["email"].capitalize()}, headers=_cookie(attacker)
    )

    assert resp.status_code == 400, resp.text
    assert (await _auth_service(db_manager).authenticate_user(victim["email"], PASSWORD)).user_id == victim["id"]


@pytest.mark.asyncio
async def test_existing_case_duplicate_rows_do_not_break_the_owners_login(db_manager, community):
    victim = await _seed(db_manager)
    await _seed(db_manager, email=victim["email"].capitalize())

    result = await _auth_service(db_manager).authenticate_user(victim["email"], PASSWORD)

    assert result.user_id == victim["id"]


@pytest.mark.asyncio
async def test_email_is_stored_lower_cased(api_client, db_manager, community):
    user = await _seed(db_manager)
    mixed = f"Mixed_{uuid4().hex[:8]}@Example.com"

    resp = await api_client.put(f"/api/v1/users/{user['id']}", json={"email": mixed}, headers=_cookie(user))

    assert resp.status_code == 200, resp.text
    assert (await _row(db_manager, user)).email == mixed.lower()


@pytest.mark.asyncio
async def test_register_refuses_a_case_variant_of_an_existing_email(db_manager, community):
    from giljo_mcp.services.auth_service import AuthService

    holder = await _seed(db_manager)

    with pytest.raises(ValidationError):
        await AuthService(db_manager).register_user(
            f"new_{uuid4().hex[:8]}", holder["email"].upper(), PASSWORD, "developer", str(uuid4())
        )




async def _username_attempt(api_client, db_manager, *, same_tenant: bool):
    caller = await _seed(db_manager)
    holder = await _seed(db_manager, tenant_key=caller["tenant_key"] if same_tenant else None)
    resp = await api_client.put(
        f"/api/v1/users/{caller['id']}", json={"username": holder["username"]}, headers=_cookie(caller)
    )
    return resp, holder["username"]


async def _email_attempt(api_client, db_manager, *, same_tenant: bool):
    caller = await _seed(db_manager)
    holder = await _seed(db_manager, tenant_key=caller["tenant_key"] if same_tenant else None)
    resp = await api_client.put(
        f"/api/v1/users/{caller['id']}", json={"email": holder["email"]}, headers=_cookie(caller)
    )
    return resp, holder["email"]


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", [_username_attempt, _email_attempt], ids=["username", "email"])
async def test_taken_value_gets_the_same_answer_in_any_tenant(api_client, db_manager, community, attempt):
    same, same_value = await attempt(api_client, db_manager, same_tenant=True)
    other, other_value = await attempt(api_client, db_manager, same_tenant=False)

    assert same.status_code == 400, same.text
    assert other.status_code == same.status_code, other.text
    assert _refusal(other, other_value) == _refusal(same, same_value)


@pytest.mark.asyncio
async def test_org_slug_held_by_another_tenant_gets_the_same_answer(api_client, db_manager, community):
    caller = await _seed(db_manager)
    neighbour = await _seed(db_manager, tenant_key=caller["tenant_key"])
    stranger = await _seed(db_manager)
    slugs = {}
    for key, owner in (("same", neighbour), ("other", stranger)):
        slugs[key] = f"sec0050-slug-{uuid4().hex[:8]}"
        created = await api_client.post(
            "/api/organizations", json={"name": "Held", "slug": slugs[key]}, headers=_cookie(owner)
        )
        assert created.status_code == 201, created.text

    same = await api_client.post(
        "/api/organizations", json={"name": "Mine", "slug": slugs["same"]}, headers=_cookie(caller)
    )
    other = await api_client.post(
        "/api/organizations", json={"name": "Mine", "slug": slugs["other"]}, headers=_cookie(caller)
    )

    assert same.status_code == 409, same.text
    assert other.status_code == same.status_code, other.text
    assert _refusal(other, slugs["other"]) == _refusal(same, slugs["same"])
