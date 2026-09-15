# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tools.tool_accessor import ToolAccessor


def _stub_product(product_id: str, name: str) -> Mock:
    product = Mock()
    product.id = product_id
    product.name = name
    return product


@pytest.fixture(autouse=True)
def _autopatch_valid_project_types():
    with patch.object(
        ProjectService,
        "_get_valid_project_types",
        new_callable=AsyncMock,
        return_value=[],
    ):
        yield


class TestCreateProjectActiveProductResolution:

    @pytest.mark.asyncio
    async def test_resolves_active_product_when_product_id_not_provided(self):
        db_manager = Mock()
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="tenant-abc")

        tool_accessor = ToolAccessor(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=None,
            test_session=None,
        )

        with (
            patch.object(
                ProductService,
                "get_default_product",
                new_callable=AsyncMock,
            ) as mock_get_active,
            patch.object(
                ProductService,
                "list_products",
                new_callable=AsyncMock,
            ) as mock_list_products,
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_product = Mock()
            mock_product.id = "prod-123"
            mock_product.name = "Product 123"
            mock_product.is_active = True
            mock_get_active.return_value = mock_product
            mock_list_products.return_value = [mock_product]

            mock_project = Mock()
            mock_project.id = "proj-456"
            mock_project.alias = "PRJ-001"
            mock_project.name = "Test Project"
            mock_project.description = ""
            mock_project.mission = ""
            mock_project.status = "inactive"
            mock_project.product_id = "prod-123"
            mock_project.created_at = None
            mock_create.return_value = mock_project

            result = await tool_accessor._project_service.create_project_for_mcp(
                name="Test Project",
                tenant_key="tenant-abc",
            )

            mock_get_active.assert_awaited_once()

            mock_create.assert_awaited_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["product_id"] == "prod-123"

            assert result["product_name"] == "Product 123"

    @pytest.mark.asyncio
    async def test_explicit_product_id_is_validated_not_trusted(self):
        db_manager = Mock()
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="tenant-abc")

        tool_accessor = ToolAccessor(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=None,
            test_session=None,
        )

        with (
            patch.object(
                ProductService,
                "resolve_binding_product",
                new_callable=AsyncMock,
            ) as mock_resolve,
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_product = Mock()
            mock_product.id = "explicit-prod-id"
            mock_product.name = "Explicitly Named Product"
            mock_resolve.return_value = mock_product

            mock_project = Mock()
            mock_project.id = "proj-789"
            mock_project.alias = "PRJ-002"
            mock_project.name = "Explicit Product Project"
            mock_project.description = ""
            mock_project.mission = ""
            mock_project.status = "inactive"
            mock_project.product_id = "explicit-prod-id"
            mock_project.created_at = None
            mock_create.return_value = mock_project

            await tool_accessor._project_service.create_project_for_mcp(
                name="Explicit Product Project",
                product_id="explicit-prod-id",
                tenant_key="tenant-abc",
            )

            mock_resolve.assert_awaited_once()
            assert mock_resolve.await_args[0][0] == "explicit-prod-id"

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["product_id"] == "explicit-prod-id"

    @pytest.mark.asyncio
    async def test_raises_validation_error_when_no_active_product(self):
        db_manager = Mock()
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="tenant-abc")

        tool_accessor = ToolAccessor(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=None,
            test_session=None,
        )

        with (
            patch.object(
                ProductService,
                "get_default_product",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                ProductService,
                "list_products",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            with pytest.raises(ValidationError) as exc_info:
                await tool_accessor._project_service.create_project_for_mcp(
                    name="Should Fail Project",
                    tenant_key="tenant-abc",
                )

            error_message = str(exc_info.value)
            assert "default product" in error_message.lower()

    @pytest.mark.asyncio
    async def test_uses_tenant_manager_when_tenant_key_not_provided(self):
        db_manager = Mock()
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="tenant-from-manager")

        tool_accessor = ToolAccessor(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=None,
            test_session=None,
        )

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_product_service_cls,
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_product = Mock()
            mock_product.id = "prod-999"
            mock_product.name = "Product 999"

            mock_ps_instance = AsyncMock()
            mock_ps_instance.resolve_binding_product = AsyncMock(return_value=mock_product)
            mock_product_service_cls.return_value = mock_ps_instance

            mock_project = Mock()
            mock_project.id = "proj-111"
            mock_project.alias = "PRJ-003"
            mock_project.name = "Fallback Tenant Project"
            mock_project.description = ""
            mock_project.mission = ""
            mock_project.status = "inactive"
            mock_project.product_id = "prod-999"
            mock_project.created_at = None
            mock_create.return_value = mock_project

            await tool_accessor._project_service.create_project_for_mcp(
                name="Fallback Tenant Project",
                tenant_key=None,
            )

            tenant_manager.get_current_tenant.assert_called_once()

            call_kwargs = mock_product_service_cls.call_args[1]
            assert call_kwargs["tenant_key"] == "tenant-from-manager"


class TestCreateProjectReturnValue:

    @pytest.mark.asyncio
    async def test_returns_serializable_dict(self):
        db_manager = Mock()
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="tenant-abc")

        tool_accessor = ToolAccessor(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=None,
            test_session=None,
        )

        with (
            patch.object(
                ProductService,
                "resolve_binding_product",
                new_callable=AsyncMock,
                return_value=_stub_product("prod-bbb", "Product BBB"),
            ),
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_project = Mock()
            mock_project.id = "proj-aaa"
            mock_project.alias = "PRJ-010"
            mock_project.name = "Serialization Test"
            mock_project.description = "Test description"
            mock_project.mission = ""
            mock_project.status = "inactive"
            mock_project.product_id = "prod-bbb"
            mock_project.created_at = None
            mock_create.return_value = mock_project

            result = await tool_accessor._project_service.create_project_for_mcp(
                name="Serialization Test",
                product_id="prod-bbb",
                tenant_key="tenant-abc",
            )

            assert isinstance(result, dict), "Return value must be a dict"
            assert result["success"] is True
            assert result["project_id"] == "proj-aaa"
            assert result["alias"] == "PRJ-010"
            assert result["name"] == "Serialization Test"
            assert result["status"] == "inactive"
            assert result["product_id"] == "prod-bbb"
            assert "message" in result
            assert "Serialization Test" in result["message"]

    @pytest.mark.asyncio
    async def test_return_dict_contains_all_expected_keys(self):
        db_manager = Mock()
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="tenant-abc")

        tool_accessor = ToolAccessor(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=None,
            test_session=None,
        )

        with (
            patch.object(
                ProductService,
                "resolve_binding_product",
                new_callable=AsyncMock,
                return_value=_stub_product("prod-xyz", "Product XYZ"),
            ),
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_project = Mock()
            mock_project.id = "proj-xyz"
            mock_project.alias = "PRJ-099"
            mock_project.name = "Keys Test"
            mock_project.description = "Keys Test desc"
            mock_project.mission = ""
            mock_project.status = "inactive"
            mock_project.product_id = "prod-xyz"
            mock_project.created_at = None
            mock_create.return_value = mock_project

            result = await tool_accessor._project_service.create_project_for_mcp(
                name="Keys Test",
                product_id="prod-xyz",
                tenant_key="tenant-abc",
            )

            expected_keys = {
                "success",
                "project_id",
                "alias",
                "taxonomy_alias",
                "name",
                "description",
                "mission",
                "status",
                "product_id",
                "product_name",
                "created_at",
                "message",
                "project_type",
                "series_number",
                "valid_types",
                "numbering",
            }
            assert set(result.keys()) == expected_keys, f"Expected keys {expected_keys}, got {set(result.keys())}"
