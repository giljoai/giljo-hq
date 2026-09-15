# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt
import pytest
from sqlalchemy import update

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.auth.principal import (
    AuthErrorReason,
    Principal,
    PrincipalValidationError,
    validate_principal,
)
from giljo_mcp.models.auth import User
from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache


@pytest.fixture
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "sec6011_contract_secret")
    return "sec6011_contract_secret"


async def _seed_user(db_manager, *, epoch: int = 0) -> tuple[str, str, str]:
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"SEC6011 Org {unique}",
            slug=f"sec6011-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec6011_user_{unique}",
                email=f"sec6011_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=epoch,
            )
        )
        await session.commit()

    return user_id, f"sec6011_user_{unique}", tk


async def _set_epoch(db_manager, user_id: str, tenant_key: str, epoch: int) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(
            update(User).where(User.id == user_id, User.tenant_key == tenant_key).values(token_revocation_epoch=epoch)
        )
        await session.commit()


def _mint(user_id: str, username: str, tenant_key: str, *, revocation_epoch: int) -> str:
    return JWTManager.create_access_token(
        user_id=user_id,
        username=username,
        role="developer",
        tenant_key=tenant_key,
        revocation_epoch=revocation_epoch,
    )




class TestRevClaimMinting:
    def test_create_access_token_embeds_rev(self, jwt_secret):
        token = JWTManager.create_access_token(
            user_id=str(uuid4()), username="u", role="developer", tenant_key="tk_x", revocation_epoch=5
        )
        payload = jwt.decode(token, jwt_secret, algorithms=[JWTManager.ALGORITHM], options={"verify_aud": False})
        assert payload["rev"] == 5

    def test_create_access_token_defaults_rev_to_zero(self, jwt_secret):
        token = JWTManager.create_access_token(user_id=str(uuid4()), username="u", role="developer", tenant_key="tk_x")
        payload = jwt.decode(token, jwt_secret, algorithms=[JWTManager.ALGORITHM], options={"verify_aud": False})
        assert payload["rev"] == 0




class TestRevocationEpochContract:
    @pytest.mark.asyncio
    async def test_token_at_current_epoch_authenticates(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager, epoch=0)
        token = _mint(user_id, username, tk, revocation_epoch=0)

        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=token)

        assert isinstance(principal, Principal)
        assert principal.user_id == user_id
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_stale_token_rejected_after_force_logout_and_relogin_works(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager, epoch=0)

        stale = _mint(user_id, username, tk, revocation_epoch=0)

        await _set_epoch(db_manager, user_id, tk, 1)

        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, jwt_token=stale)
        assert exc.value.reason == AuthErrorReason.REVOKED

        fresh = _mint(user_id, username, tk, revocation_epoch=1)
        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=fresh)
        assert principal.user_id == user_id
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_legacy_token_without_rev_claim_treated_as_epoch_zero(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager, epoch=0)

        now = datetime.now(UTC)
        legacy = jwt.encode(
            {
                "sub": user_id,
                "username": username,
                "role": "developer",
                "tenant_key": tk,
                "exp": now + timedelta(hours=1),
                "iat": now,
                "type": "access",
                "jti": uuid4().hex,
            },
            jwt_secret,
            algorithm=JWTManager.ALGORITHM,
        )

        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=legacy)
        assert principal.user_id == user_id

        await _set_epoch(db_manager, user_id, tk, 1)
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, jwt_token=legacy)
        assert exc.value.reason == AuthErrorReason.REVOKED
        clear_revocation_cache()
