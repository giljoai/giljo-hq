# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for ToolAccessor.create_project() — product resolution and return value.

Test Coverage:
- Active product resolution when product_id not provided
- Raises ValidationError when no active product exists
- Uses tenant_manager fallback when tenant_key not provided
- Returns serializable dict (not ORM object)

BE-9411: product resolution moved behind ``ProductService.resolve_binding_product``,
which validates an explicitly supplied product_id against the tenant instead of
trusting it. The default (omitted) path is unchanged and these tests now exercise
the REAL resolver over a stubbed ``get_active_product``. Explicit-id tests stub the
resolver itself -- their subject is mission/status/return-dict forwarding, and the
validation behavior they used to (wrongly) pin is covered for real against a live DB
in ``tests/integration/test_be9411_explicit_product_id_on_creates.py``.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tools.tool_accessor import ToolAccessor


def _stub_product(product_id: str, name: str) -> Mock:
    """A resolved product stand-in (BE-9411): only id + name are read."""
    product = Mock()
    product.id = product_id
    product.name = name
    return product


@pytest.fixture(autouse=True)
def _autopatch_valid_project_types():
    """create_project_for_mcp now reads valid_types as a hint when project_type is omitted.

    These tests don't set up a real DB; stub the helper so the omitted-type path
    doesn't try to open an async session. Tests that exercise the unknown-type
    rejection path explicitly mock this with a populated list.
    """
    with patch.object(
        ProjectService,
        "_get_valid_project_types",
        new_callable=AsyncMock,
        return_value=[],
    ):
        yield


class TestCreateProjectActiveProductResolution:
    """Test suite for active product resolution logic."""

    @pytest.mark.asyncio
    async def test_resolves_active_product_when_product_id_not_provided(self):
        """Test that active product is fetched when product_id is None."""
        db_manager = Mock()
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="tenant-abc")

        tool_accessor = ToolAccessor(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=None,
            test_session=None,
        )

        # BE-9411: stub only the active-product lookup and let the REAL
        # resolve_binding_product run, so the default path is genuinely covered
        # rather than mocked away.
        with (
            patch.object(
                ProductService,
                "get_active_product",
                new_callable=AsyncMock,
            ) as mock_get_active,
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_product = Mock()
            mock_product.id = "prod-123"
            mock_product.name = "Product 123"
            mock_get_active.return_value = mock_product

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

            # The active product was consulted (omitted product_id -> ambient).
            mock_get_active.assert_awaited_once()

            # Verify create_project was called with resolved product_id
            mock_create.assert_awaited_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["product_id"] == "prod-123"

            # BE-9411: the response names the landing on the default path too.
            assert result["product_name"] == "Product 123"

    @pytest.mark.asyncio
    async def test_explicit_product_id_is_validated_not_trusted(self):
        """BE-9411: an explicit product_id goes THROUGH resolution, not around it.

        This test used to assert the opposite -- that supplying product_id skipped
        the ProductService entirely (``assert_not_called``). That skip was the
        vulnerability: the id came from an agent and reached the write with no
        tenant-membership check at all. The parameter is now resolved and validated
        like any other untrusted input, so the assertion is inverted deliberately.
        """
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

            # The supplied id is handed to the validator, not straight to the write.
            mock_resolve.assert_awaited_once()
            assert mock_resolve.await_args[0][0] == "explicit-prod-id"

            # Verify create_project used the validated product_id
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["product_id"] == "explicit-prod-id"

    @pytest.mark.asyncio
    async def test_raises_validation_error_when_no_active_product(self):
        """Test that ValidationError is raised when no active product exists."""
        db_manager = Mock()
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="tenant-abc")

        tool_accessor = ToolAccessor(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=None,
            test_session=None,
        )

        # Real resolver, no active product to find -> the real 422 it raises.
        with patch.object(
            ProductService,
            "get_active_product",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(ValidationError) as exc_info:
                await tool_accessor._project_service.create_project_for_mcp(
                    name="Should Fail Project",
                    tenant_key="tenant-abc",
                )

            error_message = str(exc_info.value)
            assert "active product" in error_message.lower()

    @pytest.mark.asyncio
    async def test_uses_tenant_manager_when_tenant_key_not_provided(self):
        """Test that tenant_manager is used when tenant_key is None."""
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

            # Verify tenant_manager was called
            tenant_manager.get_current_tenant.assert_called_once()

            # Verify ProductService was instantiated with manager's tenant_key
            call_kwargs = mock_product_service_cls.call_args[1]
            assert call_kwargs["tenant_key"] == "tenant-from-manager"


class TestCreateProjectReturnValue:
    """Test suite for return value serialization."""

    @pytest.mark.asyncio
    async def test_returns_serializable_dict(self):
        """Test that create_project returns a plain dict, not an ORM object."""
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
        """Test that the returned dict has exactly the expected keys."""
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
                # BE-9411: the create response names its landing, not just its id.
                "product_name",
                "created_at",
                "message",
                "project_type",
                "series_number",
                "valid_types",
                # BE-6049d: create-success advertises auto-numbering so agents
                # stop supplying series_number.
                "numbering",
            }
            assert set(result.keys()) == expected_keys, f"Expected keys {expected_keys}, got {set(result.keys())}"
