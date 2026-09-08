# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Unit tests for AgentTemplateAssembler and platform-specific renderers.

Handover 0836a: Multi-platform agent template export.
Tests render_gemini_agent(), render_codex_agent(), and AgentTemplateAssembler.
"""

import pytest
import yaml

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_renderer import (
    CODEX_TOML_FORMAT_REFERENCE,
    render_claude_agent,
    render_codex_agent,
    render_gemini_agent,
)
from giljo_mcp.tools.agent_template_assembler import AgentTemplateAssembler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_template(**overrides) -> AgentTemplate:
    """Create a test AgentTemplate with sensible defaults."""
    defaults = {
        "name": "implementer-frontend",
        "role": "implementer",
        "cli_tool": "claude",
        "description": "Implements frontend features using Vue 3",
        "system_instructions": "You are a frontend implementer agent.",
        "user_instructions": "Focus on component-driven development.",
        "model": "sonnet",
        "background_color": "#3498DB",
        "behavioral_rules": ["Follow component patterns", "Write tests first"],
        "success_criteria": ["All tests pass", "Code review approved"],
    }
    defaults.update(overrides)
    return AgentTemplate(**defaults)


# ---------------------------------------------------------------------------
# render_gemini_agent tests
# ---------------------------------------------------------------------------


class TestRenderGeminiAgent:
    """Test Gemini CLI YAML format rendering."""

    def test_basic_render(self):
        """Test Gemini output has correct YAML frontmatter fields."""
        template = _make_template()
        result = render_gemini_agent(template)

        assert result.startswith("---\n")
        yaml_section = result.split("---\n")[1]
        frontmatter = yaml.safe_load(yaml_section)

        assert frontmatter["name"] == "implementer-frontend"
        assert frontmatter["description"] == "Implements frontend features using Vue 3"
        assert frontmatter["kind"] == "local"
        assert frontmatter["model"] == "inherit"
        assert frontmatter["max_turns"] == 50

    def test_omits_tools_to_inherit_all(self):
        """BE-9567: no hardcoded ``tools:`` roster. gemini-cli's local-executor.ts
        falls back to ``parentToolRegistry.getAllToolNames()`` when the key is
        absent, so the subagent inherits every parent tool (MCP included) --
        exactly what the other five renderers already rely on. A hand-maintained
        allowlist here had already drifted to zero live matches (wrong alias,
        one retired tool name) with no error surfaced anywhere."""
        template = _make_template()
        result = render_gemini_agent(template)

        yaml_section = result.split("---\n")[1]
        frontmatter = yaml.safe_load(yaml_section)

        assert "tools" not in frontmatter
        assert "mcp_giljo_mcp_" not in result
        assert "mcp_giljo_hq_" not in result

    def test_no_color_field(self):
        """Gemini does not support agent colors — no color in frontmatter."""
        template = _make_template(background_color="#3498DB")
        result = render_gemini_agent(template)

        yaml_section = result.split("---\n")[1]
        frontmatter = yaml.safe_load(yaml_section)

        assert "color" not in frontmatter

    def test_body_content(self):
        """Test that body includes system_instructions, user_instructions, rules, criteria."""
        template = _make_template()
        result = render_gemini_agent(template)

        assert "You are a frontend implementer agent." in result
        assert "Focus on component-driven development." in result
        assert "## Behavioral Rules" in result
        assert "- Follow component patterns" in result
        assert "## Success Criteria" in result
        assert "- All tests pass" in result

    def test_default_description_fallback(self):
        """Test description defaults to 'Subagent for {role}' when not provided."""
        template = _make_template(description=None, role="tester")
        result = render_gemini_agent(template)

        yaml_section = result.split("---\n")[1]
        frontmatter = yaml.safe_load(yaml_section)
        assert frontmatter["description"] == "Subagent for tester"

    def test_no_role_description_fallback(self):
        """Test description defaults to 'Subagent' when no role and no description."""
        template = _make_template(description=None, role=None)
        result = render_gemini_agent(template)

        yaml_section = result.split("---\n")[1]
        frontmatter = yaml.safe_load(yaml_section)
        assert frontmatter["description"] == "Subagent"

    def test_body_matches_claude_body(self):
        """Gemini and Claude should produce the same body content."""
        template = _make_template()
        gemini_result = render_gemini_agent(template)
        claude_result = render_claude_agent(template)

        # Extract body (after second ---)
        gemini_body = gemini_result.split("---\n", 2)[2]
        claude_body = claude_result.split("---\n", 2)[2]

        assert gemini_body == claude_body


# ---------------------------------------------------------------------------
# render_codex_agent tests
# ---------------------------------------------------------------------------


class TestRenderCodexAgent:
    """Test Codex CLI structured data rendering."""

    def test_basic_render(self):
        """Test Codex output returns correct structured dict."""
        template = _make_template()
        result = render_codex_agent(template)

        assert isinstance(result, dict)
        assert result["agent_name"] == "implementer-frontend"
        assert result["description"] == "Implements frontend features using Vue 3"
        assert result["role"] == "implementer"
        assert "suggested_model" not in result
        assert "suggested_reasoning_effort" not in result

    def test_developer_instructions_content(self):
        """Test developer_instructions combines all body sections."""
        template = _make_template()
        result = render_codex_agent(template)
        instructions = result["developer_instructions"]

        assert "You are a frontend implementer agent." in instructions
        assert "Focus on component-driven development." in instructions
        assert "## Behavioral Rules" in instructions
        assert "- Follow component patterns" in instructions
        assert "## Success Criteria" in instructions
        assert "- All tests pass" in instructions

    def test_default_description_fallback(self):
        """Test description defaults when not provided."""
        template = _make_template(description=None, role="analyzer")
        result = render_codex_agent(template)
        assert result["description"] == "Subagent for analyzer"

    def test_no_role_fallback(self):
        """Test role defaults to 'agent' when not set."""
        template = _make_template(role=None)
        result = render_codex_agent(template)
        assert result["role"] == "agent"

    def test_empty_instructions(self):
        """Test with empty system_instructions and user_instructions."""
        template = _make_template(
            system_instructions="",
            user_instructions="",
            behavioral_rules=[],
            success_criteria=[],
        )
        result = render_codex_agent(template)
        assert result["developer_instructions"] == ""


# ---------------------------------------------------------------------------
# AgentTemplateAssembler tests
# ---------------------------------------------------------------------------


class TestAgentTemplateAssembler:
    """Test the multi-platform assembler."""

    def setup_method(self):
        self.assembler = AgentTemplateAssembler()
        self.templates = [
            _make_template(name="implementer-frontend", role="implementer"),
            _make_template(name="tester-unit", role="tester", background_color="#FFC300"),
        ]

    def test_invalid_platform_raises(self):
        """Test that an invalid platform string raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid platform"):
            self.assembler.assemble(self.templates, "invalid_platform")

    def test_claude_code_response_structure(self):
        """Test Claude Code response matches API contract."""
        result = self.assembler.assemble(self.templates, "claude_code")

        assert result["platform"] == "claude_code"
        assert result["format_version"] == "1.0"
        assert result["template_count"] == 2
        assert "install_paths" in result
        assert result["install_paths"]["project"] == ".claude/agents/"
        assert result["install_paths"]["user"] == "~/.claude/agents/"

        agents = result["agents"]
        assert len(agents) == 2
        assert agents[0]["filename"] == "implementer-frontend.md"
        assert agents[0]["role"] == "implementer"
        assert "content" in agents[0]
        assert agents[0]["content"].startswith("---\n")

    def test_claude_code_output_matches_render_claude_agent(self):
        """Claude assembler output must match render_claude_agent() exactly."""
        result = self.assembler.assemble(self.templates, "claude_code")
        for i, template in enumerate(self.templates):
            expected = render_claude_agent(template)
            assert result["agents"][i]["content"] == expected

    def test_claude_code_color_mapping(self):
        """Test Claude Code includes mapped color field."""
        result = self.assembler.assemble(self.templates, "claude_code")
        # First template has #3498DB -> blue
        assert result["agents"][0]["color"] == "blue"
        # Second template has #FFC300 -> yellow
        assert result["agents"][1]["color"] == "yellow"

    def test_gemini_cli_response_structure(self):
        """Test Gemini CLI response matches API contract."""
        result = self.assembler.assemble(self.templates, "gemini_cli")

        assert result["platform"] == "gemini_cli"
        assert result["format_version"] == "1.0"
        assert result["template_count"] == 2
        assert result["install_paths"]["project"] == ".gemini/agents/"
        assert result["install_paths"]["user"] == "~/.gemini/agents/"

        agents = result["agents"]
        assert len(agents) == 2
        assert agents[0]["filename"] == "implementer-frontend.md"
        assert "content" in agents[0]
        assert agents[0]["content"].startswith("---\n")
        # Gemini should NOT have color field
        assert "color" not in agents[0]

    def test_codex_cli_response_structure(self):
        """Test Codex CLI response matches API contract."""
        result = self.assembler.assemble(self.templates, "codex_cli")

        assert result["platform"] == "codex_cli"
        assert result["format_version"] == "1.0"
        assert result["template_count"] == 2
        assert result["install_paths"]["agent_files"] == "~/.codex/agents/"
        assert result["install_paths"]["global_config_optional"] == "~/.codex/config.toml"
        assert "config_file" not in result["install_paths"]
        assert "toml_format_reference" in result
        assert result["toml_format_reference"] == CODEX_TOML_FORMAT_REFERENCE

        agents = result["agents"]
        assert len(agents) == 2
        assert agents[0]["agent_name"] == "implementer-frontend"
        assert "suggested_model" not in agents[0]
        assert "suggested_reasoning_effort" not in agents[0]
        assert "developer_instructions" in agents[0]
        # Codex should NOT have 'content' or 'filename' keys
        assert "content" not in agents[0]
        assert "filename" not in agents[0]

    def test_empty_templates_list(self):
        """Test assembler handles empty template list gracefully."""
        result = self.assembler.assemble([], "claude_code")
        assert result["template_count"] == 0
        assert result["agents"] == []

    def test_all_platforms_accepted(self):
        """Test all three platform strings are accepted without error."""
        for platform in ("claude_code", "codex_cli", "gemini_cli"):
            result = self.assembler.assemble(self.templates, platform)
            assert result["platform"] == platform
