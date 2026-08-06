# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for Handover 0814: Template Manager UI Redesign (Phase 5).

Validates the backend fixes introduced in 0814 that are independent of the
create/update endpoint plumbing:
5. reset_system_instructions() produces canonical bootstrap
6. Export paths produce identical output via render_claude_agent()

Updated BE-8000j: items 1-4 (create/update endpoint behaviour — canonical
bootstrap injection, user_instructions storage, system_instructions 403,
archive-on-user_instructions-change) moved to
tests/services/test_be8000j_template_crud_routing.py. Those assertions were
structurally coupled to the endpoint's old inline-write architecture (they mocked
the granular service commit helpers and captured the entity the endpoint built);
BE-8000j moves that write into TemplateService, so they are now exercised
end-to-end against a real DB through the endpoint. Their behavioural intent is
preserved there.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_renderer import render_claude_agent
from giljo_mcp.template_seeder import _get_mcp_bootstrap_section


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_template(**overrides) -> AgentTemplate:
    """Build an AgentTemplate with sensible defaults for testing."""
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
    """Create a properly configured mock async session.

    The refresh side-effect simulates what the DB does when committing a new
    record: it fills in server-default columns like ``created_at``.
    """
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.add = Mock()
    session.delete = Mock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target

    async def _simulate_refresh(obj, *args, **kwargs):
        """Simulate DB refresh by filling server-default columns."""
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(UTC)

    session.refresh = AsyncMock(side_effect=_simulate_refresh)
    return session


# ---------------------------------------------------------------------------
# 5. reset_system_instructions produces canonical bootstrap
# ---------------------------------------------------------------------------


class TestResetSystemInstructionsCanonical:
    """reset_system_instructions() must set system_instructions to the canonical
    MCP bootstrap from _get_mcp_bootstrap_section()."""

    @pytest.mark.asyncio
    async def test_reset_produces_canonical_bootstrap(self):
        """After reset, system_instructions must match _get_mcp_bootstrap_section()."""
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
        """The canonical bootstrap must include the three-step startup sequence."""
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
        """The canonical bootstrap must NOT include full protocol sections."""
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


# ---------------------------------------------------------------------------
# 6. Export paths produce identical output (render_claude_agent consistency)
# ---------------------------------------------------------------------------


class TestRenderClaudeAgentConsistency:
    """render_claude_agent() must produce consistent, complete output including
    frontmatter, system_instructions, user_instructions, behavioral_rules,
    and success_criteria."""

    def test_output_contains_yaml_frontmatter(self):
        """Output must start with YAML frontmatter containing name, description, model."""
        template = _make_template()
        result = render_claude_agent(template)

        assert result.startswith("---\n")
        # Extract frontmatter
        parts = result.split("---\n")
        assert len(parts) >= 3, "Output must have opening and closing frontmatter delimiters"
        frontmatter = yaml.safe_load(parts[1])
        assert frontmatter["name"] == "test-agent"
        assert "description" in frontmatter
        assert frontmatter["model"] == "sonnet"

    def test_output_contains_system_instructions_bootstrap(self):
        """Output body must include the slim MCP bootstrap from system_instructions."""
        template = _make_template()
        result = render_claude_agent(template)

        from giljo_mcp.branding import PRODUCT_NAME

        assert f"{PRODUCT_NAME} Agent" in result
        assert "health_check" in result
        assert "get_job_mission" in result

    def test_output_contains_user_instructions(self):
        """Output body must include user_instructions role prose."""
        template = _make_template(
            user_instructions="You are a production code specialist with deep TDD expertise.",
        )
        result = render_claude_agent(template)
        assert "production code specialist" in result
        assert "TDD expertise" in result

    def test_output_contains_behavioral_rules(self):
        """Output body must include the behavioral rules section."""
        template = _make_template(
            behavioral_rules=["Always write tests first", "Use pathlib for file ops"],
        )
        result = render_claude_agent(template)
        assert "## Behavioral Rules" in result
        assert "- Always write tests first" in result
        assert "- Use pathlib for file ops" in result

    def test_output_contains_success_criteria(self):
        """Output body must include the success criteria section."""
        template = _make_template(
            success_criteria=["All tests green", "Linting clean"],
        )
        result = render_claude_agent(template)
        assert "## Success Criteria" in result
        assert "- All tests green" in result
        assert "- Linting clean" in result

    def test_output_ordering_bootstrap_before_user_instructions(self):
        """system_instructions (bootstrap) must appear before user_instructions in body."""
        template = _make_template(
            system_instructions=_get_mcp_bootstrap_section(),
            user_instructions="You are a specialized reviewer agent.",
        )
        result = render_claude_agent(template)

        body = result.split("---\n", 2)[-1]
        from giljo_mcp.branding import PRODUCT_NAME

        bootstrap_pos = body.find(f"{PRODUCT_NAME} Agent")
        user_pos = body.find("specialized reviewer agent")
        assert bootstrap_pos >= 0, "Bootstrap must be present in body"
        assert user_pos >= 0, "User instructions must be present in body"
        assert bootstrap_pos < user_pos, "Bootstrap must appear before user_instructions"

    def test_output_ordering_rules_and_criteria_after_user_instructions(self):
        """Behavioral rules and success criteria must appear after user_instructions."""
        template = _make_template(
            user_instructions="You are the implementer agent.",
            behavioral_rules=["Rule one"],
            success_criteria=["Criteria one"],
        )
        result = render_claude_agent(template)

        user_pos = result.find("implementer agent")
        rules_pos = result.find("## Behavioral Rules")
        criteria_pos = result.find("## Success Criteria")

        assert user_pos < rules_pos, "User instructions must come before behavioral rules"
        assert rules_pos < criteria_pos, "Behavioral rules must come before success criteria"

    def test_render_with_empty_optional_sections(self):
        """Rendering with empty behavioral_rules and success_criteria should still work."""
        template = _make_template(
            behavioral_rules=[],
            success_criteria=[],
        )
        result = render_claude_agent(template)

        assert result.startswith("---\n")
        from giljo_mcp.branding import PRODUCT_NAME

        assert f"{PRODUCT_NAME} Agent" in result
        assert "## Behavioral Rules" not in result
        assert "## Success Criteria" not in result

    def test_render_produces_identical_output_for_same_input(self):
        """Calling render_claude_agent twice with the same template produces identical output."""
        template = _make_template()
        result_1 = render_claude_agent(template)
        result_2 = render_claude_agent(template)
        assert result_1 == result_2, "render_claude_agent must be deterministic"
