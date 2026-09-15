# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers.model_factories import make_agent_template, strict_result




class TestSeederProducesSlimBootstrap:

    def test_default_templates_have_slim_system_instructions(self):
        from giljo_mcp.template_seeder import _get_default_templates_v103

        templates = _get_default_templates_v103()
        for tmpl in templates:
            assert "user_instructions" in tmpl
            assert len(tmpl["user_instructions"]) > 100, (
                f"Template {tmpl['name']} should have rich user_instructions (>100 chars)"
            )

    def test_bootstrap_content_is_slim(self):
        from giljo_mcp.template_seeder import _get_mcp_bootstrap_section

        bootstrap = _get_mcp_bootstrap_section()
        lines = [line for line in bootstrap.strip().split("\n") if line.strip()]
        assert len(lines) <= 15, f"Bootstrap should be slim (~10 lines), got {len(lines)}"
        from giljo_mcp.branding import PRODUCT_NAME

        assert f"{PRODUCT_NAME} Agent" in bootstrap or PRODUCT_NAME in bootstrap
        assert "get_job_mission" in bootstrap
        assert "health_check" in bootstrap
        assert "full_protocol" in bootstrap

    def test_bootstrap_does_not_contain_protocol(self):
        from giljo_mcp.template_seeder import _get_mcp_bootstrap_section

        bootstrap = _get_mcp_bootstrap_section()
        assert "CHECK-IN PROTOCOL" not in bootstrap
        assert "MESSAGING" not in bootstrap
        assert "Agent Guidelines" not in bootstrap
        assert "REQUESTING BROADER CONTEXT" not in bootstrap




class TestRefreshProducesSlimFormat:

    @pytest.mark.asyncio
    async def test_refresh_uses_slim_bootstrap(self):
        from giljo_mcp.template_seeder import _get_mcp_bootstrap_section

        bootstrap = _get_mcp_bootstrap_section()
        assert "## MCP Tool Usage" not in bootstrap
        assert "## CHECK-IN PROTOCOL" not in bootstrap
        assert "get_job_mission" in bootstrap




class TestGetAgentTemplatesIncludesUserInstructions:

    @pytest.mark.asyncio
    async def test_full_detail_includes_user_instructions(self):
        from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates

        mock_template = make_agent_template(
            name="implementer",
            role="implementer",
            description="Implementation specialist",
            system_instructions="Bootstrap content",
            user_instructions="You are an implementation specialist.",
            behavioral_rules=["Follow standards"],
            success_criteria=["Tests pass"],
            meta_data={},
            is_active=True,
        )

        mock_result = strict_result(scalars_all=[mock_template], all=[(mock_template.id,)])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.info = {}

        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_agent_templates(
            product_id="test-product",
            tenant_key="test-tenant",
            detail="full",
            db_manager=mock_db_manager,
        )

        assert len(result["data"]) == 1
        template_data = result["data"][0]
        assert "user_instructions" in template_data, "Full detail response must include user_instructions"
        assert template_data["user_instructions"] == "You are an implementation specialist."
        assert "behavioral_rules" in template_data
        assert "success_criteria" in template_data




class TestResolveSpawnTemplateContent:

    def test_mission_returned_unchanged_and_template_id_captured(self):
        original_mission = "Implement the REST API endpoint for user management"

        assert "AGENT EXPERTISE" not in original_mission
        assert "YOUR ASSIGNED WORK" not in original_mission

        box_art_markers = ["╔═", "╚═", "║"]
        for marker in box_art_markers:
            assert marker not in original_mission, f"Mission should not contain box-art framing: {marker}"
