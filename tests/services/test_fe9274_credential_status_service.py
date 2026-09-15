# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import APIKey, User
from giljo_mcp.models.oauth import OAuthRefreshToken
from giljo_mcp.services.credential_status_service import get_credential_status


pytestmark = pytest.mark.asyncio


async def _get_status(session, tenant_key: str):
    with tenant_session_context(session, tenant_key):
        return await get_credential_status(session, tenant_key)


async def _create_user(session, tenant_key: str) -> User:
    unique_id = uuid4().hex[:8]
    user = User(
        id=str(uuid4()),
        username=f"fe9274_{unique_id}",
        email=f"fe9274_{unique_id}@example.com",
        password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def _create_api_key(session, *, tenant_key: str, user_id: str, is_active: bool, expires_at) -> None:
    session.add(
        APIKey(
            id=str(uuid4()),
            tenant_key=tenant_key,
            user_id=user_id,
            name=f"key_{uuid4().hex[:6]}",
            key_hash=f"hash_{uuid4().hex}",
            key_prefix="gk_test_",
            permissions=["*"],
            is_active=is_active,
            expires_at=expires_at,
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()


async def _create_oauth_token(session, *, tenant_key: str, user_id: str, revoked: bool, expires_at) -> None:
    session.add(
        OAuthRefreshToken(
            token_hash=uuid4().hex,
            family_id=str(uuid4()),
            client_id="giljo-mcp-default",
            tenant_key=tenant_key,
            user_id=user_id,
            aud="https://example.test/mcp",
            expires_at=expires_at,
            revoked=revoked,
        )
    )
    await session.flush()


class TestCredentialStatusApiKeys:
    async def test_no_rows_all_false(self, db_session):
        tenant_key = f"tk_{uuid4().hex[:12]}"
        result = await _get_status(db_session, tenant_key)
        assert result.has_valid_api_key is False
        assert result.has_valid_oauth is False
        assert result.has_expired_oauth is False

    async def test_active_non_expiring_key_is_valid(self, db_session):
        tenant_key = f"tk_{uuid4().hex[:12]}"
        user = await _create_user(db_session, tenant_key)
        await _create_api_key(db_session, tenant_key=tenant_key, user_id=user.id, is_active=True, expires_at=None)

        result = await _get_status(db_session, tenant_key)
        assert result.has_valid_api_key is True

    async def test_active_future_expiry_key_is_valid(self, db_session):
        tenant_key = f"tk_{uuid4().hex[:12]}"
        user = await _create_user(db_session, tenant_key)
        await _create_api_key(
            db_session,
            tenant_key=tenant_key,
            user_id=user.id,
            is_active=True,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )

        result = await _get_status(db_session, tenant_key)
        assert result.has_valid_api_key is True

    async def test_inactive_key_only_is_false(self, db_session):
        tenant_key = f"tk_{uuid4().hex[:12]}"
        user = await _create_user(db_session, tenant_key)
        await _create_api_key(db_session, tenant_key=tenant_key, user_id=user.id, is_active=False, expires_at=None)

        result = await _get_status(db_session, tenant_key)
        assert result.has_valid_api_key is False

    async def test_expired_active_key_only_is_false(self, db_session):
        tenant_key = f"tk_{uuid4().hex[:12]}"
        user = await _create_user(db_session, tenant_key)
        await _create_api_key(
            db_session,
            tenant_key=tenant_key,
            user_id=user.id,
            is_active=True,
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        result = await _get_status(db_session, tenant_key)
        assert result.has_valid_api_key is False


class TestCredentialStatusOAuth:
    async def test_valid_refresh_token_is_valid_oauth(self, db_session):
        tenant_key = f"tk_{uuid4().hex[:12]}"
        user = await _create_user(db_session, tenant_key)
        await _create_oauth_token(
            db_session,
            tenant_key=tenant_key,
            user_id=user.id,
            revoked=False,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )

        result = await _get_status(db_session, tenant_key)
        assert result.has_valid_oauth is True
        assert result.has_expired_oauth is False

    async def test_only_revoked_and_expired_rows_sets_expired_flag(self, db_session):
        tenant_key = f"tk_{uuid4().hex[:12]}"
        user = await _create_user(db_session, tenant_key)
        await _create_oauth_token(
            db_session,
            tenant_key=tenant_key,
            user_id=user.id,
            revoked=True,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        await _create_oauth_token(
            db_session,
            tenant_key=tenant_key,
            user_id=user.id,
            revoked=False,
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        result = await _get_status(db_session, tenant_key)
        assert result.has_valid_oauth is False
        assert result.has_expired_oauth is True

    async def test_one_valid_among_expired_rows_is_valid_not_expired(self, db_session):
        tenant_key = f"tk_{uuid4().hex[:12]}"
        user = await _create_user(db_session, tenant_key)
        await _create_oauth_token(
            db_session,
            tenant_key=tenant_key,
            user_id=user.id,
            revoked=True,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        await _create_oauth_token(
            db_session,
            tenant_key=tenant_key,
            user_id=user.id,
            revoked=False,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )

        result = await _get_status(db_session, tenant_key)
        assert result.has_valid_oauth is True
        assert result.has_expired_oauth is False


class TestCredentialStatusTenantIsolation:
    async def test_tenant_b_never_sees_tenant_a_credentials(self, db_session):
        tenant_a = f"tk_a_{uuid4().hex[:12]}"
        tenant_b = f"tk_b_{uuid4().hex[:12]}"
        user_a = await _create_user(db_session, tenant_a)
        await _create_api_key(db_session, tenant_key=tenant_a, user_id=user_a.id, is_active=True, expires_at=None)
        await _create_oauth_token(
            db_session,
            tenant_key=tenant_a,
            user_id=user_a.id,
            revoked=False,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )

        result_a = await _get_status(db_session, tenant_a)
        result_b = await _get_status(db_session, tenant_b)

        assert result_a.has_valid_api_key is True
        assert result_a.has_valid_oauth is True

        assert result_b.has_valid_api_key is False
        assert result_b.has_valid_oauth is False
        assert result_b.has_expired_oauth is False


class TestCredentialStatusEndpointBoundary:

    async def test_route_reflects_seeded_api_key_for_authenticated_tenant(self, db_session):
        from api.endpoints.connect import get_connect_credential_status

        tenant_key = f"tk_{uuid4().hex[:12]}"
        user = await _create_user(db_session, tenant_key)
        await _create_api_key(db_session, tenant_key=tenant_key, user_id=user.id, is_active=True, expires_at=None)

        with tenant_session_context(db_session, tenant_key):
            result = await get_connect_credential_status(current_user=user, db=db_session)

        assert result.has_valid_api_key is True
        assert result.has_valid_oauth is False
        assert result.has_expired_oauth is False
