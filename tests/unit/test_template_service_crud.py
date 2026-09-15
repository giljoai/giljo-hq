# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.schemas.service_responses import TemplateGetResult
from giljo_mcp.services.template_service import TemplateService
from tests.helpers.model_factories import make_agent_template
from tests.unit.conftest import make_mock_db_manager, make_mock_session


class TestTemplateServiceGet:

    @pytest.mark.asyncio
    async def test_get_template_by_id_success(self):
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

        result = await service.get_template(template_id="test-id")

        assert isinstance(result, TemplateGetResult)
        assert result.template.id == "test-id"
        assert result.template.name == "orchestrator"
        assert result.template.content == "You are an orchestrator..."

    @pytest.mark.asyncio
    async def test_get_template_by_name_success(self):
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

        result = await service.get_template(template_name="analyzer")

        assert isinstance(result, TemplateGetResult)
        assert result.template.name == "analyzer"

    @pytest.mark.asyncio
    async def test_get_template_not_found(self):
        from giljo_mcp.exceptions import TemplateNotFoundError

        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        session = make_mock_session(execute=AsyncMock(return_value=mock_result))
        db_manager = make_mock_db_manager(session)

        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)

        with pytest.raises(TemplateNotFoundError) as exc_info:
            await service.get_template(template_id="nonexistent")

        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_template_missing_identifier(self):
        from giljo_mcp.exceptions import ValidationError

        db_manager = Mock()
        tenant_manager = Mock()

        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)

        with pytest.raises(ValidationError) as exc_info:
            await service.get_template()

        assert "Either template_id or template_name must be provided" in str(exc_info.value)
