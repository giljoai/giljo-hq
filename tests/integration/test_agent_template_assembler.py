# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Integration tests for the agent template assembler pipeline.

Handover 0836c: Tests the full assembler pipeline including
template rendering, color mapping, 8-cap enforcement, and edge cases
beyond the unit tests in test_template_assembler_0836a.py.
"""

import pytest
import yaml

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_renderer import render_claude_agent
from giljo_mcp.tools.agent_template_assembler import AgentTemplateAssembler


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


class TestAssemblerColorMapping:
    """Test that background_color maps correctly per platform."""

    def setup_method(self):
        self.assembler = AgentTemplateAssembler()

    def test_claude_includes_color(self):
        """Claude Code output includes color derived from background_color."""
        templates = [_make_template(background_color="#3498DB")]
        result = self.assembler.assemble(templates, "claude_code")
        assert "color" in result["agents"][0]

    def test_gemini_omits_color(self):
        """Gemini output omits color entirely."""
        templates = [_make_template(background_color="#3498DB")]
        result = self.assembler.assemble(templates, "gemini_cli")
        assert "color" not in result["agents"][0]

    def test_codex_omits_color(self):
        """Codex output omits color entirely."""
        templates = [_make_template(background_color="#3498DB")]
        result = self.assembler.assemble(templates, "codex_cli")
        agent = result["agents"][0]
        assert "color" not in agent


class TestAssemblerPlatformConsistency:
    """Test that all 3 platforms return consistent core data."""

    def setup_method(self):
        self.assembler = AgentTemplateAssembler()
        self.templates = [
            _make_template(name="analyzer-code", role="analyzer"),
            _make_template(name="tester-unit", role="tester"),
        ]

    def test_template_count_consistent(self):
        """All platforms report the same template_count."""
        for platform in ("claude_code", "gemini_cli", "codex_cli"):
            result = self.assembler.assemble(self.templates, platform)
            assert result["template_count"] == 2, f"Failed for {platform}"

    def test_format_version_consistent(self):
        """All platforms return format_version 1.0."""
        for platform in ("claude_code", "gemini_cli", "codex_cli"):
            result = self.assembler.assemble(self.templates, platform)
            assert result["format_version"] == "1.0", f"Failed for {platform}"

    def test_claude_output_matches_standalone_renderer(self):
        """Assembler Claude output must match render_claude_agent() exactly."""
        result = self.assembler.assemble(self.templates, "claude_code")
        for i, template in enumerate(self.templates):
            expected = render_claude_agent(template)
            assert result["agents"][i]["content"] == expected

    def test_gemini_frontmatter_kind_is_local(self):
        """Gemini frontmatter must have kind: local (matches built-in agent format)."""
        result = self.assembler.assemble(self.templates, "gemini_cli")
        for agent in result["agents"]:
            yaml_section = agent["content"].split("---\n")[1]
            fm = yaml.safe_load(yaml_section)
            assert fm["kind"] == "local"

    def test_gemini_omits_tools_key(self):
        """BE-9567: Gemini frontmatter carries no ``tools:`` key at all.

        A hardcoded roster here had drifted to zero live matches (the pre-rename
        ``giljo_mcp`` alias, plus one tool BE-9554 retired), and gemini-cli
        surfaces neither failure to the model or a human -- see
        render_gemini_agent's docstring for the source citations. Omitting the
        key inherits every parent tool instead (local-executor.ts's documented
        fallback), matching every other renderer's convention.
        """
        result = self.assembler.assemble(self.templates, "gemini_cli")
        yaml_section = result["agents"][0]["content"].split("---\n")[1]
        fm = yaml.safe_load(yaml_section)
        assert "tools" not in fm

    def test_codex_has_required_fields(self):
        """Codex agents must have all required structured fields."""
        result = self.assembler.assemble(self.templates, "codex_cli")
        required = {
            "agent_name",
            "description",
            "role",
            "developer_instructions",
        }
        for agent in result["agents"]:
            assert required.issubset(agent.keys())
            assert "suggested_model" not in agent
            assert "suggested_reasoning_effort" not in agent


class TestAssemblerEdgeCases:
    """Test assembler edge cases and error handling."""

    def setup_method(self):
        self.assembler = AgentTemplateAssembler()

    def test_invalid_platform_raises_validation_error(self):
        """Assembler rejects invalid platform strings."""
        with pytest.raises(ValidationError, match="Invalid platform"):
            self.assembler.assemble([], "invalid")

    def test_empty_templates_all_platforms(self):
        """Empty template list returns valid response for all platforms."""
        for platform in ("claude_code", "gemini_cli", "codex_cli"):
            result = self.assembler.assemble([], platform)
            assert result["template_count"] == 0
            assert result["agents"] == []

    def test_template_with_no_description(self):
        """Templates without description get a fallback."""
        templates = [_make_template(description=None, role="tester")]
        for platform in ("claude_code", "gemini_cli", "codex_cli"):
            result = self.assembler.assemble(templates, platform)
            assert len(result["agents"]) == 1

    def test_template_with_empty_body_sections(self):
        """Templates with empty instructions still assemble."""
        templates = [
            _make_template(
                system_instructions="",
                user_instructions="",
                behavioral_rules=[],
                success_criteria=[],
            )
        ]
        for platform in ("claude_code", "gemini_cli", "codex_cli"):
            result = self.assembler.assemble(templates, platform)
            assert len(result["agents"]) == 1
