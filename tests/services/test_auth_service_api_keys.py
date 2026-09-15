# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.auth import APIKey
from giljo_mcp.schemas.service_responses import (
    ApiKeyCreateResult,
    ApiKeyInfo,
)




@pytest_asyncio.fixture
async def auth_api_key(db_session, auth_user_with_password):
    user, _ = auth_user_with_password
    unique_id = str(uuid4())[:8]
    raw_key = f"gk_test_key_{unique_id}_{uuid4().hex[:12]}"
    api_key = APIKey(
        id=str(uuid4()),
        tenant_key=user.tenant_key,
        user_id=user.id,
        name=f"Test API Key {unique_id}",
        key_hash=bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        key_prefix="gk_test_key_",
        permissions=["*"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return api_key, raw_key




class TestListAPIKeys:

    @pytest.mark.asyncio
    async def test_list_api_keys_active_only(self, auth_service, auth_user_with_password, auth_api_key):
        user, _ = auth_user_with_password

        result = await auth_service.list_api_keys(user.id, include_revoked=False)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ApiKeyInfo)
        assert result[0].name.startswith("Test API Key")
        assert result[0].is_active is True

    @pytest.mark.asyncio
    async def test_list_api_keys_include_revoked(self, auth_service, auth_user_with_password, auth_api_key, db_session):
        user, _ = auth_user_with_password
        api_key, _ = auth_api_key

        api_key.is_active = False
        api_key.revoked_at = datetime.now(UTC)
        await db_session.commit()

        result = await auth_service.list_api_keys(user.id, include_revoked=True)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ApiKeyInfo)
        assert result[0].is_active is False
        assert result[0].revoked_at is not None

    @pytest.mark.asyncio
    async def test_list_api_keys_empty(self, auth_service, auth_user_with_password):
        result = await auth_service.list_api_keys("user-no-keys", include_revoked=False)

        assert isinstance(result, list)
        assert len(result) == 0


class TestCreateAPIKey:

    @pytest.mark.asyncio
    async def test_create_api_key_success(self, auth_service, auth_user_with_password):
        user, _ = auth_user_with_password

        result = await auth_service.create_api_key(
            user_id=user.id, tenant_key=user.tenant_key, name="New Test Key", permissions=["*"]
        )

        assert isinstance(result, ApiKeyCreateResult)
        assert result.name == "New Test Key"
        assert result.api_key.startswith("gk_")
        assert result.key_prefix is not None
        assert result.key_hash is not None

    @pytest.mark.asyncio
    async def test_create_api_key_custom_permissions(self, auth_service, auth_user_with_password):
        user, _ = auth_user_with_password

        result = await auth_service.create_api_key(
            user_id=user.id, tenant_key=user.tenant_key, name="Limited Key", permissions=["read", "write"]
        )

        assert isinstance(result, ApiKeyCreateResult)
        assert result.permissions == ["read", "write"]


class TestRevokeAPIKey:

    @pytest.mark.asyncio
    async def test_revoke_api_key_success(self, auth_service, auth_user_with_password, auth_api_key, db_session):
        user, _ = auth_user_with_password
        api_key, _ = auth_api_key

        result = await auth_service.revoke_api_key(api_key.id, user.id)
        assert result is None

        stmt = select(APIKey).where(APIKey.id == api_key.id)
        result_db = await db_session.execute(stmt)
        revoked_key = result_db.scalar_one()
        assert revoked_key.is_active is False
        assert revoked_key.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_api_key_not_found(self, auth_service, auth_user_with_password):
        user, _ = auth_user_with_password

        with pytest.raises(ResourceNotFoundError):
            await auth_service.revoke_api_key("nonexistent-key-id", user.id)

    @pytest.mark.asyncio
    async def test_revoke_api_key_wrong_user(self, auth_service, auth_api_key, db_session):
        api_key, _ = auth_api_key

        with pytest.raises(ResourceNotFoundError):
            await auth_service.revoke_api_key(api_key.id, "wrong-user-id")
