# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.tools.tool_accessor import ToolAccessor


def _make_tool_accessor():
    db_manager = Mock()
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value="tenant-abc")
    return ToolAccessor(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=None,
        test_session=None,
    )


def _mock_project(**overrides):
    defaults = {
        "id": "proj-001",
        "alias": "PRJ-001",
        "name": "Test Project",
        "description": "",
        "mission": "",
        "status": "inactive",
        "product_id": "prod-123",
        "created_at": None,
    }
    defaults.update(overrides)
    mock = Mock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestCreateProjectTypeResolution:

    @pytest.mark.asyncio
    async def test_resolves_type_by_label(self):
        tool_accessor = _make_tool_accessor()

        mock_type = Mock()
        mock_type.id = "pt-frontend-uuid"

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
            patch.object(
                tool_accessor._project_service,
                "get_project_type_by_label",
                new_callable=AsyncMock,
                return_value=mock_type,
            ) as mock_lookup,
        ):
            mock_product = Mock()
            mock_product.id = "prod-123"
            mock_ps_instance = AsyncMock()
            mock_ps_instance.get_default_product = AsyncMock(return_value=mock_product)
            mock_ps_cls.return_value = mock_ps_instance

            mock_create.return_value = _mock_project()

            await tool_accessor._project_service.create_project_for_mcp(
                name="FE Project",
                project_type="Frontend",
                tenant_key="tenant-abc",
            )

            mock_lookup.assert_awaited_once_with("Frontend", "tenant-abc")
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["project_type_id"] == "pt-frontend-uuid"

    @pytest.mark.asyncio
    async def test_type_resolution_is_case_insensitive(self):
        tool_accessor = _make_tool_accessor()

        mock_type = Mock()
        mock_type.id = "pt-frontend-uuid"

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
            patch.object(
                tool_accessor._project_service,
                "get_project_type_by_label",
                new_callable=AsyncMock,
                return_value=mock_type,
            ),
        ):
            mock_product = Mock()
            mock_product.id = "prod-123"
            mock_ps_instance = AsyncMock()
            mock_ps_instance.get_default_product = AsyncMock(return_value=mock_product)
            mock_ps_cls.return_value = mock_ps_instance

            mock_create.return_value = _mock_project()

            await tool_accessor._project_service.create_project_for_mcp(
                name="FE Project",
                project_type="frontend",
                tenant_key="tenant-abc",
            )

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["project_type_id"] == "pt-frontend-uuid"

    @pytest.mark.asyncio
    async def test_unknown_type_raises_validation_error_with_valid_types(self):
        tool_accessor = _make_tool_accessor()

        valid_types_payload = [
            {"abbreviation": "FE", "label": "Frontend", "color": "#aaa"},
            {"abbreviation": "BE", "label": "Backend", "color": "#bbb"},
        ]

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
            patch.object(
                tool_accessor._project_service,
                "get_project_type_by_label",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                tool_accessor._project_service,
                "_get_valid_project_types",
                new_callable=AsyncMock,
                return_value=valid_types_payload,
            ),
        ):
            mock_product = Mock()
            mock_product.id = "prod-123"
            mock_ps_instance = AsyncMock()
            mock_ps_instance.get_default_product = AsyncMock(return_value=mock_product)
            mock_ps_cls.return_value = mock_ps_instance

            with pytest.raises(ValidationError) as exc_info:
                await tool_accessor._project_service.create_project_for_mcp(
                    name="Bogus Type Project",
                    project_type="BOGUS",
                    tenant_key="tenant-abc",
                )

            err = exc_info.value
            assert "BOGUS" in err.message
            assert err.context["valid_types"] == valid_types_payload
            assert err.context["operation"] == "create_project"
            mock_create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_type_error_shape_matches_update_project_metadata(self):
        from giljo_mcp.services.project_service import ProjectService

        valid_types_payload = [{"abbreviation": "FE", "label": "Frontend", "color": "#aaa"}]

        tool_accessor = _make_tool_accessor()
        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ),
            patch.object(
                tool_accessor._project_service,
                "get_project_type_by_label",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                tool_accessor._project_service,
                "_get_valid_project_types",
                new_callable=AsyncMock,
                return_value=valid_types_payload,
            ),
        ):
            mock_product = Mock()
            mock_product.id = "prod-123"
            mock_ps_instance = AsyncMock()
            mock_ps_instance.get_default_product = AsyncMock(return_value=mock_product)
            mock_ps_cls.return_value = mock_ps_instance

            with pytest.raises(ValidationError) as exc_info:
                await tool_accessor._project_service.create_project_for_mcp(
                    name="Bogus", project_type="BOGUS", tenant_key="tenant-abc"
                )

            ctx_keys = set(exc_info.value.context.keys())
            assert {"operation", "valid_types"}.issubset(ctx_keys)
            assert isinstance(exc_info.value.context["valid_types"], list)
            assert {"abbreviation", "label"} <= set(exc_info.value.context["valid_types"][0].keys())
            assert hasattr(ProjectService, "update_project_metadata_for_mcp")

    @pytest.mark.asyncio
    async def test_omitted_type_returns_valid_types_hint(self):
        tool_accessor = _make_tool_accessor()

        valid_types_payload = [
            {"abbreviation": "FE", "label": "Frontend", "color": "#aaa"},
            {"abbreviation": "BE", "label": "Backend", "color": "#bbb"},
        ]

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
            patch.object(
                tool_accessor._project_service,
                "_get_valid_project_types",
                new_callable=AsyncMock,
                return_value=valid_types_payload,
            ),
        ):
            mock_product = Mock()
            mock_product.id = "prod-123"
            mock_ps_instance = AsyncMock()
            mock_ps_instance.get_default_product = AsyncMock(return_value=mock_product)
            mock_ps_cls.return_value = mock_ps_instance

            mock_create.return_value = _mock_project()

            result = await tool_accessor._project_service.create_project_for_mcp(
                name="No Type Project",
                tenant_key="tenant-abc",
            )

            assert result["success"] is True
            assert result["valid_types"] == valid_types_payload
            call_kwargs = mock_create.call_args[1]
            assert "project_type_id" not in call_kwargs or call_kwargs["project_type_id"] is None
