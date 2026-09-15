# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from giljo_mcp.auth.dependencies import get_current_user, get_current_user_optional
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.services.oauth_revocation_service import (
    clear_revocation_cache,
    revoke_dashboard_access_jwt,
)


async def _seed_user(db_manager):
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    user_id = str(uuid4())
    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"JWT Revoke Org {uuid4().hex[:6]}",
            slug=f"jwt-revoke-{uuid4().hex[:8]}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"revoke_user_{uuid4().hex[:8]}",
                email=f"revoke_{uuid4().hex[:8]}@example.com",
                role="developer",
                tenant_key=tenant_key,
                is_active=True,
                org_id=org.id,
            )
        )
        await session.commit()
    return tenant_key, user_id


def _mint(tenant_key: str, user_id: str) -> str:
    return JWTManager.create_access_token(
        user_id=UUID(user_id),
        username="revoke_user",
        role="developer",
        tenant_key=tenant_key,
    )


def _cookie_request() -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path="/api/projects"))


@pytest.mark.asyncio
async def test_valid_token_authenticates_before_revocation(db_manager):
    clear_revocation_cache()
    tenant_key, user_id = await _seed_user(db_manager)
    token = _mint(tenant_key, user_id)

    async with db_manager.get_session_async() as db:
        user = await get_current_user(
            request=_cookie_request(),
            access_token=token,
            x_api_key=None,
            authorization=None,
            db=db,
        )
    assert str(user.id) == user_id
    clear_revocation_cache()


@pytest.mark.asyncio
async def test_revoked_cookie_token_is_rejected(db_manager):
    clear_revocation_cache()
    tenant_key, user_id = await _seed_user(db_manager)
    token = _mint(tenant_key, user_id)

    async with db_manager.get_session_async() as db:
        revoked = await revoke_dashboard_access_jwt(db, token=token)
        await db.commit()
    assert revoked is True

    clear_revocation_cache()

    async with db_manager.get_session_async() as db:
        with pytest.raises(Exception) as exc:
            await get_current_user(
                request=_cookie_request(),
                access_token=token,
                x_api_key=None,
                authorization=None,
                db=db,
            )
    assert getattr(exc.value, "status_code", None) == 401
    clear_revocation_cache()


@pytest.mark.asyncio
async def test_revoked_bearer_token_is_rejected(db_manager):
    clear_revocation_cache()
    tenant_key, user_id = await _seed_user(db_manager)
    token = _mint(tenant_key, user_id)

    async with db_manager.get_session_async() as db:
        await revoke_dashboard_access_jwt(db, token=token)
        await db.commit()

    clear_revocation_cache()

    async with db_manager.get_session_async() as db:
        with pytest.raises(Exception) as exc:
            await get_current_user(
                request=_cookie_request(),
                access_token=None,
                x_api_key=None,
                authorization=f"Bearer {token}",
                db=db,
            )
    assert getattr(exc.value, "status_code", None) == 401
    clear_revocation_cache()


@pytest.mark.asyncio
async def test_optional_variant_returns_none_for_revoked_token(db_manager):
    clear_revocation_cache()
    tenant_key, user_id = await _seed_user(db_manager)
    token = _mint(tenant_key, user_id)

    async with db_manager.get_session_async() as db:
        await revoke_dashboard_access_jwt(db, token=token)
        await db.commit()

    clear_revocation_cache()

    async with db_manager.get_session_async() as db:
        result = await get_current_user_optional(
            request=_cookie_request(),
            access_token=token,
            x_api_key=None,
            authorization=None,
            db=db,
        )
    assert result is None
    clear_revocation_cache()


@pytest.mark.asyncio
async def test_tenant_isolation_revocation_does_not_cross_tenants(db_manager):
    clear_revocation_cache()
    tenant_a, user_a = await _seed_user(db_manager)
    tenant_b, user_b = await _seed_user(db_manager)
    token_a = _mint(tenant_a, user_a)
    token_b = _mint(tenant_b, user_b)

    async with db_manager.get_session_async() as db:
        await revoke_dashboard_access_jwt(db, token=token_a)
        await db.commit()

    clear_revocation_cache()

    async with db_manager.get_session_async() as db:
        user = await get_current_user(
            request=_cookie_request(),
            access_token=token_b,
            x_api_key=None,
            authorization=None,
            db=db,
        )
    assert str(user.id) == user_b
    clear_revocation_cache()
