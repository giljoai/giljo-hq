# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime

import bcrypt
import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.exceptions import AuthorizationError
from giljo_mcp.models import Task  # noqa: F401 - For FK cleanup
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization, OrgMembership
from giljo_mcp.schemas.service_responses import UserInfo
from giljo_mcp.services.auth_service import AuthService




@pytest_asyncio.fixture
async def auth_service(db_manager, db_session):
    return AuthService(
        db_manager=db_manager,
        websocket_manager=None,
        session=db_session,
    )


@pytest_asyncio.fixture
async def test_org(db_session):
    org = Organization(
        id="test-org-001",
        name="Test Organization",
        slug="test-organization",
        tenant_key="test_tenant_001",
        is_active=True,
        settings={},
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def test_admin_user(db_session, test_org):
    password = "Admin1234!@#$"
    admin = User(
        id="test-admin-001",
        username="testadmin",
        email="admin@example.com",
        full_name="Test Admin",
        password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        role="admin",
        tenant_key="test_tenant_001",
        org_id=test_org.id,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(admin)
    await db_session.flush()

    owner_membership = OrgMembership(
        org_id=test_org.id,
        user_id=admin.id,
        role="owner",
        tenant_key="test_tenant_001",
        is_active=True,
    )
    db_session.add(owner_membership)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin, password


@pytest_asyncio.fixture
async def test_member_user(db_session, test_org):
    password = "Member1234!@#$"
    member = User(
        id="test-member-001",
        username="testmember",
        email="member@example.com",
        full_name="Test Member",
        password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key="test_tenant_002",
        org_id=test_org.id,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(member)
    await db_session.flush()

    member_membership = OrgMembership(
        org_id=test_org.id,
        user_id=member.id,
        role="member",
        tenant_key="test_tenant_001",
        is_active=True,
    )
    db_session.add(member_membership)
    await db_session.commit()
    await db_session.refresh(member)
    return member, password




@pytest.mark.asyncio
async def test_create_default_organization_returns_org_id(auth_service, db_session):
    org_id = await auth_service._create_default_organization(
        session=db_session, tenant_key="test_tenant_999", org_name="Custom Workspace"
    )

    assert isinstance(org_id, str)
    assert len(org_id) == 36

    stmt = select(Organization).where(Organization.id == org_id)
    result = await db_session.execute(stmt)
    org = result.scalar_one_or_none()

    assert org is not None
    assert org.name == "Custom Workspace"
    assert org.is_active is True

    membership_stmt = select(OrgMembership).where(OrgMembership.org_id == org_id)
    membership_result = await db_session.execute(membership_stmt)
    membership = membership_result.scalar_one_or_none()

    assert membership is None


@pytest.mark.asyncio
async def test_register_user_sets_org_id(auth_service, db_session, test_admin_user, test_org):
    admin, _ = test_admin_user

    result = await auth_service._register_user_impl(
        session=db_session,
        username="newuser",
        email="newuser@example.com",
        password="NewUser1234!@#$",
        role="developer",
        requesting_admin_id=admin.id,
        org_id=test_org.id,
        org_role="member",
    )

    assert isinstance(result, UserInfo)
    user_id = result.id
    stmt = select(User).where(User.id == user_id)
    user_result = await db_session.execute(stmt)
    user = user_result.scalar_one()

    assert user.org_id == test_org.id

    membership_stmt = (
        select(OrgMembership).where(OrgMembership.org_id == test_org.id).where(OrgMembership.user_id == user.id)
    )
    membership_result = await db_session.execute(membership_stmt)
    membership = membership_result.scalar_one()

    assert membership.role == "member"
    assert membership.is_active is True


@pytest.mark.asyncio
async def test_create_user_in_org_by_admin(auth_service, db_session, test_admin_user, test_org):
    admin, _ = test_admin_user

    result = await auth_service.create_user_in_org(
        session=db_session,
        admin_user_id=admin.id,
        username="orguser",
        email="orguser@example.com",
        role="member",
        initial_password="OrgUser1234!@#$",
    )

    assert isinstance(result, UserInfo)
    assert result.username == "orguser"
    assert result.email == "orguser@example.com"

    user_id = result.id
    stmt = select(User).where(User.id == user_id)
    user_result = await db_session.execute(stmt)
    user = user_result.scalar_one()

    assert user.org_id == test_org.id

    membership_stmt = (
        select(OrgMembership).where(OrgMembership.org_id == test_org.id).where(OrgMembership.user_id == user.id)
    )
    membership_result = await db_session.execute(membership_stmt)
    membership = membership_result.scalar_one()

    assert membership.role == "member"
    assert membership.is_active is True


@pytest.mark.asyncio
async def test_create_user_in_org_requires_admin_role(auth_service, db_session, test_member_user, test_org):
    member, _ = test_member_user

    with pytest.raises(AuthorizationError) as exc_info:
        await auth_service.create_user_in_org(
            session=db_session,
            admin_user_id=member.id,
            username="unauthorizeduser",
            email="unauthorized@example.com",
            role="member",
            initial_password="Unauthorized1234!@#$",
        )

    assert "owner" in str(exc_info.value).lower() or "admin" in str(exc_info.value).lower()

    stmt = select(User).where(User.username == "unauthorizeduser")
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()

    assert user is None
