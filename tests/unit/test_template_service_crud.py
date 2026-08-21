# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for TemplateService.get_template (Handover 0123 - Phase 2)

Covers template retrieval by ID and name (success, not-found, missing identifier).

Split from test_template_service.py.

Updated Handover 0731: Migrated from dict returns to typed TemplateGetResult.
Updated BE-8000j: the create/update/list tests were removed together with the
never-production-called create_template / update_template / list_templates
service methods; the create/update WRITE path is now covered end-to-end through
the REST endpoint in tests/services/test_be8000j_template_crud_routing.py.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.schemas.service_responses import TemplateGetResult
from giljo_mcp.services.template_service import TemplateService
from tests.helpers.model_factories import make_agent_template
from tests.unit.conftest import make_mock_db_manager, make_mock_session


class TestTemplateServiceGet:
    """Test get_template retrieval operations"""

    @pytest.mark.asyncio
    async def test_get_template_by_id_success(self):
        """Test successful template retrieval by ID"""
        # Arrange
        mock_template = make_agent_template(
            id="test-id",
            name="orchestrator",
            system_instructions="You are an orchestrator...",
            role="orchestrator",
            category="role",
            background_color="#FF5733",
            tenant_key="test-tenant",
        )

        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_template)
        session = make_mock_session(execute=AsyncMock(return_value=mock_result))
        db_manager = make_mock_db_manager(session)

        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)

        # Act
        result = await service.get_template(template_id="test-id")

        # Assert - Handover 0731: typed TemplateGetResult
        assert isinstance(result, TemplateGetResult)
        assert result.template.id == "test-id"
        assert result.template.name == "orchestrator"
        assert result.template.content == "You are an orchestrator..."

    @pytest.mark.asyncio
    async def test_get_template_by_name_success(self):
        """Test successful template retrieval by name"""
        # Arrange
        mock_template = make_agent_template(
            id="test-id",
            name="analyzer",
            system_instructions="You are an analyzer...",
            role="analyzer",
            category="role",
            background_color="#00FF00",
            tenant_key="test-tenant",
        )

        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_template)
        session = make_mock_session(execute=AsyncMock(return_value=mock_result))
        db_manager = make_mock_db_manager(session)

        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)

        # Act
        result = await service.get_template(template_name="analyzer")

        # Assert - Handover 0731: typed TemplateGetResult
        assert isinstance(result, TemplateGetResult)
        assert result.template.name == "analyzer"

    @pytest.mark.asyncio
    async def test_get_template_not_found(self):
        """Test template not found error"""
        from giljo_mcp.exceptions import TemplateNotFoundError

        # Arrange
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        session = make_mock_session(execute=AsyncMock(return_value=mock_result))
        db_manager = make_mock_db_manager(session)

        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)

        # Act & Assert - exception-based pattern (Handover 0730)
        with pytest.raises(TemplateNotFoundError) as exc_info:
            await service.get_template(template_id="nonexistent")

        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_template_missing_identifier(self):
        """Test get_template fails without ID or name"""
        from giljo_mcp.exceptions import ValidationError

        # Arrange
        db_manager = Mock()
        tenant_manager = Mock()

        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)

        # Act & Assert - exception-based pattern (Handover 0730)
        with pytest.raises(ValidationError) as exc_info:
            await service.get_template()

        assert "Either template_id or template_name must be provided" in str(exc_info.value)
