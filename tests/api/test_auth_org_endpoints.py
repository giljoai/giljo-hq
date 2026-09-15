# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio


def _gil_mode() -> str:
    val = os.environ.get("GILJO_MODE")
    if val:
        return val.lower()
    try:
        env_path = str(Path(__file__).resolve().parent.parent.parent / ".env")
        with open(env_path) as f:
            for line in f:
                if line.startswith("GILJO_MODE="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'").lower()
    except OSError:
        pass
    return ""


_skip_in_saas = pytest.mark.skipif(
    _gil_mode() == "saas",
    reason="endpoint refuses public admin bootstrap in saas; SaaS path tested in tests/saas/",
)


@pytest_asyncio.fixture
async def fresh_db_session(db_manager):
    async with db_manager.get_session_async() as session:
        yield session


@pytest_asyncio.fixture
async def authed_client_for_first_admin(db_manager, api_client):
    yield api_client


async def _global_user_count(db_manager) -> int:
    from sqlalchemy import func, select

    from giljo_mcp.database import tenant_isolation_bypass
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session,
            reason="first-admin tests assert on the endpoint's global user-count precondition",
            models=(User,),
        ):
            result = await session.execute(select(func.count()).select_from(User))
        return result.scalar()


@_skip_in_saas
@pytest.mark.asyncio
async def test_create_first_admin_accepts_workspace_name(api_client, db_manager):
    unique_suffix = str(uuid4())[:8]
    request_body = {
        "username": f"admin_{unique_suffix}",
        "password": "SecureAdmin123!@#",
        "email": f"admin_{unique_suffix}@example.com",
        "full_name": "Administrator",
        "workspace_name": f"Acme Corporation {unique_suffix}",
    }

    response = await api_client.post("/api/auth/create-first-admin", json=request_body)

    if response.status_code == 400:
        assert "already exists" in response.text.lower() or "already created" in response.text.lower()
        assert await _global_user_count(db_manager) > 0, (
            "the endpoint refused because users already exist, so users must exist -- "
            "a refusal against an empty users table is a real failure, not a race"
        )
        return

    assert response.status_code == 201, f"Expected 201 or 400, got {response.status_code}: {response.text}"

    data = response.json()
    assert data["username"] == f"admin_{unique_suffix}"
    assert data["role"] == "admin"
    assert data["tenant_key"].startswith("tk_")

    from sqlalchemy import select

    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = data["tenant_key"]
        user_stmt = select(User).where(User.username == f"admin_{unique_suffix}")
        user_result = await session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        assert user is not None, "endpoint returned 201, so the admin row must exist"
        assert user.org_id is not None, "User should have org_id set"

        org_stmt = select(Organization).where(Organization.id == user.org_id)
        org_result = await session.execute(org_stmt)
        org = org_result.scalar_one()

        assert org.name == f"Acme Corporation {unique_suffix}", f"Expected org name, got '{org.name}'"


@_skip_in_saas
@pytest.mark.asyncio
async def test_create_first_admin_defaults_workspace_name(api_client, db_manager):
    unique_suffix = str(uuid4())[:8]
    request_body = {
        "username": f"admin_default_{unique_suffix}",
        "password": "SecureAdmin123!@#",
        "email": f"admin_default_{unique_suffix}@example.com",
        "full_name": "Administrator",
    }

    response = await api_client.post("/api/auth/create-first-admin", json=request_body)

    if response.status_code == 400:
        assert await _global_user_count(db_manager) > 0, (
            "the endpoint refused because users already exist, so users must exist -- "
            "a refusal against an empty users table is a real failure, not a race"
        )
        return

    assert response.status_code == 201, f"Expected 201 or 400, got {response.status_code}: {response.text}"

    data = response.json()
    assert data["username"] == f"admin_default_{unique_suffix}"

    from sqlalchemy import select

    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = data["tenant_key"]
        user_stmt = select(User).where(User.username == f"admin_default_{unique_suffix}")
        user_result = await session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        assert user is not None, "endpoint returned 201, so the admin row must exist"

        org_stmt = select(Organization).where(Organization.id == user.org_id)
        org_result = await session.execute(org_stmt)
        org = org_result.scalar_one()

        assert org.name == "My Organization", f"Expected 'My Organization', got '{org.name}'"


@pytest.mark.asyncio
async def test_auth_me_returns_org_data(api_client, db_manager, auth_headers):
    response = await api_client.get("/api/auth/me", headers=auth_headers)

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert "org_id" in data, "Response should include org_id field"
    assert "org_name" in data, "Response should include org_name field"
    assert "org_role" in data, "Response should include org_role field"

    assert data["org_id"] is not None, "User should have org_id"
    assert data["org_name"] is not None, "org_name should not be null"


@pytest.mark.asyncio
async def test_auth_me_returns_org_fields(api_client, db_manager, auth_headers):
    response = await api_client.get("/api/auth/me", headers=auth_headers)

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert "org_id" in data, "Response should include org_id field"
    assert "org_name" in data, "Response should include org_name field"
    assert "org_role" in data, "Response should include org_role field"

    assert data["org_id"] is not None, "org_id should never be null after 0424j migration"
    assert data["org_name"] is not None, "org_name should never be null"
    assert "org_role" in data, "org_role field should be present"




async def _seed_user_key_and_open_notification(db_manager) -> dict:
    import secrets

    import bcrypt

    from giljo_mcp.auth.jwt_manager import JWTManager
    from giljo_mcp.models import User
    from giljo_mcp.models.auth import APIKey
    from giljo_mcp.models.notifications import Notification
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    csrf_token = secrets.token_urlsafe(32)

    async with db_manager.get_session_async() as session:
        suffix = uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(
            name=f"Org {suffix}",
            slug=f"org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        api_key = APIKey(
            id=str(uuid4()),
            tenant_key=tenant_key,
            user_id=user.id,
            name=f"Expiring Key {suffix}",
            key_hash=bcrypt.hashpw(f"gk_{suffix}".encode(), bcrypt.gensalt()).decode("utf-8"),
            key_prefix=f"gk_{suffix[:6]}",
            permissions=["*"],
            is_active=True,
        )
        session.add(api_key)
        await session.flush()

        notification = Notification(
            id=str(uuid4()),
            tenant_key=tenant_key,
            user_id=user.id,
            type="api_key.expiring_soon",
            severity="warning",
            title="API key expiring soon",
            body=f"Key {api_key.name} expires soon",
            payload={"api_key_id": api_key.id, "api_key_name": api_key.name, "expires_at": None},
            dedupe_key=f"api_key.expiring_soon:{api_key.id}",
        )
        session.add(notification)
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        return {
            "tenant_key": tenant_key,
            "key_id": api_key.id,
            "notification_id": notification.id,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={csrf_token}",
                "X-CSRF-Token": csrf_token,
            },
        }


@pytest.mark.asyncio
async def test_revoke_api_key_endpoint_resolves_expiry_notification(api_client, db_manager):
    from sqlalchemy import select

    from giljo_mcp.models.notifications import Notification

    seeded = await _seed_user_key_and_open_notification(db_manager)

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = seeded["tenant_key"]
        before = (
            await session.execute(select(Notification).where(Notification.id == seeded["notification_id"]))
        ).scalar_one()
        assert before.resolved_at is None, "precondition: notification must start open"

    resp = await api_client.delete(f"/api/auth/api-keys/{seeded['key_id']}", headers=seeded["headers"])
    assert resp.status_code == 200, resp.text

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = seeded["tenant_key"]
        after = (
            await session.execute(select(Notification).where(Notification.id == seeded["notification_id"]))
        ).scalar_one()
        assert after.resolved_at is not None, (
            "revoke endpoint must resolve the key's api_key.expiring_soon notification"
        )
