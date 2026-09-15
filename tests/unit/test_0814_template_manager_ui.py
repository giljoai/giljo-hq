# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_seeder import _get_mcp_bootstrap_section




def _make_template(**overrides) -> AgentTemplate:
    defaults = {
        "name": "test-agent",
        "role": "implementer",
        "cli_tool": "claude",
        "description": "Test agent for 0814 validation",
        "system_instructions": _get_mcp_bootstrap_section(),
        "user_instructions": "You are a testing specialist.",
        "model": "sonnet",
        "behavioral_rules": ["Follow coding standards", "Write tests first"],
        "success_criteria": ["All tests pass", "No linting errors"],
    }
    defaults.update(overrides)
    return AgentTemplate(**defaults)


def _make_mock_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.add = Mock()
    session.delete = Mock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.info = {}

    async def _simulate_refresh(obj, *args, **kwargs):
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(UTC)

    session.refresh = AsyncMock(side_effect=_simulate_refresh)
    return session




class TestResetSystemInstructionsCanonical:

    @pytest.mark.asyncio
    async def test_reset_produces_canonical_bootstrap(self):
        from giljo_mcp.services.template_service import TemplateService

        canonical = _get_mcp_bootstrap_section()

        template = _make_template(
            system_instructions="Stale or corrupted bootstrap content",
        )

        session = _make_mock_session()
        db_manager = Mock()
        db_manager.get_session_async = Mock(return_value=session)
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)
        await service.reset_system_instructions(session, template)

        assert template.system_instructions == canonical

    @pytest.mark.asyncio
    async def test_reset_canonical_contains_startup_sequence(self):
        from giljo_mcp.services.template_service import TemplateService

        template = _make_template(
            system_instructions="Old content",
        )

        session = _make_mock_session()
        db_manager = Mock()
        db_manager.get_session_async = Mock(return_value=session)
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)
        await service.reset_system_instructions(session, template)

        assert "health_check" in template.system_instructions
        assert "get_job_mission" in template.system_instructions
        assert "full_protocol" in template.system_instructions
        from giljo_mcp.branding import PRODUCT_NAME

        assert PRODUCT_NAME in template.system_instructions

    @pytest.mark.asyncio
    async def test_reset_canonical_does_not_contain_protocol_sections(self):
        from giljo_mcp.services.template_service import TemplateService

        template = _make_template(
            system_instructions="Old content with ## CHECK-IN PROTOCOL",
        )

        session = _make_mock_session()
        db_manager = Mock()
        db_manager.get_session_async = Mock(return_value=session)
        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)
        await service.reset_system_instructions(session, template)

        assert "## CHECK-IN PROTOCOL" not in template.system_instructions
        assert "## MESSAGING" not in template.system_instructions
        assert "## Agent Guidelines" not in template.system_instructions
