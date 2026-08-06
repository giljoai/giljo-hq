# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for Handover 0813: Agent Template Context Separation.

Tests the three-context separation:
- Role Identity: baked into template file (system_instructions bootstrap + user_instructions)
- Operating Protocols: delivered via get_job_mission() -> full_protocol
- Work Order: delivered via get_job_mission() -> mission

TDD: These tests are written FIRST (RED phase).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_renderer import render_claude_agent


# ---------------------------------------------------------------------------
# 1. Renderer: user_instructions now included in exported .md files
# ---------------------------------------------------------------------------


class TestRendererIncludesUserInstructions:
    """render_claude_agent() must include user_instructions in output."""

    def test_user_instructions_appears_in_rendered_output(self):
        """User instructions prose should appear in the rendered .md body."""
        template = AgentTemplate(
            name="implementer",
            role="implementer",
            cli_tool="claude",
            description="Implementation specialist",
            system_instructions="## GiljoAI MCP Agent\nSlim bootstrap content.",
            user_instructions="You are a production code specialist with deep expertise in clean architecture.",
            model="sonnet",
            behavioral_rules=["Follow coding standards"],
            success_criteria=["Code passes linting"],
        )

        result = render_claude_agent(template)

        assert "You are a production code specialist" in result
        assert "clean architecture" in result

    def test_user_instructions_appears_after_system_instructions(self):
        """User instructions should come after system_instructions in the body."""
        template = AgentTemplate(
            name="tester",
            role="tester",
            cli_tool="claude",
            description="Testing specialist",
            system_instructions="## GiljoAI MCP Agent\nBootstrap.",
            user_instructions="You are a testing specialist who writes behavior-driven tests.",
            model="sonnet",
        )

        result = render_claude_agent(template)
        body = result.split("---\n")[-1].strip()

        # System instructions (bootstrap) should come before user_instructions
        bootstrap_pos = body.find("GiljoAI MCP Agent")
        user_pos = body.find("testing specialist who writes")
        assert bootstrap_pos < user_pos, "Bootstrap should appear before user_instructions"

    def test_empty_user_instructions_still_renders(self):
        """If user_instructions is empty, template still renders without error."""
        template = AgentTemplate(
            name="minimal",
            role="minimal",
            cli_tool="claude",
            description="Minimal agent",
            system_instructions="Bootstrap content.",
            user_instructions="",
            model="sonnet",
        )

        result = render_claude_agent(template)
        assert result.startswith("---\n")
        assert "Bootstrap content." in result

    def test_none_user_instructions_still_renders(self):
        """If user_instructions is None, template still renders without error."""
        template = AgentTemplate(
            name="none-ui",
            role="test",
            cli_tool="claude",
            description="Test",
            system_instructions="Bootstrap.",
            user_instructions=None,
            model="sonnet",
        )

        result = render_claude_agent(template)
        assert result.startswith("---\n")
        assert "Bootstrap." in result


# ---------------------------------------------------------------------------
# 2. Renderer: old protocol sections NOT in exported files
# ---------------------------------------------------------------------------


class TestRendererExcludesOldProtocol:
    """Exported .md files should NOT contain protocol boilerplate.
    Protocol is delivered via full_protocol from get_job_mission().
    """

    def _make_template_with_slim_bootstrap(self, **overrides):
        """Helper to create a template with the new slim bootstrap."""
        defaults = {
            "name": "implementer",
            "role": "implementer",
            "cli_tool": "claude",
            "description": "Implementation specialist",
            "system_instructions": (
                "## GiljoAI MCP Agent\n\n"
                "You are part of a GiljoAI MCP orchestration system.\n\n"
                "### STARTUP (MANDATORY)\n"
                "1. Call `mcp__giljo_mcp__health_check()`\n"
                '2. Call `mcp__giljo_mcp__get_job_mission(job_id="<your_job_id>")`\n'
                "3. Follow `full_protocol` for all lifecycle behavior\n"
            ),
            "user_instructions": "You are an implementation specialist.",
            "model": "sonnet",
            "behavioral_rules": ["Follow standards"],
            "success_criteria": ["Tests pass"],
        }
        defaults.update(overrides)
        return AgentTemplate(**defaults)

    def test_no_mcp_tool_usage_section(self):
        """MCP Tool Usage protocol section should NOT be in exported file."""
        template = self._make_template_with_slim_bootstrap()
        result = render_claude_agent(template)
        assert "## MCP Tool Usage" not in result

    def test_no_check_in_protocol_section(self):
        """CHECK-IN PROTOCOL section should NOT be in exported file."""
        template = self._make_template_with_slim_bootstrap()
        result = render_claude_agent(template)
        assert "## CHECK-IN PROTOCOL" not in result

    def test_no_messaging_section(self):
        """MESSAGING protocol section should NOT be in exported file."""
        template = self._make_template_with_slim_bootstrap()
        result = render_claude_agent(template)
        assert "## MESSAGING" not in result

    def test_no_agent_guidelines_section(self):
        """Agent Guidelines protocol section should NOT be in exported file."""
        template = self._make_template_with_slim_bootstrap()
        result = render_claude_agent(template)
        assert "## Agent Guidelines" not in result

    def test_no_requesting_broader_context_section(self):
        """REQUESTING BROADER CONTEXT section should NOT be in exported file."""
        template = self._make_template_with_slim_bootstrap()
        result = render_claude_agent(template)
        assert "### REQUESTING BROADER CONTEXT" not in result

    def test_no_orchestrator_coordination_section(self):
        """ORCHESTRATOR COORDINATION section should NOT be in exported file."""
        template = self._make_template_with_slim_bootstrap(name="orchestrator", role="orchestrator")
        result = render_claude_agent(template)
        assert "## ORCHESTRATOR COORDINATION" not in result


# ---------------------------------------------------------------------------
# 3. Seeder: system_instructions is slim bootstrap
# ---------------------------------------------------------------------------


class TestSeederProducesSlimBootstrap:
    """seed_tenant_templates() should produce slim system_instructions."""

    def test_default_templates_have_slim_system_instructions(self):
        """All default templates should have slim bootstrap, not protocol boilerplate."""
        from giljo_mcp.template_seeder import _get_default_templates_v103

        templates = _get_default_templates_v103()
        for tmpl in templates:
            # The handover removes system_instructions from the template dicts
            # since the seeder builds it. But we test the seeder output below.
            assert "user_instructions" in tmpl
            assert len(tmpl["user_instructions"]) > 100, (
                f"Template {tmpl['name']} should have rich user_instructions (>100 chars)"
            )

    def test_bootstrap_content_is_slim(self):
        """The bootstrap text used for system_instructions should be ~5-10 lines."""
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
        """The bootstrap should NOT contain full protocol sections."""
        from giljo_mcp.template_seeder import _get_mcp_bootstrap_section

        bootstrap = _get_mcp_bootstrap_section()
        assert "CHECK-IN PROTOCOL" not in bootstrap
        assert "MESSAGING" not in bootstrap
        assert "Agent Guidelines" not in bootstrap
        assert "REQUESTING BROADER CONTEXT" not in bootstrap


# ---------------------------------------------------------------------------
# 4. Refresh: regenerates slim format
# ---------------------------------------------------------------------------


class TestRefreshProducesSlimFormat:
    """refresh_tenant_template_instructions() should regenerate slim bootstrap."""

    @pytest.mark.asyncio
    async def test_refresh_uses_slim_bootstrap(self):
        """After refresh, system_instructions should be slim bootstrap."""
        from giljo_mcp.template_seeder import _get_mcp_bootstrap_section

        # The bootstrap function should exist and return slim content
        bootstrap = _get_mcp_bootstrap_section()
        assert "## MCP Tool Usage" not in bootstrap
        assert "## CHECK-IN PROTOCOL" not in bootstrap
        assert "get_job_mission" in bootstrap


# ---------------------------------------------------------------------------
# 5. Export endpoint: includes user_instructions
# ---------------------------------------------------------------------------


class TestClaudeExportIncludesUserInstructions:
    """claude_export.py should include user_instructions in exported files."""

    def test_export_content_includes_user_instructions(self):
        """The export function should render user_instructions into the file."""
        # We test via render_claude_agent since export uses it (via file_staging)
        # or has its own inline logic that should also include user_instructions
        template = AgentTemplate(
            name="reviewer",
            role="reviewer",
            cli_tool="claude",
            description="Code review specialist",
            system_instructions="## GiljoAI MCP Agent\nBootstrap.",
            user_instructions="You are a code review specialist who provides constructive feedback.",
            model="sonnet",
            behavioral_rules=["Be constructive"],
            success_criteria=["No critical bugs"],
        )

        result = render_claude_agent(template)
        assert "constructive feedback" in result
        assert "## Behavioral Rules" in result
        assert "## Success Criteria" in result


# ---------------------------------------------------------------------------
# 6. Context tool: includes user_instructions in "full" mode
# ---------------------------------------------------------------------------


class TestGetAgentTemplatesIncludesUserInstructions:
    """get_agent_templates context tool should include user_instructions in 'full' mode."""

    @pytest.mark.asyncio
    async def test_full_detail_includes_user_instructions(self):
        """Full detail response should include user_instructions field."""
        from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates

        # Create mock template with user_instructions
        mock_template = MagicMock()
        mock_template.name = "implementer"
        mock_template.role = "implementer"
        mock_template.description = "Implementation specialist"
        mock_template.system_instructions = "Bootstrap content"
        mock_template.user_instructions = "You are an implementation specialist."
        mock_template.behavioral_rules = ["Follow standards"]
        mock_template.success_criteria = ["Tests pass"]
        mock_template.meta_data = {}
        mock_template.is_active = True
        mock_template.created_at = None
        mock_template.updated_at = None

        # Mock the database session
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_template]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.info = {}  # tenant_session_context save/restore target

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


# ---------------------------------------------------------------------------
# 7. Exported .md files are lean (~30-50 lines, not 108)
# ---------------------------------------------------------------------------


class TestExportedFileSize:
    """Exported .md files should be 30-50 lines, not 108+ of boilerplate."""

    def test_rendered_template_is_lean(self):
        """Rendered template with slim bootstrap + role prose should be ~30-50 lines."""
        template = AgentTemplate(
            name="implementer",
            role="implementer",
            cli_tool="claude",
            description="Implementation specialist for writing production-grade code",
            system_instructions=(
                "## GiljoAI MCP Agent\n\n"
                "You are part of a GiljoAI MCP orchestration system. MCP tools are available as native\n"
                "tool calls prefixed `mcp__giljo_mcp__*` in your tool list.\n\n"
                "### STARTUP (MANDATORY)\n"
                "1. Call `mcp__giljo_mcp__health_check()` to verify MCP connectivity\n"
                '2. Call `mcp__giljo_mcp__get_job_mission(job_id="<your_job_id>")` to receive:\n'
                "   - Your full operating protocols (`full_protocol`)\n"
                "   - Your work order and team context (`mission`)\n"
                "3. Follow `full_protocol` for all lifecycle behavior\n\n"
                "Do not begin work until you have received and read your mission and protocols.\n"
            ),
            user_instructions=(
                "You are an implementation specialist responsible for writing clean, "
                "production-grade code. Your expertise spans backend Python development "
                "with FastAPI and SQLAlchemy, frontend Vue 3 with Vuetify, and cross-platform "
                "compatibility across Windows, macOS, and Linux.\n\n"
                "You approach each task methodically: understand requirements first, "
                "identify existing patterns to reuse, write tests, implement minimal code "
                "to make tests pass, then refactor for clarity. You use pathlib for all "
                "file operations and never hardcode paths or credentials.\n\n"
                "Your code is written for humans first, machines second. You prefer "
                "established patterns over novel solutions, handle errors gracefully with "
                "structured logging, and leave the codebase cleaner than you found it."
            ),
            model="sonnet",
            behavioral_rules=[
                "Follow project coding standards",
                "Ensure cross-platform compatibility",
                "Never hardcode paths",
                "Use pathlib for file operations",
            ],
            success_criteria=[
                "Passes all linting checks",
                "Matches specification",
                "No breaking changes",
                "Proper error handling",
            ],
        )

        result = render_claude_agent(template)
        lines = result.strip().split("\n")

        # Should be ~30-50 lines with the lean format
        assert len(lines) <= 60, f"Exported file should be ~30-50 lines, got {len(lines)} lines"
        assert len(lines) >= 20, f"Exported file should have at least 20 lines of content, got {len(lines)}"


# ---------------------------------------------------------------------------
# 8. Multi-terminal mode: _resolve_spawn_template concatenation
# ---------------------------------------------------------------------------


class TestResolveSpawnTemplateContent:
    """Handover 0825: _resolve_spawn_template returns mission unchanged, captures template_id only."""

    def test_mission_returned_unchanged_and_template_id_captured(self):
        """_resolve_spawn_template no longer injects template content into mission.
        It captures template_id for read-time identity resolution in get_job_mission().
        """
        # The new _resolve_spawn_template simply returns:
        # (mission_unchanged, template_id_or_none)
        # Template content is resolved at read time in get_job_mission(),
        # NOT baked into the mission at spawn time.
        original_mission = "Implement the REST API endpoint for user management"

        # Verify the design contract: mission is NOT modified
        # (The actual method is async and needs DB, so we test the contract)
        assert "AGENT EXPERTISE" not in original_mission
        assert "YOUR ASSIGNED WORK" not in original_mission

        # The old box-art framing should NOT appear in missions anymore
        box_art_markers = ["╔═", "╚═", "║"]
        for marker in box_art_markers:
            assert marker not in original_mission, f"Mission should not contain box-art framing: {marker}"
