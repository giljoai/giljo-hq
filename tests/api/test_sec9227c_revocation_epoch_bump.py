# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.auth.principal import AuthErrorReason, PrincipalValidationError, validate_principal
from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthRefreshToken
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services import oauth_refresh_service as _refresh
from giljo_mcp.services.oauth_refresh_service import (
    bump_epoch_if_revoked,
    hash_authorization_code,
    hash_refresh_token,
    lock_user_for_update,
    new_family_id,
    revoke_families_for_code,
)
from giljo_mcp.services.oauth_revocation_service import revoke_token
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService
from giljo_mcp.tenant import TenantManager


_MCP_AUD = "https://mcp.giljo.test/resource"


async def _seed_user(db_manager) -> tuple[str, str, str]:
    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"sec9227c_user_{unique}"
    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"SEC9227c Org {unique}", slug=f"sec9227c-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"sec9227c_{unique}@example.com",
                role="developer",
                tenant_key=tk,
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()
    return user_id, username, tk


async def _insert_refresh_row(
    db_manager, *, tenant_key: str, user_id: str, revoked: bool = False, origin_code_hash: str | None = None
) -> str:
    raw = secrets.token_urlsafe(64)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            OAuthRefreshToken(
                token_hash=hash_refresh_token(raw),
                family_id=new_family_id(),
                client_id=BUILTIN_CLIENT_ID,
                tenant_key=tenant_key,
                user_id=user_id,
                scope="mcp:read mcp:write",
                aud=_MCP_AUD,
                expires_at=datetime.now(UTC) + timedelta(days=30),
                revoked=revoked,
                origin_code_hash=origin_code_hash,
            )
        )
        await session.commit()
    return raw


def _mint_access_jwt(*, user_id: str, username: str, tenant_key: str, epoch: int) -> str:
    return JWTManager.create_access_token(
        user_id=UUID(user_id),
        username=username,
        role="developer",
        tenant_key=tenant_key,
        audience=_MCP_AUD,
        scope="mcp:read mcp:write",
        revocation_epoch=epoch,
    )


async def _current_epoch(db_manager, *, tenant_key: str, user_id: str) -> int:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        user = (
            await session.execute(select(User).where(User.id == user_id, User.tenant_key == tenant_key))
        ).scalar_one()
        return int(user.token_revocation_epoch or 0)


@pytest.mark.asyncio
async def test_revoke_refresh_token_rejects_prior_access_jwt_at_mcp_boundary(db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)
    raw_refresh = await _insert_refresh_row(db_manager, tenant_key=tk, user_id=user_id)

    access_jwt = _mint_access_jwt(user_id=user_id, username=username, tenant_key=tk, epoch=0)

    async with db_manager.get_session_async(tenant_key=tk) as s1:
        principal = await validate_principal(s1, jwt_token=access_jwt, expected_audience=_MCP_AUD)
        assert principal.user_id == user_id

    async with db_manager.get_session_async(tenant_key=tk) as s2:
        await revoke_token(s2, token=raw_refresh, token_type_hint="refresh_token")
        await s2.commit()
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1

    async with db_manager.get_session_async(tenant_key=tk) as s3:
        with pytest.raises(PrincipalValidationError) as exc:
            await validate_principal(s3, jwt_token=access_jwt, expected_audience=_MCP_AUD)
        assert exc.value.reason == AuthErrorReason.REVOKED


@pytest.mark.asyncio
async def test_code_reuse_revocation_bumps_epoch(db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, _username, tk = await _seed_user(db_manager)
    code = secrets.token_urlsafe(64)
    await _insert_refresh_row(
        db_manager, tenant_key=tk, user_id=user_id, origin_code_hash=hash_authorization_code(code)
    )

    async with db_manager.get_session_async(tenant_key=tk) as session:
        revoked = await revoke_families_for_code(session, code=code, tenant_key=tk)
    assert revoked == 1
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1


async def _seed_family(db_manager, *, tenant_key: str, user_id: str, rows: list[bool]) -> list[str]:
    family_id = new_family_id()
    raws: list[str] = []
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        for revoked in rows:
            raw = secrets.token_urlsafe(64)
            raws.append(raw)
            session.add(
                OAuthRefreshToken(
                    token_hash=hash_refresh_token(raw),
                    family_id=family_id,
                    client_id=BUILTIN_CLIENT_ID,
                    tenant_key=tenant_key,
                    user_id=user_id,
                    scope="mcp:read mcp:write",
                    aud=_MCP_AUD,
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                    revoked=revoked,
                )
            )
        await session.commit()
    return raws


@pytest.mark.asyncio
async def test_refresh_reuse_detection_bumps_epoch(db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)

    user_id, _username, tk = await _seed_user(db_manager)
    raw_revoked, _raw_live = await _seed_family(db_manager, tenant_key=tk, user_id=user_id, rows=[True, False])

    async with db_manager.get_session_async(tenant_key=tk) as session:
        service = OAuthService(db_session=session)
        with pytest.raises(ValueError, match="reuse detected"):
            await _refresh.refresh_token_grant(
                service,
                refresh_token=raw_revoked,
                client_id=BUILTIN_CLIENT_ID,
                client_secret=None,
                access_token_lifetime_seconds=3600,
                refresh_token_lifetime_seconds=30 * 86400,
            )
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1


@pytest.mark.asyncio
async def test_reuse_of_already_dead_family_does_not_rebump_epoch(db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)

    user_id, _username, tk = await _seed_user(db_manager)
    (raw_dead,) = await _seed_family(db_manager, tenant_key=tk, user_id=user_id, rows=[True])
    async with db_manager.get_session_async(tenant_key=tk) as session:
        user = (await session.execute(select(User).where(User.id == user_id, User.tenant_key == tk))).scalar_one()
        user.token_revocation_epoch = 1
        await session.commit()

    async with db_manager.get_session_async(tenant_key=tk) as session:
        service = OAuthService(db_session=session)
        with pytest.raises(ValueError, match="reuse detected"):
            await _refresh.refresh_token_grant(
                service,
                refresh_token=raw_dead,
                client_id=BUILTIN_CLIENT_ID,
                client_secret=None,
                access_token_lifetime_seconds=3600,
                refresh_token_lifetime_seconds=30 * 86400,
            )
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1


@pytest.mark.asyncio
async def test_lock_and_gated_bump_helpers(db_manager):
    user_id, _username, tk = await _seed_user(db_manager)

    async with db_manager.get_session_async(tenant_key=tk) as session:
        user = await lock_user_for_update(session, user_id=user_id, tenant_key=tk)
        assert user is not None
        assert bump_epoch_if_revoked(user, 0) is False
        assert bump_epoch_if_revoked(user, 2) is True
        await session.commit()
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1

    async with db_manager.get_session_async(tenant_key=tk) as session:
        assert await lock_user_for_update(session, user_id=str(uuid4()), tenant_key=tk) is None
