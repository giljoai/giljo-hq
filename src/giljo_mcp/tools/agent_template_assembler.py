# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
AgentTemplateAssembler — multi-platform template export (Handover 0836a).

Takes platform-neutral AgentTemplate rows from the database and produces
correctly formatted output for Claude Code, Codex CLI, or Gemini CLI.

BE-9385b adds the collision-safety layer. Two things changed, and they are
separate mechanisms solving separate halves of the same problem:

* **Names became product-qualified.** A file is ``<agent>--<product-slug>.md``, so
  the same agent shared by two products installs twice instead of the second
  install silently replacing the first.
* **Files became self-identifying.** Each rendered file carries an ownership
  marker naming the tenant, product and template it came from, so an installer can
  refresh GiljoAI's own files and leave a user's hand-written agents untouched.

Both are driven by :class:`ExportContext`. Passing ``None`` yields exactly the
pre-BE-9385b output — bare names, no marker — which is what the anonymous
system-default download needs: it has no tenant and no product, so there is
nothing truthful to stamp on it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from giljo_mcp import branding
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.install_targets import INSTALL_PATHS as _INSTALL_PATHS
from giljo_mcp.platform_registry import (
    EXPORT_ANTIGRAVITY_CLI,
    EXPORT_CLAUDE_CODE,
    EXPORT_CODEX_CLI,
    EXPORT_GEMINI_CLI,
    EXPORT_GENERIC,
    VALID_EXPORT_PLATFORMS,
)
from giljo_mcp.template_renderer import (
    CODEX_TOML_FORMAT_REFERENCE,
    _slugify_filename,
    build_ownership_marker,
    hex_to_claude_color,
    inject_ownership_marker,
    inject_toml_ownership_marker,
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

# Separator between the agent name and the product slug in an exported filename.
# TWO hyphens, not one: agent names and product slugs both legitimately contain
# single hyphens ("implementer-backend", "acme-corp"), so a single-hyphen joiner
# would be unreadable and impossible to split back apart.
PRODUCT_QUALIFIER_SEPARATOR = "--"

# Install path metadata per platform lives on install_targets (BE-9385b moved it
# out of the PlatformRegistry, which sits at its size cap) -- single source for
# the per-platform agent-template install locations.


@dataclass(frozen=True)
class ExportContext:
    """Who this export belongs to (BE-9385b).

    Threaded from the export call sites, which know the tenant and can resolve the
    active product, down to the renderers, which know neither. Frozen because an
    assembler run must not be able to change whose export it is halfway through.

    Attributes:
        tenant_key: The exporting tenant. Carried in the marker so a file stays
            decisive under any future cross-tenant sharing -- one field now rather
            than a migration later.
        product_id: The active product. This is what makes install resolution
            possible: a file whose marker names a DIFFERENT product is a conflict
            to ask about, not a refresh to perform.
        product_slug: The stable slug qualifying filenames. Callers fall back to a
            slug derived from the product name for rows predating ce_0092.
    """

    tenant_key: str
    product_id: str
    product_slug: str


class AgentTemplateAssembler:
    """Assembles agent templates into platform-specific export format."""

    def assemble(
        self,
        templates: list[AgentTemplate],
        platform: str,
        *,
        export_context: ExportContext | None = None,
    ) -> dict:
        """Assemble templates into export response for the given platform.

        Args:
            templates: Pre-selected list of AgentTemplate model instances
                       (already filtered and capped by select_templates_for_packaging).
            platform: Target platform — 'claude_code', 'codex_cli', or 'gemini_cli'.
            export_context: BE-9385b — whose export this is. Supplying it turns on
                product-qualified filenames and ownership markers. ``None`` keeps
                the pre-BE-9385b output byte-for-byte, which is what the anonymous
                system-default download needs: no tenant, no product, so any marker
                would be a claim about nobody.

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
        return dispatch[platform](templates, export_context)

    # ------------------------------------------------------------------
    # Naming + marker helpers (BE-9385b), shared by every file-based platform
    # ------------------------------------------------------------------

    @staticmethod
    def _export_stem(template: AgentTemplate, ctx: ExportContext | None) -> str:
        """The filename stem: the agent's name, qualified by the product.

        The agent's own name always LEADS, so the user can still see what they
        installed; the product slug only disambiguates. Without a context the stem
        is the bare agent name -- byte-identical to the pre-BE-9385b export.
        """
        stem = _slugify_filename(template.name)
        if ctx and ctx.product_slug:
            stem = f"{stem}{PRODUCT_QUALIFIER_SEPARATOR}{ctx.product_slug}"
        return stem

    @staticmethod
    def _marked(
        content: str,
        template: AgentTemplate,
        ctx: ExportContext | None,
        *,
        toml: bool = False,
    ) -> str:
        """Return ``content`` stamped with its ownership marker, if there is one.

        The marker is built from the UNMARKED text so its hash describes the
        agent's content rather than itself, then injected -- which is why the two
        steps live together here and nowhere else.
        """
        if ctx is None:
            return content
        marker = build_ownership_marker(
            tenant_key=ctx.tenant_key,
            product_id=ctx.product_id,
            template_id=str(template.id),
            content=content,
        )
        return inject_toml_ownership_marker(content, marker) if toml else inject_ownership_marker(content, marker)

    # ------------------------------------------------------------------
    # Claude Code — pre-assembled markdown files with YAML frontmatter
    # ------------------------------------------------------------------

    def _assemble_claude(self, templates: list[AgentTemplate], ctx: ExportContext | None = None) -> dict:
        agents = []
        for t in templates:
            content = render_claude_agent(t)
            color = None
            if hasattr(t, "background_color") and t.background_color:
                color = hex_to_claude_color(t.background_color)

            agents.append(
                {
                    "filename": f"{self._export_stem(t, ctx)}.md",
                    "content": self._marked(content, t, ctx),
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

    def _assemble_gemini(self, templates: list[AgentTemplate], ctx: ExportContext | None = None) -> dict:
        agents = []
        for t in templates:
            content = render_gemini_agent(t)
            agents.append(
                {
                    "filename": f"{self._export_stem(t, ctx)}.md",
                    "content": self._marked(content, t, ctx),
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
    #
    # BE-9385b deliberately ships NO ownership marker here, and that is a decision
    # rather than an omission. `agy plugin validate` accepts ONLY the nested
    # `config.customAgent` shape (spike C2), so an extra top-level key risks
    # failing validation outright, and hiding the marker inside the agent's own
    # prompt would pollute its persona. The carve-out is safe because this whole
    # tree installs into a fixed GiljoAI-owned plugin root -- there are no
    # user-authored files in there to protect, which is the marker's entire job.
    # ------------------------------------------------------------------

    def _assemble_antigravity(self, templates: list[AgentTemplate], ctx: ExportContext | None = None) -> dict:
        agents = []
        for t in templates:
            agent_json = render_antigravity_agent(t)
            agents.append(
                {
                    "agent_dir": self._export_stem(t, ctx),
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

    def _assemble_codex(self, templates: list[AgentTemplate], ctx: ExportContext | None = None) -> dict:
        agents = []
        for t in templates:
            agent_data = render_codex_agent(t)
            # The marker travels as its own key rather than inside
            # developer_instructions: that text becomes the agent's operating
            # identity, and an installer's bookkeeping has no business in it.
            # file_staging renders it as the TOML file's leading comment.
            if ctx is not None:
                agent_data["giljo_marker"] = build_ownership_marker(
                    tenant_key=ctx.tenant_key,
                    product_id=ctx.product_id,
                    template_id=str(t.id),
                    content=str(agent_data.get("developer_instructions", "")),
                )
            agent_data["export_stem"] = self._export_stem(t, ctx)
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

    def _assemble_generic(self, templates: list[AgentTemplate], ctx: ExportContext | None = None) -> dict:
        agents = []
        for t in templates:
            content = render_generic_agent(t)
            agents.append(
                {
                    "filename": f"{self._export_stem(t, ctx)}.md",
                    "content": self._marked(content, t, ctx),
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
