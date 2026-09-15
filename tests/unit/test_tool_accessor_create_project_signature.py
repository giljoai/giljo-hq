# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tools.tool_accessor import ToolAccessor


def _stub_binding_resolution():
    product = Mock()
    product.id = "prod-status"
    product.name = "Stubbed Product"
    return patch.object(
        ProductService,
        "resolve_binding_product",
        new_callable=AsyncMock,
        return_value=product,
    )


@pytest.fixture(autouse=True)
def _autopatch_valid_project_types():
    with patch.object(
        ProjectService,
        "_get_valid_project_types",
        new_callable=AsyncMock,
        return_value=[],
    ):
        yield


class TestCreateProjectHardcodedBehavior:

    @pytest.mark.asyncio
    async def test_always_creates_with_inactive_status(self):
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
            _stub_binding_resolution(),
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_project = Mock()
            mock_project.id = "proj-status"
            mock_project.alias = "PRJ-STS"
            mock_project.name = "Status Test"
            mock_project.description = ""
            mock_project.mission = ""
            mock_project.status = "inactive"
            mock_project.product_id = "prod-status"
            mock_project.created_at = None
            mock_create.return_value = mock_project

            await tool_accessor._project_service.create_project_for_mcp(
                name="Status Test",
                product_id="prod-status",
                tenant_key="tenant-abc",
            )

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["status"] == "inactive", "Status must always be 'inactive'"

    @pytest.mark.asyncio
    async def test_mission_defaults_to_empty_string(self):
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
            _stub_binding_resolution(),
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_project = Mock()
            mock_project.id = "proj-mission"
            mock_project.alias = "PRJ-MSN"
            mock_project.name = "Mission Default Test"
            mock_project.description = ""
            mock_project.mission = ""
            mock_project.status = "inactive"
            mock_project.product_id = "prod-mission"
            mock_project.created_at = None
            mock_create.return_value = mock_project

            await tool_accessor._project_service.create_project_for_mcp(
                name="Mission Default Test",
                product_id="prod-mission",
                tenant_key="tenant-abc",
            )

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["mission"] == "", "Mission should default to empty string"

    @pytest.mark.asyncio
    async def test_passes_explicit_mission_when_provided(self):
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
            _stub_binding_resolution(),
            patch.object(
                tool_accessor._project_service,
                "create_project",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_project = Mock()
            mock_project.id = "proj-expl"
            mock_project.alias = "PRJ-EXP"
            mock_project.name = "Explicit Mission Test"
            mock_project.description = ""
            mock_project.mission = ""
            mock_project.status = "inactive"
            mock_project.product_id = "prod-expl"
            mock_project.created_at = None
            mock_create.return_value = mock_project

            await tool_accessor._project_service.create_project_for_mcp(
                name="Explicit Mission Test",
                mission="Build the REST API for user management",
                product_id="prod-expl",
                tenant_key="tenant-abc",
            )

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["mission"] == "Build the REST API for user management"
