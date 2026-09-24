# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.tools.tool_accessor import ToolAccessor


def _make_mock_product(product_id="prod-123", name="Test Product"):
    product = Mock()
    product.id = product_id
    product.name = name
    return product


def _make_taxonomy_row(abbr="BE"):
    row = Mock()
    row.id = f"tt-{abbr}"
    row.abbreviation = abbr
    row.label = abbr
    return row


def _make_tool_accessor(tenant_key="tenant-abc"):
    db_manager = Mock()
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return ToolAccessor(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=None,
        test_session=None,
    )


def _patch_active_product(product_id="prod-456"):
    return patch(
        "giljo_mcp.services.product_service.ProductService",
        return_value=AsyncMock(resolve_binding_product=AsyncMock(return_value=_make_mock_product(product_id))),
    )


def _patch_taxonomy(resolved_abbr="BE"):
    instance = AsyncMock()
    instance.ensure_reserved_type = AsyncMock(
        side_effect=lambda _tenant_key, abbreviation: _make_taxonomy_row(abbreviation)
    )
    instance.ensure_reserved_task_type = AsyncMock(return_value=_make_taxonomy_row("TSK"))
    instance.validate = AsyncMock(return_value=_make_taxonomy_row(resolved_abbr))
    instance._valid_types_payload = AsyncMock(
        return_value=[{"abbreviation": "BE", "label": "Backend", "color": "#000"}]
    )
    return patch("giljo_mcp.services.taxonomy_service.TaxonomyService", return_value=instance)


class TestToolAccessorCreateTaskValidation:
    @pytest.mark.asyncio
    async def test_raises_validation_error_when_no_active_product(self):
        tool_accessor = _make_tool_accessor()
        with (
            patch.object(ProductService, "get_default_product", new_callable=AsyncMock, return_value=None),
            patch.object(ProductService, "list_products", new_callable=AsyncMock, return_value=[]),
        ):
            with pytest.raises(ValidationError) as exc_info:
                await tool_accessor._task_service.create_task_for_mcp(
                    title="Test Task",
                    description="Should fail",
                    priority="medium",
                    tenant_key="tenant-abc",
                )
            assert "default product" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_uses_tenant_manager_when_tenant_key_not_provided(self):
        tool_accessor = _make_tool_accessor(tenant_key="tenant-from-manager")
        with (
            _patch_active_product("prod-123") as mock_product_cls,
            _patch_taxonomy("BE"),
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            mock_log_task.return_value = "task-123"
            await tool_accessor._task_service.create_task_for_mcp(
                title="Test Task", description="Test description", tenant_key=None
            )
            call_kwargs = mock_product_cls.call_args[1]
            assert call_kwargs["tenant_key"] == "tenant-from-manager"


class TestToolAccessorCreateTaskReturnValue:
    @pytest.mark.asyncio
    async def test_returns_dict_with_success_and_task_id(self):
        tool_accessor = _make_tool_accessor()
        with (
            _patch_active_product("prod-456"),
            _patch_taxonomy("BE"),
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            mock_log_task.return_value = "task-789"
            result = await tool_accessor._task_service.create_task_for_mcp(
                title="Integration Task",
                description="Task description here",
                priority="high",
                tenant_key="tenant-abc",
            )
            assert isinstance(result, dict)
            assert result["success"] is True
            assert result["task_id"] == "task-789"
            assert result["title"] == "Integration Task"
            assert result["priority"] == "high"
            assert result["task_type"] == "TSK"
            assert "Integration Task" in result["message"]

    @pytest.mark.asyncio
    async def test_return_dict_includes_product_id(self):
        tool_accessor = _make_tool_accessor()
        with (
            _patch_active_product("prod-999"),
            _patch_taxonomy("BE"),
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            mock_log_task.return_value = "task-001"
            result = await tool_accessor._task_service.create_task_for_mcp(
                title="Task A",
                description="Description A",
                tenant_key="tenant-abc",
            )
            assert result["product_id"] == "prod-999"


class TestToolAccessorCreateTaskTitlePreservation:
    @pytest.mark.asyncio
    async def test_passes_title_to_task_service_log_task(self):
        tool_accessor = _make_tool_accessor()
        with (
            _patch_active_product("prod-456"),
            _patch_taxonomy("BUG"),
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            mock_log_task.return_value = "task-789"
            await tool_accessor._task_service.create_task_for_mcp(
                title="Fix login bug",
                description="Users cannot login with email containing special chars",
                priority="high",
                tenant_key="tenant-abc",
            )
            mock_log_task.assert_called_once()
            call_kwargs = mock_log_task.call_args[1]
            assert call_kwargs["title"] == "Fix login bug"
            assert call_kwargs["description"] == "Users cannot login with email containing special chars"

    @pytest.mark.asyncio
    async def test_content_parameter_uses_title_for_backwards_compat(self):
        tool_accessor = _make_tool_accessor()
        with (
            _patch_active_product("prod-456"),
            _patch_taxonomy("BE"),
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            mock_log_task.return_value = "task-789"
            await tool_accessor._task_service.create_task_for_mcp(
                title="My Task Title",
                description="Extended details about the task",
                tenant_key="tenant-abc",
            )
            call_kwargs = mock_log_task.call_args[1]
            assert call_kwargs["content"] == "My Task Title"


class TestToolAccessorCreateTaskTaskTypeResolution:

    @pytest.mark.asyncio
    async def test_omitted_task_type_forces_tsk_without_validate(self):
        tool_accessor = _make_tool_accessor()
        with (
            _patch_active_product("prod-456"),
            _patch_taxonomy("BE") as tax_cls,
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            mock_log_task.return_value = "task-789"
            result = await tool_accessor._task_service.create_task_for_mcp(
                title="Some task",
                description="Detail",
                task_type=None,
                tenant_key="tenant-abc",
            )
            tax_instance = tax_cls.return_value
            tax_instance.validate.assert_not_called()
            tax_instance.ensure_reserved_type.assert_awaited_once_with("tenant-abc", "TSK")
            assert result["task_type"] == "TSK"
            assert "valid_types" not in result

    @pytest.mark.asyncio
    async def test_a_project_taxonomy_abbreviation_is_refused_not_absorbed(self):
        from giljo_mcp.exceptions import ValidationError

        tool_accessor = _make_tool_accessor()
        with (
            _patch_active_product("prod-456"),
            _patch_taxonomy("FE"),
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            mock_log_task.return_value = "task-789"
            with pytest.raises(ValidationError, match="FE"):
                await tool_accessor._task_service.create_task_for_mcp(
                    title="UI work",
                    description="Detail",
                    task_type="FE",
                    tenant_key="tenant-abc",
                )
            mock_log_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_handover_type_resolves_to_the_hnd_reserved_tag(self):
        tool_accessor = _make_tool_accessor()
        with (
            _patch_active_product("prod-456"),
            _patch_taxonomy("HND") as tax_cls,
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            mock_log_task.return_value = "task-789"
            result = await tool_accessor._task_service.create_task_for_mcp(
                title="Session handover",
                description=(
                    "## Verify before trusting\n- x\n\n"
                    "## Waiting on the operator\n- nothing\n\n"
                    "## Cannot testify\n- nothing"
                ),
                task_type="HND",
                tenant_key="tenant-abc",
            )
            tax_instance = tax_cls.return_value
            tax_instance.validate.assert_not_called()
            tax_instance.ensure_reserved_type.assert_awaited_once_with("tenant-abc", "HND")
            assert result["task_type"] == "HND"

    @pytest.mark.asyncio
    async def test_a_handover_missing_its_headings_never_reaches_the_write(self):
        from giljo_mcp.exceptions import ValidationError

        tool_accessor = _make_tool_accessor()
        with (
            _patch_active_product("prod-456"),
            _patch_taxonomy("HND"),
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            with pytest.raises(ValidationError, match="Cannot testify"):
                await tool_accessor._task_service.create_task_for_mcp(
                    title="Session handover",
                    description="## Verify before trusting\n- x\n\n## Waiting on the operator\n- nothing",
                    task_type="HND",
                    tenant_key="tenant-abc",
                )
            mock_log_task.assert_not_called()


class TestToolAccessorCreateTaskLogging:
    @pytest.mark.asyncio
    async def test_logs_on_successful_task_creation(self, caplog):
        tool_accessor = _make_tool_accessor()
        with (
            _patch_active_product("prod-456"),
            _patch_taxonomy("BE"),
            patch.object(tool_accessor._task_service, "log_task", new_callable=AsyncMock) as mock_log_task,
        ):
            mock_log_task.return_value = "task-log-test"
            with caplog.at_level(logging.INFO, logger="giljo_mcp.services.task_service.TaskService"):
                await tool_accessor._task_service.create_task_for_mcp(
                    title="Logged Task",
                    description="Should produce a log",
                    tenant_key="tenant-abc",
                )
            assert any("task-log-test" in rec.getMessage() for rec in caplog.records)
