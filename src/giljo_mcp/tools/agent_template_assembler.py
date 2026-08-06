# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
AgentTemplateAssembler — multi-platform template export (Handover 0836a).

Takes platform-neutral AgentTemplate rows from the database and produces
correctly formatted output for Claude Code, Codex CLI, or Gemini CLI.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from giljo_mcp import branding
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.platform_registry import (
    EXPORT_ANTIGRAVITY_CLI,
    EXPORT_CLAUDE_CODE,
    EXPORT_CODEX_CLI,
    EXPORT_GEMINI_CLI,
    EXPORT_GENERIC,
    VALID_EXPORT_PLATFORMS,
)
from giljo_mcp.platform_registry import INSTALL_PATHS as _INSTALL_PATHS
from giljo_mcp.template_renderer import (
    CODEX_TOML_FORMAT_REFERENCE,
    _slugify_filename,
    hex_to_claude_color,
    render_antigravity_agent,
    render_claude_agent,
    render_codex_agent,
    render_gemini_agent,
    render_generic_agent,
    render_plugin_manifest,
)


if TYPE_CHECKING:
    from giljo_mcp.models import AgentTemplate

logger = logging.getLogger(__name__)

# BE-6117: the export-platform vocabulary is owned by the PlatformRegistry.
# Re-exported here so existing importers keep resolving the name.
VALID_PLATFORMS = VALID_EXPORT_PLATFORMS

# Antigravity (`agy`) single-bundle plugin name. Spike C3 (SOW §4): the ENTIRE
# export — plugin.json + agents/ + skills/ — lives under ONE plugin tree, installed
# via `agy plugin install` to ~/.gemini/config/plugins/<name>/.
ANTIGRAVITY_PLUGIN_NAME = "giljoai"
ANTIGRAVITY_PLUGIN_VERSION = "1.0.0"
ANTIGRAVITY_PLUGIN_DESCRIPTION = f"{branding.PRODUCT_NAME} orchestration agents and skills for Antigravity CLI."

# Install path metadata per platform now lives on the PlatformRegistry
# (BE-6116, imported above as ``_INSTALL_PATHS``) -- single source for the
# per-platform agent-template install locations.


class AgentTemplateAssembler:
    """Assembles agent templates into platform-specific export format."""

    def assemble(
        self,
        templates: list[AgentTemplate],
        platform: str,
    ) -> dict:
        """Assemble templates into export response for the given platform.

        Args:
            templates: Pre-selected list of AgentTemplate model instances
                       (already filtered and capped by select_templates_for_packaging).
            platform: Target platform — 'claude_code', 'codex_cli', or 'gemini_cli'.

        Returns:
            Dict matching the API contract defined in handover 0836.

        Raises:
            ValidationError: If platform is not one of the supported values.
        """
        if platform not in VALID_PLATFORMS:
            raise ValidationError(
                f"Invalid platform '{platform}'. Must be one of: {', '.join(sorted(VALID_PLATFORMS))}"
            )

        # BE-6117: dict dispatch keyed off the registry's export vocabulary,
        # replacing the if-chain on bare platform literals.
        dispatch = {
            EXPORT_CLAUDE_CODE: self._assemble_claude,
            EXPORT_GEMINI_CLI: self._assemble_gemini,
            EXPORT_CODEX_CLI: self._assemble_codex,
            EXPORT_ANTIGRAVITY_CLI: self._assemble_antigravity,
            EXPORT_GENERIC: self._assemble_generic,
        }
        return dispatch[platform](templates)

    # ------------------------------------------------------------------
    # Claude Code — pre-assembled markdown files with YAML frontmatter
    # ------------------------------------------------------------------

    def _assemble_claude(self, templates: list[AgentTemplate]) -> dict:
        agents = []
        for t in templates:
            content = render_claude_agent(t)
            color = None
            if hasattr(t, "background_color") and t.background_color:
                color = hex_to_claude_color(t.background_color)

            agents.append(
                {
                    "filename": f"{_slugify_filename(t.name)}.md",
                    "content": content,
                    "role": t.role or "agent",
                    "color": color,
                }
            )

        return {
            "platform": "claude_code",
            "agents": agents,
            "install_paths": _INSTALL_PATHS["claude_code"],
            "template_count": len(agents),
            "format_version": "1.0",
        }

    # ------------------------------------------------------------------
    # Gemini CLI — pre-assembled markdown files (different frontmatter)
    # ------------------------------------------------------------------

    def _assemble_gemini(self, templates: list[AgentTemplate]) -> dict:
        agents = []
        for t in templates:
            content = render_gemini_agent(t)
            agents.append(
                {
                    "filename": f"{_slugify_filename(t.name)}.md",
                    "content": content,
                    "role": t.role or "agent",
                }
            )

        return {
            "platform": "gemini_cli",
            "agents": agents,
            "install_paths": _INSTALL_PATHS["gemini_cli"],
            "template_count": len(agents),
            "format_version": "1.0",
        }

    # ------------------------------------------------------------------
    # Antigravity CLI (`agy`) — NESTED plugin bundle (BE-6041c / P2).
    #
    # Spike C2/C3 (SOW §4): agents load ONLY from an installed plugin, never
    # from loose files. The whole export is one plugin tree:
    #   plugins/giljoai/plugin.json
    #   plugins/giljoai/agents/<agent_name>/agent.json   (nested config.customAgent)
    # Skills (SKILL.md) are added alongside by file_staging from
    # get_all_templates(); the manifest here is the keystone the validator needs.
    # ------------------------------------------------------------------

    def _assemble_antigravity(self, templates: list[AgentTemplate]) -> dict:
        agents = []
        for t in templates:
            agent_json = render_antigravity_agent(t)
            slug = _slugify_filename(t.name)
            agents.append(
                {
                    "agent_dir": slug,
                    "agent_json": agent_json,
                    "role": t.role or "agent",
                }
            )

        manifest = render_plugin_manifest(
            name=ANTIGRAVITY_PLUGIN_NAME,
            version=ANTIGRAVITY_PLUGIN_VERSION,
            description=ANTIGRAVITY_PLUGIN_DESCRIPTION,
        )

        return {
            "platform": "antigravity_cli",
            "plugin_name": ANTIGRAVITY_PLUGIN_NAME,
            "plugin_manifest": manifest,
            "agents": agents,
            "install_paths": _INSTALL_PATHS["antigravity_cli"],
            "template_count": len(agents),
            "format_version": "1.0",
        }

    # ------------------------------------------------------------------
    # Codex CLI — structured data (LLM writes TOML config locally)
    # ------------------------------------------------------------------

    def _assemble_codex(self, templates: list[AgentTemplate]) -> dict:
        agents = []
        for t in templates:
            agent_data = render_codex_agent(t)
            agents.append(agent_data)

        return {
            "platform": "codex_cli",
            "agents": agents,
            "install_paths": _INSTALL_PATHS["codex_cli"],
            "toml_format_reference": CODEX_TOML_FORMAT_REFERENCE,
            "template_count": len(agents),
            "format_version": "1.0",
        }

    # ------------------------------------------------------------------
    # Generic MCP — plain Markdown, no platform-specific frontmatter
    # ------------------------------------------------------------------

    def _assemble_generic(self, templates: list[AgentTemplate]) -> dict:
        agents = []
        for t in templates:
            content = render_generic_agent(t)
            agents.append(
                {
                    "filename": f"{_slugify_filename(t.name)}.md",
                    "content": content,
                    "role": t.role or "agent",
                }
            )

        return {
            "platform": "generic",
            "agents": agents,
            "install_paths": _INSTALL_PATHS["generic"],
            "template_count": len(agents),
            "format_version": "1.0",
        }
