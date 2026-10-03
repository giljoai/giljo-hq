# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from giljo_mcp.exceptions import ValidationError




@pytest.fixture
def mock_db_manager():
    db_manager = Mock()
    session = AsyncMock()
    session.info = {}

    async_cm = AsyncMock()
    async_cm.__aenter__ = AsyncMock(return_value=session)
    async_cm.__aexit__ = AsyncMock(return_value=False)

    db_manager.get_session_async = Mock(return_value=async_cm)
    return db_manager, session


@pytest.fixture
def inactive_product():
    product = MagicMock()
    product.id = "inactive-product-id"
    product.is_active = False
    product.tenant_key = "test-tenant"
    product.tech_stack = None
    product.architecture = None
    product.test_config = None
    return product


@pytest.fixture
def active_product():
    product = MagicMock()
    product.id = "active-product-id"
    product.is_active = True
    product.tenant_key = "test-tenant"
    product.tech_stack = None
    product.architecture = None
    product.test_config = None
    product.core_features = None
    return product


@pytest.fixture
def active_product_with_tech_stack(active_product):
    active_product.tech_stack = MagicMock()
    return active_product


@pytest.fixture
def active_product_with_all_fields(active_product):
    active_product.tech_stack = MagicMock()
    active_product.architecture = MagicMock()
    active_product.test_config = MagicMock()
    return active_product


def _build_service_with_product(mock_db_manager, product):
    from giljo_mcp.services.product_service import ProductService

    db_manager, _session = mock_db_manager

    mock_repo = AsyncMock()
    mock_repo.get_by_id = AsyncMock(return_value=product)
    mock_repo.update_config_relations = AsyncMock()
    mock_repo.commit = AsyncMock()
    mock_repo.refresh = AsyncMock()

    service = ProductService(db_manager, "test-tenant")
    service._repo = mock_repo

    return service




class TestActiveProductGuard:

    @pytest.mark.asyncio
    async def test_update_inactive_product_succeeds(self, mock_db_manager, inactive_product):
        service = _build_service_with_product(mock_db_manager, inactive_product)

        result = await service.update_product("inactive-product-id", name="New Name")
        assert result is not None

    @pytest.mark.asyncio
    async def test_update_active_product_succeeds(self, mock_db_manager, active_product):
        service = _build_service_with_product(mock_db_manager, active_product)

        result = await service.update_product("active-product-id", name="Updated Name")
        assert result is not None




class TestOverwriteConfirmation:

    @pytest.mark.asyncio
    async def test_update_populated_tech_stack_without_force_raises_validation_error(
        self, mock_db_manager, active_product_with_tech_stack
    ):
        service = _build_service_with_product(mock_db_manager, active_product_with_tech_stack)

        with pytest.raises(ValidationError) as exc_info:
            await service.update_product(
                "active-product-id",
                tech_stack={"language": "Python"},
                force=False,
            )

        assert "tech_stack" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_overwrite_error_message_lists_populated_fields(
        self, mock_db_manager, active_product_with_tech_stack
    ):
        service = _build_service_with_product(mock_db_manager, active_product_with_tech_stack)

        with pytest.raises(ValidationError) as exc_info:
            await service.update_product(
                "active-product-id",
                tech_stack={"language": "Python"},
            )

        assert "already populated" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_overwrite_error_includes_populated_fields_in_context(
        self, mock_db_manager, active_product_with_tech_stack
    ):
        service = _build_service_with_product(mock_db_manager, active_product_with_tech_stack)

        with pytest.raises(ValidationError) as exc_info:
            await service.update_product(
                "active-product-id",
                tech_stack={"language": "Python"},
            )

        assert exc_info.value.context is not None
        assert "populated_fields" in exc_info.value.context
        assert "tech_stack" in exc_info.value.context["populated_fields"]

    @pytest.mark.asyncio
    async def test_update_populated_tech_stack_with_force_true_succeeds(
        self, mock_db_manager, active_product_with_tech_stack
    ):
        service = _build_service_with_product(mock_db_manager, active_product_with_tech_stack)

        result = await service.update_product(
            "active-product-id",
            tech_stack={"language": "Go"},
            force=True,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_update_empty_fields_without_force_succeeds(self, mock_db_manager, active_product):
        service = _build_service_with_product(mock_db_manager, active_product)

        result = await service.update_product(
            "active-product-id",
            tech_stack={"language": "Python"},
            force=False,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_all_three_populated_fields_listed_in_error(self, mock_db_manager, active_product_with_all_fields):
        service = _build_service_with_product(mock_db_manager, active_product_with_all_fields)

        with pytest.raises(ValidationError) as exc_info:
            await service.update_product(
                "active-product-id",
                tech_stack={"language": "Python"},
                architecture={"pattern": "microservices"},
                test_config={"framework": "pytest"},
                force=False,
            )

        populated = exc_info.value.context["populated_fields"]
        assert "tech_stack" in populated
        assert "architecture" in populated
        assert "test_config" in populated

    @pytest.mark.asyncio
    async def test_non_dict_tech_stack_value_does_not_trigger_overwrite_guard(
        self, mock_db_manager, active_product_with_tech_stack
    ):
        service = _build_service_with_product(mock_db_manager, active_product_with_tech_stack)

        result = await service.update_product(
            "active-product-id",
            name="Updated Name",
            force=False,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_force_default_is_false(self, mock_db_manager, active_product_with_tech_stack):
        service = _build_service_with_product(mock_db_manager, active_product_with_tech_stack)

        with pytest.raises(ValidationError):
            await service.update_product(
                "active-product-id",
                tech_stack={"language": "Rust"},
            )




class TestDroppedFieldFiresNoEvent:

    @pytest.mark.asyncio
    async def test_dropped_product_memory_fires_no_event(self, mock_db_manager, active_product):
        service = _build_service_with_product(mock_db_manager, active_product)

        emit = AsyncMock()
        service.lifecycle._emit_websocket_event = emit
        build_memory = AsyncMock(return_value={"stale": "payload"})
        service.memory._build_product_memory_response = build_memory

        active_product.product_memory = {"original": True}

        result = await service.update_product(
            "active-product-id",
            force=True,
            product_memory={"injected": "never persisted"},
        )

        assert result is not None
        emit.assert_not_awaited()
        build_memory.assert_not_awaited()
        assert active_product.product_memory == {"original": True}, "allowlist gate must hold: nothing applied"

    @pytest.mark.asyncio
    async def test_allowed_field_update_fires_no_memory_event(self, mock_db_manager, active_product):
        service = _build_service_with_product(mock_db_manager, active_product)

        emit = AsyncMock()
        service.lifecycle._emit_websocket_event = emit

        result = await service.update_product("active-product-id", force=True, name="Renamed")

        assert result is not None
        emit.assert_not_awaited()




class TestApiKeyTenantKeyConsistency:

    def _make_api_key_record(self, tenant_key="tk_abc123", user_id="user-1"):
        key = MagicMock()
        key.id = "key-id-1"
        key.tenant_key = tenant_key
        key.user_id = user_id
        key.is_active = True
        key.name = "Test Key"
        key.last_used = None
        key.expires_at = None
        return key

    def _make_user(self, tenant_key="tk_abc123", user_id="user-1", is_active=True):
        user = MagicMock()
        user.id = user_id
        user.tenant_key = tenant_key
        user.is_active = is_active
        user.username = "testuser"
        return user

    @pytest.mark.asyncio
    async def test_matching_tenant_key_returns_user(self):
        from giljo_mcp.auth.dependencies import get_current_user

        tenant_key = "tk_matching"
        key_record = self._make_api_key_record(tenant_key=tenant_key)
        user = self._make_user(tenant_key=tenant_key)

        raw_key = "gk_" + "abcdef" + "123456789xyz"
        expected_prefix = f"{raw_key[:12]}..."
        key_record.key_prefix = expected_prefix
        key_record.key_hash = "hashed"

        mock_db = AsyncMock()
        mock_db.info = {}

        first_result = MagicMock()
        first_result.scalars.return_value.all.return_value = [key_record]
        second_result = MagicMock()
        second_result.scalar_one_or_none.return_value = user

        mock_db.execute = AsyncMock(side_effect=[first_result, second_result, MagicMock(), MagicMock()])
        mock_db.commit = AsyncMock()

        mock_request = MagicMock()
        mock_request.url.path = "/mcp/test"
        mock_request.client = None

        with patch("giljo_mcp.auth.principal.verify_api_key_cached", new=AsyncMock(return_value=True)):
            result = await get_current_user(
                request=mock_request,
                access_token=None,
                authorization=None,
                x_api_key=raw_key,
                db=mock_db,
            )

        assert result is user

    @pytest.mark.asyncio
    async def test_mismatched_tenant_key_rejects_authentication(self):
        from giljo_mcp.auth.dependencies import get_current_user

        key_tenant = "tk_key_tenant"

        key_record = self._make_api_key_record(tenant_key=key_tenant)
        raw_key = "gk_" + "abcdef" + "123456789xyz"
        key_record.key_prefix = f"{raw_key[:12]}..."
        key_record.key_hash = "hashed"

        mock_db = AsyncMock()
        mock_db.info = {}

        first_result = MagicMock()
        first_result.scalars.return_value.all.return_value = [key_record]
        second_result = MagicMock()
        second_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[first_result, second_result, MagicMock(), MagicMock()])
        mock_db.commit = AsyncMock()

        mock_request = MagicMock()
        mock_request.url.path = "/mcp/test"
        mock_request.client = None

        with patch("giljo_mcp.auth.principal.verify_api_key_cached", new=AsyncMock(return_value=True)):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=mock_request,
                    access_token=None,
                    authorization=None,
                    x_api_key=raw_key,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_inactive_user_with_matching_tenant_key_is_rejected(self):
        from giljo_mcp.auth.dependencies import get_current_user

        tenant_key = "tk_matching"
        key_record = self._make_api_key_record(tenant_key=tenant_key)
        raw_key = "gk_" + "abcdef" + "123456789xyz"
        key_record.key_prefix = f"{raw_key[:12]}..."
        key_record.key_hash = "hashed"

        mock_db = AsyncMock()
        mock_db.info = {}

        first_result = MagicMock()
        first_result.scalars.return_value.all.return_value = [key_record]
        second_result = MagicMock()
        second_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[first_result, second_result, MagicMock(), MagicMock()])
        mock_db.commit = AsyncMock()

        mock_request = MagicMock()
        mock_request.url.path = "/mcp/test"
        mock_request.client = None

        with patch("giljo_mcp.auth.principal.verify_api_key_cached", new=AsyncMock(return_value=True)):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=mock_request,
                    access_token=None,
                    authorization=None,
                    x_api_key=raw_key,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_key_prefix_narrowing_limits_candidates(self):
        from giljo_mcp.auth.dependencies import get_current_user

        raw_key = "gk_" + "abcdef" + "123456789xyz"

        wrong_prefix_key = self._make_api_key_record()
        wrong_prefix_key.key_prefix = "gk_zzzzzzzzz..."
        wrong_prefix_key.key_hash = "hashed"

        mock_db = AsyncMock()
        mock_db.info = {}

        first_result = MagicMock()
        first_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(return_value=first_result)
        mock_db.commit = AsyncMock()

        mock_request = MagicMock()
        mock_request.url.path = "/mcp/test"
        mock_request.client = None

        with patch("giljo_mcp.auth.principal.verify_api_key_cached", new=AsyncMock(return_value=False)):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=mock_request,
                    access_token=None,
                    authorization=None,
                    x_api_key=raw_key,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_mcp_session_mismatched_tenant_key_rejects_user(self):
        from api.endpoints.mcp_session import MCPSessionManager

        tenant_key_key = "tk_key_tenant"
        key_record = self._make_api_key_record(tenant_key=tenant_key_key)
        raw_key = "gk_" + "abcdef" + "123456789xyz"
        key_record.key_prefix = f"{raw_key[:12]}..."
        key_record.key_hash = "hashed"

        mock_db = AsyncMock()
        mock_db.info = {}

        first_result = MagicMock()
        first_result.scalars.return_value.all.return_value = [key_record]
        second_result = MagicMock()
        second_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[first_result, second_result])
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)

        with patch("giljo_mcp.auth.principal.verify_api_key_cached", new=AsyncMock(return_value=True)):
            result = await manager.authenticate_api_key(raw_key)

        assert result is None

    @pytest.mark.asyncio
    async def test_mcp_session_matching_tenant_key_returns_key_and_user(self):
        from api.endpoints.mcp_session import MCPSessionManager

        tenant_key = "tk_matching"
        user_id = "user-abc"
        key_record = self._make_api_key_record(tenant_key=tenant_key, user_id=user_id)
        user = self._make_user(tenant_key=tenant_key, user_id=user_id)
        raw_key = "gk_" + "abcdef" + "123456789xyz"
        key_record.key_prefix = f"{raw_key[:12]}..."
        key_record.key_hash = "hashed"

        mock_db = AsyncMock()
        mock_db.info = {}

        first_result = MagicMock()
        first_result.scalars.return_value.all.return_value = [key_record]
        second_result = MagicMock()
        second_result.scalar_one_or_none.return_value = user

        mock_db.execute = AsyncMock(side_effect=[first_result, second_result])
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)

        with patch("giljo_mcp.auth.principal.verify_api_key_cached", new=AsyncMock(return_value=True)):
            result = await manager.authenticate_api_key(raw_key)

        assert result is not None
        _key_out, user_out = result
        assert user_out is user
