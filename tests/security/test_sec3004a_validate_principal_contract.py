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

from giljo_mcp.api_key_utils import (
    clear_api_key_verify_cache,
    get_key_prefix,
    hash_api_key,
)
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.auth.principal import (
    AuthErrorReason,
    Principal,
    PrincipalValidationError,
    validate_principal,
)
from giljo_mcp.services.oauth_revocation_service import (
    clear_revocation_cache,
    revoke_dashboard_access_jwt,
)


_CANONICAL_AUD = "http://test/mcp"


@pytest.fixture
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "sec3004a_contract_secret")
    return "sec3004a_contract_secret"


async def _seed_user(db_manager, *, is_active: bool = True) -> tuple[str, str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"SEC3004a Org {unique}",
            slug=f"sec3004a-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec3004a_user_{unique}",
                email=f"sec3004a_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=is_active,
            )
        )
        await session.commit()

    return user_id, f"sec3004a_user_{unique}", tk


async def _seed_api_key(db_manager, *, expires_at: datetime | None = None, user_active: bool = True) -> tuple[str, str]:
    from giljo_mcp.models.auth import APIKey, User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    raw_key = f"gk_{uuid4().hex}{uuid4().hex}"
    user_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"SEC3004a KeyOrg {unique}",
            slug=f"sec3004a-keyorg-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec3004a_keyuser_{unique}",
                email=f"sec3004a_key_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=user_active,
            )
        )
        await session.flush()
        session.add(
            APIKey(
                id=str(uuid4()),
                tenant_key=tk,
                user_id=user_id,
                name=f"SEC3004a Key {unique}",
                key_hash=hash_api_key(raw_key),
                key_prefix=get_key_prefix(raw_key),
                permissions=["*"],
                is_active=True,
                created_at=datetime.now(UTC),
                expires_at=expires_at,
            )
        )
        await session.commit()

    return raw_key, tk


def _mint(
    user_id: str, username: str, tenant_key: str, *, audience: str | None = None, scope: str | None = None
) -> str:
    return JWTManager.create_access_token(
        user_id=user_id,
        username=username,
        role="developer",
        tenant_key=tenant_key,
        audience=audience,
        scope=scope,
    )


def _mint_expired(user_id: str, tenant_key: str, secret: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user_id,
            "username": "expired_user",
            "role": "developer",
            "tenant_key": tenant_key,
            "exp": now - timedelta(hours=1),
            "iat": now - timedelta(hours=25),
            "type": "access",
            "jti": uuid4().hex,
        },
        secret,
        algorithm=JWTManager.ALGORITHM,
    )




class TestJwtContract:
    @pytest.mark.asyncio
    async def test_valid_jwt_authenticates(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = _mint(user_id, username, tk)

        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=token)

        assert isinstance(principal, Principal)
        assert principal.user_id == user_id
        assert principal.tenant_key == tk
        assert principal.auth_method == "jwt"
        assert principal.username == username
        assert principal.user is not None and principal.user.is_active
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_malformed_jwt_rejected(self, db_manager, jwt_secret):
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, jwt_token="not.a.jwt")
        assert exc.value.reason == AuthErrorReason.INVALID_TOKEN

    @pytest.mark.asyncio
    async def test_expired_jwt_rejected(self, db_manager, jwt_secret):
        user_id, _username, tk = await _seed_user(db_manager)
        token = _mint_expired(user_id, tk, jwt_secret)
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, jwt_token=token)
        assert exc.value.reason == AuthErrorReason.EXPIRED

    @pytest.mark.asyncio
    async def test_revoked_jwt_rejected_but_valid_first(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = _mint(user_id, username, tk)

        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=token)
        assert principal.user_id == user_id

        async with db_manager.get_session_async() as db:
            assert await revoke_dashboard_access_jwt(db, token=token) is True
            await db.commit()
        clear_revocation_cache()

        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, jwt_token=token)
        assert exc.value.reason == AuthErrorReason.REVOKED
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_deactivated_user_jwt_rejected(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager, is_active=False)
        token = _mint(user_id, username, tk)
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, jwt_token=token)
        assert exc.value.reason == AuthErrorReason.INACTIVE
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_revocation_does_not_cross_tenants(self, db_manager, jwt_secret):
        clear_revocation_cache()
        ua, na, ta = await _seed_user(db_manager)
        ub, nb, tb = await _seed_user(db_manager)
        token_a = _mint(ua, na, ta)
        token_b = _mint(ub, nb, tb)

        async with db_manager.get_session_async() as db:
            await revoke_dashboard_access_jwt(db, token=token_a)
            await db.commit()
        clear_revocation_cache()

        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=token_b)
        assert principal.user_id == ub
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_scope_claim_parsed(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = _mint(user_id, username, tk, scope="mcp:read mcp:write")
        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=token)
        assert principal.scopes == ["mcp:read", "mcp:write"]
        clear_revocation_cache()




class TestAudienceBinding:
    @pytest.mark.asyncio
    async def test_matching_audience_authenticates(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = _mint(user_id, username, tk, audience=_CANONICAL_AUD, scope="mcp:read")
        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=token, expected_audience=_CANONICAL_AUD)
        assert principal.user_id == user_id
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_foreign_audience_rejected(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = _mint(user_id, username, tk, audience="http://other/mcp")
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, jwt_token=token, expected_audience=_CANONICAL_AUD)
        assert exc.value.reason == AuthErrorReason.INVALID_AUDIENCE
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_audless_token_rejected_at_resource_server(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = _mint(user_id, username, tk)
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, jwt_token=token, expected_audience=_CANONICAL_AUD)
        assert exc.value.reason == AuthErrorReason.INVALID_AUDIENCE
        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=token)
        assert principal.user_id == user_id
        clear_revocation_cache()




class TestApiKeyContract:
    @pytest.mark.asyncio
    async def test_valid_api_key_authenticates(self, db_manager):
        clear_api_key_verify_cache()
        raw_key, tk = await _seed_api_key(db_manager)
        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, api_key=raw_key)
        assert principal.auth_method == "api_key"
        assert principal.tenant_key == tk
        assert principal.api_key_id is not None
        assert principal.user is not None and principal.user.is_active
        clear_api_key_verify_cache()

    @pytest.mark.asyncio
    async def test_malformed_api_key_rejected(self, db_manager):
        clear_api_key_verify_cache()
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, api_key="gk_does_not_exist")
        assert exc.value.reason == AuthErrorReason.INVALID_CREDENTIALS
        clear_api_key_verify_cache()

    @pytest.mark.asyncio
    async def test_expired_api_key_rejected(self, db_manager):
        clear_api_key_verify_cache()
        raw_key, _tk = await _seed_api_key(db_manager, expires_at=datetime.now(UTC) - timedelta(hours=1))
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, api_key=raw_key)
        assert exc.value.reason == AuthErrorReason.INVALID_CREDENTIALS
        clear_api_key_verify_cache()

    @pytest.mark.asyncio
    async def test_null_expiry_api_key_authenticates(self, db_manager):
        clear_api_key_verify_cache()
        raw_key, _tk = await _seed_api_key(db_manager, expires_at=None)
        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, api_key=raw_key)
        assert principal.auth_method == "api_key"
        clear_api_key_verify_cache()

    @pytest.mark.asyncio
    async def test_api_key_with_inactive_user_rejected(self, db_manager):
        clear_api_key_verify_cache()
        raw_key, _tk = await _seed_api_key(db_manager, user_active=False)
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db, api_key=raw_key)
        assert exc.value.reason == AuthErrorReason.INVALID_CREDENTIALS
        clear_api_key_verify_cache()




class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_credentials_rejected(self, db_manager):
        async with db_manager.get_session_async() as db:
            with pytest.raises(PrincipalValidationError) as exc:
                await validate_principal(db)
        assert exc.value.reason == AuthErrorReason.INVALID_CREDENTIALS

    @pytest.mark.asyncio
    async def test_prefetched_active_user_is_reused(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = _mint(user_id, username, tk)

        from sqlalchemy import select as _select

        from giljo_mcp.models.auth import User

        async with db_manager.get_session_async(tenant_key=tk) as seed_db:
            stash = (await seed_db.execute(_select(User).where(User.id == user_id))).scalar_one()

        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=token, prefetched_user=stash)
        assert principal.user_id == user_id
        clear_revocation_cache()

    @pytest.mark.asyncio
    async def test_stale_inactive_prefetched_user_is_ignored(self, db_manager, jwt_secret):
        clear_revocation_cache()
        user_id, username, tk = await _seed_user(db_manager)
        token = _mint(user_id, username, tk)

        from sqlalchemy import select as _select

        from giljo_mcp.models.auth import User

        async with db_manager.get_session_async(tenant_key=tk) as seed_db:
            stash = (await seed_db.execute(_select(User).where(User.id == user_id))).scalar_one()
            seed_db.expunge(stash)
        stash.is_active = False

        async with db_manager.get_session_async() as db:
            principal = await validate_principal(db, jwt_token=token, prefetched_user=stash)
        assert principal.user_id == user_id
        assert principal.user.is_active is True
        clear_revocation_cache()
