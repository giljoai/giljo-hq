# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager




class TestCreateAccessTokenRequiresTenantKey:

    def test_create_access_token_requires_tenant_key(self):
        with pytest.raises(TypeError):
            JWTManager.create_access_token(
                user_id=uuid.uuid4(),
                username="testuser",
                role="developer",
            )

    def test_create_access_token_with_tenant_key_succeeds(self):
        token = JWTManager.create_access_token(
            user_id=uuid.uuid4(),
            username="testuser",
            role="developer",
            tenant_key="tk_test123",
        )
        assert token is not None
        assert isinstance(token, str)
        payload = JWTManager.verify_token(token)
        assert payload["tenant_key"] == "tk_test123"




class TestValidateJwtTokenTenantKeyRequired:

    @pytest.mark.asyncio
    async def test_jwt_without_tenant_key_claim_rejected(self):
        from api.auth_utils import validate_jwt_token

        secret_key = JWTManager._get_secret_key()
        payload = {
            "sub": str(uuid.uuid4()),
            "username": "testuser",
            "role": "developer",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
            "type": "access",
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256")

        result = await validate_jwt_token(token)
        assert result is None, "validate_jwt_token should return None for JWTs missing tenant_key"

    @pytest.mark.asyncio
    async def test_valid_jwt_with_tenant_key_accepted(self):
        from api.auth_utils import validate_jwt_token

        token = JWTManager.create_access_token(
            user_id=uuid.uuid4(),
            username="testuser",
            role="developer",
            tenant_key="tk_test",
        )

        result = await validate_jwt_token(token)
        assert result is not None
        assert result["tenant_key"] == "tk_test"
        assert result["role"] == "developer"




class TestSubscriptionPermissionTenantKeyRequired:

    def test_subscription_denied_when_user_missing_tenant_key(self):
        from api.auth_utils import check_subscription_permission

        auth_context = {
            "user": {
                "user_id": "testuser",
                "role": "developer",
                "permissions": ["*"],
            }
        }

        result = check_subscription_permission(
            auth_context=auth_context,
            entity_type="project",
            entity_id=str(uuid.uuid4()),
            tenant_key="tk_entity_tenant",
        )
        assert result is False, "Subscription should be denied when user has no tenant_key"

    def test_subscription_allowed_when_tenant_key_matches(self):
        from api.auth_utils import check_subscription_permission

        tenant = "tk_matching_tenant"
        auth_context = {
            "user": {
                "user_id": "testuser",
                "tenant_key": tenant,
                "role": "developer",
                "permissions": ["*"],
            }
        }

        result = check_subscription_permission(
            auth_context=auth_context,
            entity_type="project",
            entity_id=str(uuid.uuid4()),
            tenant_key=tenant,
        )
        assert result is True




class TestAuthenticateWebsocketApiKeyTenantKey:

    @pytest.mark.asyncio
    async def test_api_key_auth_uses_db_tenant_key(self):
        from api.auth_utils import authenticate_websocket

        mock_websocket = AsyncMock()
        mock_websocket.query_params = {"api_key": "test-api-key"}
        mock_websocket.headers = {}

        mock_db = AsyncMock()
        mock_db.info = {}

        validated_key = {
            "name": "test-key",
            "tenant_key": "tk_from_database",
            "permissions": ["*"],
        }

        with (
            patch("api.auth_utils.get_setup_state", return_value={"database_initialized": True}),
            patch("api.auth_utils.validate_api_key", return_value=validated_key),
        ):
            result = await authenticate_websocket(mock_websocket, db=mock_db)

        assert result["authenticated"] is True
        assert result["user"]["tenant_key"] == "tk_from_database"
