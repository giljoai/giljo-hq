# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

import secrets
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.exceptions import ValidationError


_CSRF = secrets.token_urlsafe(32)


async def _seed_user(db_manager, *, with_password: bool) -> dict:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"sec0048_{unique}"
    password_hash = bcrypt.hashpw(b"Password1!", bcrypt.gensalt()).decode() if with_password else None
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(name=f"SEC0048 {unique}", slug=f"sec0048-{unique}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"{username}@example.com",
                password_hash=password_hash,
                tenant_key=tenant_key,
                role="admin",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()
    return {"id": user_id, "username": username, "tenant_key": tenant_key, "email": f"{username}@example.com"}


def _browser_headers(user: dict) -> dict:
    token = JWTManager.create_access_token(
        user_id=user["id"], username=user["username"], role="admin", tenant_key=user["tenant_key"], revocation_epoch=0
    )
    return {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


async def _stored_email(db_manager, user: dict) -> str | None:
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async(tenant_key=user["tenant_key"]) as session:
        return (
            await session.execute(
                select(User.email).where(User.id == user["id"], User.tenant_key == user["tenant_key"])
            )
        ).scalar_one()


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setenv("GILJO_MODE", "saas")


@pytest.fixture
def community(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setenv("GILJO_MODE", "ce")




@pytest.mark.asyncio
@pytest.mark.parametrize("with_password", [False, True], ids=["social_only", "password"])
async def test_hosted_generic_route_refuses_a_new_email_and_leaves_the_row(
    api_client, db_manager, hosted, with_password
):
    user = await _seed_user(db_manager, with_password=with_password)
    target = f"victim_{uuid4().hex[:8]}@example.com"

    resp = await api_client.put(f"/api/v1/users/{user['id']}", json={"email": target}, headers=_browser_headers(user))

    assert resp.status_code == 400, resp.text
    assert "verif" in resp.text.lower()
    assert target not in resp.text
    assert await _stored_email(db_manager, user) == user["email"]


@pytest.mark.asyncio
async def test_hosted_refusal_is_identical_whether_or_not_another_account_holds_the_address(
    api_client, db_manager, hosted
):
    user = await _seed_user(db_manager, with_password=True)
    holder = await _seed_user(db_manager, with_password=True)
    unused = f"nobody_{uuid4().hex[:8]}@example.com"
    headers = _browser_headers(user)

    taken = await api_client.put(f"/api/v1/users/{user['id']}", json={"email": holder["email"]}, headers=headers)
    free = await api_client.put(f"/api/v1/users/{user['id']}", json={"email": unused}, headers=headers)

    assert taken.status_code == free.status_code == 400
    assert taken.json()["message"] == free.json()["message"]
    assert "exist" not in taken.json()["message"].lower()


@pytest.mark.asyncio
async def test_hosted_generic_route_still_saves_when_the_email_is_unchanged(api_client, db_manager, hosted):
    user = await _seed_user(db_manager, with_password=True)

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}",
        json={"email": user["email"], "first_name": "Grace"},
        headers=_browser_headers(user),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["first_name"] == "Grace"




@pytest.mark.asyncio
async def test_hosted_user_service_refuses_an_unproven_email_write(db_manager, hosted):
    from giljo_mcp.services import UserService

    user = await _seed_user(db_manager, with_password=False)
    service = UserService(db_manager=db_manager, tenant_key=user["tenant_key"])

    with pytest.raises(ValidationError):
        await service.update_user(user["id"], email=f"victim_{uuid4().hex[:8]}@example.com")

    assert await _stored_email(db_manager, user) == user["email"]


@pytest.mark.asyncio
async def test_hosted_verified_flow_writer_still_changes_the_email(db_manager, hosted):
    from giljo_mcp.services import UserService

    user = await _seed_user(db_manager, with_password=False)
    proven = f"proven_{uuid4().hex[:8]}@example.com"
    service = UserService(db_manager=db_manager, tenant_key=user["tenant_key"])

    updated = await service.apply_verified_email(user["id"], proven)

    assert updated.email == proven
    assert await _stored_email(db_manager, user) == proven




@pytest.mark.asyncio
async def test_ce_generic_route_still_updates_the_email(api_client, db_manager, community):
    user = await _seed_user(db_manager, with_password=True)
    new_email = f"ce_{uuid4().hex[:8]}@example.com"

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}", json={"email": new_email}, headers=_browser_headers(user)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == new_email
    assert await _stored_email(db_manager, user) == new_email
