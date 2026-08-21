# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
API tests for auth endpoints with organization integration (Handover 0424h).

Tests:
- POST /auth/create-first-admin accepts workspace_name parameter
- POST /auth/create-first-admin defaults workspace_name to "My Organization"
- GET /auth/me returns org_id, org_name, org_role fields

Test Strategy (TDD):
1. Write tests that expect org integration (RED phase)
2. Update endpoints to pass tests (GREEN phase)
3. Verify all tests pass (REFACTOR phase)

Updated for exception-based patterns (Handover 0480 series).

CE-only: in saas mode the endpoint is intentionally rejected with 403
(admin bootstrap is CLI-only). The SaaS-side behavior is covered by
tests/saas/test_auth_create_first_admin_mode_gate.py.
"""

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio


def _gil_mode() -> str:
    """Resolve GILJO_MODE the same way app.py does: env var first, else .env at repo root."""
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
    """
    Provides a fresh database session for tests that need isolated user creation.

    Instead of deleting all users (which violates FK constraints), we:
    1. Create a unique test user for each test
    2. Use unique identifiers to avoid collisions
    """
    async with db_manager.get_session_async() as session:
        yield session


@pytest_asyncio.fixture
async def authed_client_for_first_admin(db_manager, api_client):
    """
    Provides an API client that simulates a fresh installation.

    Since we can't delete all users due to FK constraints, we test the
    create-first-admin endpoint behavior by checking it works when no
    admin exists, or returns appropriate error when admin exists.
    """
    yield api_client


async def _global_user_count(db_manager) -> int:
    """Users across every tenant, read NOW (INF-9417).

    ``create-first-admin`` refuses whenever ANY user exists, so this is the
    endpoint's own precondition. It is deliberately read AFTER the response and
    never before: read beforehand it is a prediction, and the suite runs under
    ``pytest-xdist`` where a peer can both create users and -- via the BE-9238
    teardown -- delete them, so a pre-read is stale in both directions.
    """
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
    """
    Test that POST /auth/create-first-admin accepts workspace_name parameter.

    Expected behavior:
    - Accept workspace_name in request body
    - Create organization with provided workspace_name
    - User's org should match workspace_name

    NOTE: This test uses unique credentials to avoid conflicts.
    If first admin already exists, endpoint returns 400 (expected behavior).

    INF-9417: the branch is chosen by the RESPONSE, never by a user count read
    beforehand. The old shape read ``count(*) FROM users``, POSTed, and then
    asserted 201-or-400 on that now-stale number -- so any concurrent writer
    decided the outcome while the test still believed the old one. The count is
    not even monotonic: ``tests/conftest.py``'s BE-9238 teardown DELETEs the
    tenants a peer minted, so it moves in both directions. Each branch is now
    checked against the state at the time of the response instead.
    """
    unique_suffix = str(uuid4())[:8]
    request_body = {
        "username": f"admin_{unique_suffix}",
        "password": "SecureAdmin123!@#",
        "email": f"admin_{unique_suffix}@example.com",
        "full_name": "Administrator",
        "workspace_name": f"Acme Corporation {unique_suffix}",
    }

    # Act
    response = await api_client.post("/api/auth/create-first-admin", json=request_body)

    # Assert: whichever branch the endpoint took must be correct ON ITS OWN TERMS.
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

    # Verify organization was created with correct name
    from sqlalchemy import select

    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = data["tenant_key"]
        user_stmt = select(User).where(User.username == f"admin_{unique_suffix}")
        user_result = await session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        # Unconditional: the endpoint reported 201, so the row is there. The old
        # `if user:` made every assertion below optional, so the test could pass
        # having checked nothing at all.
        assert user is not None, "endpoint returned 201, so the admin row must exist"
        assert user.org_id is not None, "User should have org_id set"

        org_stmt = select(Organization).where(Organization.id == user.org_id)
        org_result = await session.execute(org_stmt)
        org = org_result.scalar_one()

        assert org.name == f"Acme Corporation {unique_suffix}", f"Expected org name, got '{org.name}'"


@_skip_in_saas
@pytest.mark.asyncio
async def test_create_first_admin_defaults_workspace_name(api_client, db_manager):
    """
    Test that POST /auth/create-first-admin defaults workspace_name to "My Organization".

    Expected behavior:
    - If workspace_name not provided, use "My Organization" as default
    - Organization created with default name

    NOTE: This test uses unique credentials to avoid conflicts.

    INF-9417: branch on the RESPONSE, not on a stale pre-read of the user count.
    See ``test_create_first_admin_accepts_workspace_name`` for the full reasoning.
    """
    unique_suffix = str(uuid4())[:8]
    request_body = {
        "username": f"admin_default_{unique_suffix}",
        "password": "SecureAdmin123!@#",
        "email": f"admin_default_{unique_suffix}@example.com",
        "full_name": "Administrator",
        # workspace_name intentionally omitted
    }

    # Act
    response = await api_client.post("/api/auth/create-first-admin", json=request_body)

    # Assert: whichever branch the endpoint took must be correct ON ITS OWN TERMS.
    if response.status_code == 400:
        assert await _global_user_count(db_manager) > 0, (
            "the endpoint refused because users already exist, so users must exist -- "
            "a refusal against an empty users table is a real failure, not a race"
        )
        return

    assert response.status_code == 201, f"Expected 201 or 400, got {response.status_code}: {response.text}"

    data = response.json()
    assert data["username"] == f"admin_default_{unique_suffix}"

    # Verify organization was created with default name
    from sqlalchemy import select

    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = data["tenant_key"]
        user_stmt = select(User).where(User.username == f"admin_default_{unique_suffix}")
        user_result = await session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        # Unconditional, for the same reason as its sibling: `if user:` made the
        # org-name assertion -- the only thing this test exists to check -- optional.
        assert user is not None, "endpoint returned 201, so the admin row must exist"

        org_stmt = select(Organization).where(Organization.id == user.org_id)
        org_result = await session.execute(org_stmt)
        org = org_result.scalar_one()

        assert org.name == "My Organization", f"Expected 'My Organization', got '{org.name}'"


@pytest.mark.asyncio
async def test_auth_me_returns_org_data(api_client, db_manager, auth_headers):
    """
    Test that GET /auth/me returns org_id, org_name, org_role for user with org.

    Expected behavior:
    - Return org_id field
    - Return org_name field
    - Return org_role field from membership

    Uses auth_headers fixture which creates a properly authenticated user with org.
    """
    # Act - use authenticated client
    response = await api_client.get("/api/auth/me", headers=auth_headers)

    # Assert
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert "org_id" in data, "Response should include org_id field"
    assert "org_name" in data, "Response should include org_name field"
    assert "org_role" in data, "Response should include org_role field"

    assert data["org_id"] is not None, "User should have org_id"
    # org_name and org_role should be present (values depend on fixture setup)
    assert data["org_name"] is not None, "org_name should not be null"


@pytest.mark.asyncio
async def test_auth_me_returns_org_fields(api_client, db_manager, auth_headers):
    """
    Test that GET /auth/me always returns org fields (post-0424j).

    After 0424j migration:
    - All users MUST have org_id (NOT NULL)
    - org_name and org_role should always be present
    - No null org scenarios possible

    This test verifies the API returns org fields for authenticated user.
    """
    # Act
    response = await api_client.get("/api/auth/me", headers=auth_headers)

    # Assert
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert "org_id" in data, "Response should include org_id field"
    assert "org_name" in data, "Response should include org_name field"
    assert "org_role" in data, "Response should include org_role field"

    # Post-0424j: All users MUST have org
    assert data["org_id"] is not None, "org_id should never be null after 0424j migration"
    assert data["org_name"] is not None, "org_name should never be null"
    # org_role can vary based on membership but should be present
    assert "org_role" in data, "org_role field should be present"


# ---------------------------------------------------------------------------
# IMP-5037a NB-1: live revoke endpoint resolves the open expiry notification
#
# Regression at the FAILING layer. The auto-clear hook lives in
# AuthService.revoke_api_key(notification_service=...), but the live DELETE
# endpoint previously invoked it WITHOUT a notification_service, so a user who
# revoked an expiring key kept a stale api_key.expiring_soon bell notification
# forever (the hourly scan only creates, never resolves). The fix injects
# get_notification_service into the endpoint. This test exercises the endpoint
# through real FastAPI DI (not a service stub), per the failing-layer rule.
#
# Isolation is by unique tenant_key (the proven tests/api pattern), not
# transaction rollback: the ASGI app opens its own pooled connection that a
# single TransactionalTestContext transaction cannot wrap (see
# tests/api/test_be6004c_taxonomy_types_tenant_scope.py).
# ---------------------------------------------------------------------------


async def _seed_user_key_and_open_notification(db_manager) -> dict:
    """Create org + user + active API key + an OPEN api_key.expiring_soon
    notification for that key, all in a fresh tenant. Returns auth headers,
    the key id, the notification id, and the tenant_key."""
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
    """IMP-5037a NB-1: DELETE /api/auth/api-keys/{id} sets resolved_at on the
    key's open api_key.expiring_soon notification via the live path.

    Before the fix the endpoint called AuthService.revoke_api_key without a
    notification_service, so the auto-clear hook was a no-op and resolved_at
    stayed NULL.
    """
    from sqlalchemy import select

    from giljo_mcp.models.notifications import Notification

    seeded = await _seed_user_key_and_open_notification(db_manager)

    # Precondition: notification is OPEN (resolved_at IS NULL).
    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = seeded["tenant_key"]
        before = (
            await session.execute(select(Notification).where(Notification.id == seeded["notification_id"]))
        ).scalar_one()
        assert before.resolved_at is None, "precondition: notification must start open"

    resp = await api_client.delete(f"/api/auth/api-keys/{seeded['key_id']}", headers=seeded["headers"])
    assert resp.status_code == 200, resp.text

    # The live endpoint must have resolved the open expiry notification.
    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = seeded["tenant_key"]
        after = (
            await session.execute(select(Notification).where(Notification.id == seeded["notification_id"]))
        ).scalar_one()
        assert after.resolved_at is not None, (
            "revoke endpoint must resolve the key's api_key.expiring_soon notification"
        )
