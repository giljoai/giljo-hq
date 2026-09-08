# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Template rendering utilities for packaging/export (Claude Code, Gemini CLI, Codex CLI).

Implements 0102a/0103 rules for Claude Code agent templates:
- YAML frontmatter with: name, description, model, color (optional)
- Color field maps GiljoAI app colors to Claude Code named colors
- Omit tools to inherit all by default
- Body: system_instructions + optional Behavioral Rules / Success Criteria sections
- Packaging cap: max 16 active templates with precedence (BE-9208)
  1) user-created before is_default (defaults are a low-priority tiebreak only)
  2) updated_at (falling back to created_at) descending
  3) name ascending
  Over-cap templates are omitted with a WARNING log (no silent starvation).

Handover 0836a: Added render_gemini_agent() and render_codex_agent() for multi-platform export.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING

import yaml


if TYPE_CHECKING:
    from collections.abc import Iterable

from .branding import PRODUCT_NAME
from .models import AgentTemplate


logger = logging.getLogger(__name__)

# Single source of truth for the packaging cap. Raised 8 -> 16 (BE-9208):
# up to 16 enabled agents ship. Every export path relies on this default rather
# than passing its own literal, so the cap lives in exactly one place.
MAX_PACKAGED_TEMPLATES = 16


# BE-9275b: existing DB rows carry the OLD "GiljoAI MCP" bootstrap text until the
# ce_0085 heal migration runs (and a CE self-hoster may never run it before a
# render). Both markers/headings are recognized so old-shape and new-shape rows
# behave identically here -- only the seeded literal moved, not this tolerance.
_MCP_BOOTSTRAP_MARKER_OLD = "You are part of a GiljoAI MCP orchestration system"
_MCP_BOOTSTRAP_MARKER_NEW = f"You are part of a {PRODUCT_NAME} orchestration system"
_MCP_BOOTSTRAP_MARKERS = (_MCP_BOOTSTRAP_MARKER_OLD, _MCP_BOOTSTRAP_MARKER_NEW)
_MCP_BOOTSTRAP_END = "Do not begin work until you have received and read your mission and protocols"
_MCP_STARTUP_MARKER = "STARTUP (MANDATORY)"
_ROLE_BOUNDARY_HEADINGS_OLD_NEW = ("GiljoAI MCP Agent", f"{PRODUCT_NAME} Agent")
_ROLE_BOUNDARY_HEADING_RE = re.compile(
    r"(?m)^\s{0,3}#{1,3}\s+(?!"
    + "\\b|".join(re.escape(h) for h in _ROLE_BOUNDARY_HEADINGS_OLD_NEW)
    + r"\b|STARTUP \(MANDATORY\)\b).+"
)


def _normalize_instruction_text(text: str) -> str:
    """Normalize exported prompt text without changing markdown structure."""
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def _serve_bootstrap(stored_system_text: str | None) -> str:
    """Return the system-bootstrap text to serve, always fresh when applicable.

    BE-6231: the MCP startup bootstrap is system-owned (~10 identical lines for
    every template) and lives in ``AgentTemplate.system_instructions``. Serving
    the frozen DB copy let a stale tool name survive in downloaded agent files —
    after ``get_agent_mission`` was renamed to ``get_job_mission`` the stored
    bootstrap still instructed the dead tool. When the stored text IS that
    bootstrap (identified by the stable opening marker the dedup logic already
    relies on), regenerate it from the seed so served templates always reflect
    the current tool surface; this self-heals any future tool rename with no DB
    surgery. Non-bootstrap content (custom prose, test fixtures) is returned
    verbatim — only the system-owned bootstrap section is regenerated.
    """
    normalized = _normalize_instruction_text(stored_system_text or "")
    if any(marker in normalized for marker in _MCP_BOOTSTRAP_MARKERS):
        # Lazy import avoids a module-load cycle (template_seeder imports models).
        from .template_seeder import _get_mcp_bootstrap_section

        return _normalize_instruction_text(_get_mcp_bootstrap_section())
    return normalized


def _find_bootstrap_marker_index(text: str) -> int:
    """Return the index of whichever bootstrap marker (old or new shape) appears first, or -1."""
    indices = [idx for marker in _MCP_BOOTSTRAP_MARKERS if (idx := text.find(marker)) != -1]
    return min(indices) if indices else -1


def _remove_duplicate_mcp_bootstrap(system_text: str, user_text: str) -> str:
    """Remove legacy duplicated MCP startup prose from role instructions.

    Handover 0813 moved the startup bootstrap into system_instructions. Some
    existing template rows still carry an older copy at the start of
    user_instructions, which produces malformed Codex agent TOML exports.
    """
    if not any(marker in system_text for marker in _MCP_BOOTSTRAP_MARKERS):
        return user_text

    marker_index = _find_bootstrap_marker_index(user_text)
    if marker_index == -1:
        return user_text

    prefix = user_text[:marker_index].strip()
    allowed_prefixes = {f"# {h}" for h in _ROLE_BOUNDARY_HEADINGS_OLD_NEW} | {
        f"## {h}" for h in _ROLE_BOUNDARY_HEADINGS_OLD_NEW
    }
    if prefix and prefix not in allowed_prefixes:
        return user_text

    if _MCP_STARTUP_MARKER not in user_text[marker_index:]:
        return user_text

    end_index = user_text.find(_MCP_BOOTSTRAP_END, marker_index)
    if end_index != -1:
        line_end_index = user_text.find("\n", end_index)
        if line_end_index == -1:
            return ""
        return user_text[line_end_index + 1 :].lstrip()

    next_heading = _ROLE_BOUNDARY_HEADING_RE.search(user_text, marker_index)
    if not next_heading:
        return user_text

    return user_text[next_heading.start() :].lstrip()


def _build_role_prose(system_text: str, user_text: str) -> str:
    """Return role prose safe for export beside the shared MCP bootstrap."""
    normalized = _normalize_instruction_text(user_text)
    if not normalized:
        return ""
    deduped = _remove_duplicate_mcp_bootstrap(system_text, normalized)
    return _normalize_instruction_text(deduped)


def _slugify_filename(name: str) -> str:
    """Return a safe slug filename (keeps existing slug if already valid)."""
    slug = name.strip().lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9._-]", "-", slug)
    # collapse multiple dashes
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "agent"


# ---------------------------------------------------------------------------
# Ownership marker (BE-9385b)
#
# Every exported agent file says, in its own bytes, that GiljoAI produced it and
# which product it belongs to. That is what lets an install overwrite ITS OWN
# files while leaving a user's hand-written agents alone -- the distinction the
# old whole-directory "Overwrite (all) / Skip (all)" prompt could not make, and
# the reason answering "Overwrite" used to destroy user-authored agents.
#
# THE MARKER IS RENDER-TIME ONLY AND MUST NEVER BE PERSISTED. The ce_0049 /
# ce_0084 / ce_0085 / ce_0090 heal migrations repair seeded templates by comparing
# stored text against a byte-exact literal; a marker written into
# ``system_instructions`` would make every one of those comparisons miss, and a
# self-hoster's templates would silently stop healing on upgrade -- a failure that
# surfaces releases later, in someone else's install, with nothing pointing back
# here. So the functions below take text and RETURN text; nothing in this module
# writes to a template row, and
# ``test_be9385b_collision_safe_export_mcp_boundary.py`` asserts the columns stay
# clean after an export.
# ---------------------------------------------------------------------------

OWNERSHIP_MARKER_TOKEN = "giljo-managed:"

# Truncated SHA-256. Not a security boundary -- it answers "is the installed copy
# still what the server rendered?", so an installer can skip an unchanged file
# instead of rewriting it. 16 hex chars is ample for that and keeps the marker on
# one readable line.
_MARKER_HASH_CHARS = 16


def build_ownership_marker(
    *,
    tenant_key: str,
    product_id: str,
    template_id: str,
    content: str,
) -> str:
    """Return the marker payload for ``content``.

    Key ORDER is fixed rather than dict-dependent so golden tests stay stable and
    two renders of the same agent produce byte-identical markers.

    The hash covers ``content`` as rendered **before** the marker is injected --
    it has to, or it would be hashing itself. Callers therefore build the marker
    from the un-marked text and inject afterwards, which
    :func:`inject_ownership_marker` enforces by construction (it takes both).
    """
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:_MARKER_HASH_CHARS]
    return f"{OWNERSHIP_MARKER_TOKEN} v1 tenant={tenant_key} product={product_id} template={template_id} hash={digest}"


def inject_ownership_marker(content: str, marker: str) -> str:
    """Return ``content`` with ``marker`` as an HTML comment in the body.

    Placed as the first body line, AFTER any YAML frontmatter -- never inside it.
    A ``giljo:`` key in frontmatter would be at the mercy of each harness's agent
    schema validator (Gemini's is stricter than Claude Code's, and we cannot test
    against it from here); an HTML comment is inert in every Markdown renderer,
    trivially greppable by the installing agent, and cannot collide with a schema.
    """
    line = f"<!-- {marker} -->"
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            close = end + len("\n---\n")
            return content[:close] + line + "\n" + content[close:]
    # No frontmatter (the generic renderer): the marker leads the document.
    return f"{line}\n{content}"


def inject_toml_ownership_marker(content: str, marker: str) -> str:
    """Return ``content`` with ``marker`` as a leading TOML comment.

    TOML comments are legal anywhere, so line 1 is both the most visible place and
    the cheapest for an installer to read without parsing the file.
    """
    return f"# {marker}\n{content}"


def hex_to_claude_color(hex_code: str | None) -> str | None:
    """Convert hex color code to Claude Code named color.

    Maps GiljoAI app colors to Claude Code CLI color names.
    Returns None if no mapping exists (color field will be omitted).

    Supported Claude Code colors: green, blue, purple, orange, red, yellow, grey

    Args:
        hex_code: Hex color code (e.g., "#3498DB") or None

    Returns:
        Claude Code named color or None
    """
    if not hex_code:
        return None

    # Normalize hex code (uppercase, ensure # prefix)
    normalized = hex_code.strip().upper()
    if not normalized.startswith("#"):
        normalized = f"#{normalized}"

    # Map GiljoAI app colors to Claude Code named colors
    color_map = {
        # Orchestrator - tan/bronze -> orange
        "#D4A574": "orange",
        # Implementer/Frontend - blue
        "#3498DB": "blue",
        # Tester - yellow/gold
        "#FFC300": "yellow",
        # Analyzer - red
        "#E74C3C": "red",
        # Reviewer/Designer - purple
        "#9B59B6": "purple",
        # Documenter/Backend - green
        "#27AE60": "green",
        "#2ECC71": "green",
        # Default/fallback - grey
        "#90A4AE": "grey",
    }

    return color_map.get(normalized)


def render_claude_agent(template: AgentTemplate) -> str:
    """Render a single AgentTemplate to Claude Code-compatible Markdown.

    Handover 0813: Now includes user_instructions (role identity prose) in the body.
    Structure: frontmatter + system_instructions (slim bootstrap) + user_instructions
    (role prose) + behavioral_rules + success_criteria.

    Rules per 0102a:
    - Frontmatter includes name, description, model (omit tools to inherit all)
    - Description fallback: "Subagent for <role>"
    - Model default: 'opus' if blank; allow 'inherit' if explicitly set
    """
    description = template.description or (f"Subagent for {template.role}" if template.role else "Subagent")
    # Respect explicit 'inherit'; otherwise default to opus when blank
    model_value = (template.model or "opus").strip()

    frontmatter = {
        "name": template.name,
        "description": description,
        "model": model_value,
    }

    # Include color field — use background_color from DB, fall back to role-based color
    bg_color = getattr(template, "background_color", None) or None
    if not bg_color and template.role:
        from .template_validation import get_role_color

        bg_color = get_role_color(template.role)
    if bg_color:
        claude_color = hex_to_claude_color(bg_color)
        if claude_color:
            frontmatter["color"] = claude_color

    # Include tools only when explicitly specified (inherit all otherwise)
    tools_field = (template.tools or "").strip() if hasattr(template, "tools") else ""
    if tools_field:
        # Normalize spacing (store as comma-separated string)
        tools_line = ", ".join([part.strip() for part in tools_field.split(",") if part.strip()])
        if tools_line:
            # Render as plain YAML string per 0102a
            frontmatter["tools"] = tools_line

    yaml_header = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()

    parts: list[str] = []

    # Slim bootstrap (system_instructions -- now ~5-10 lines, Handover 0813).
    # BE-6231: regenerated fresh at serve time when it is the system-owned bootstrap.
    bootstrap = _serve_bootstrap(template.system_instructions)
    if bootstrap:
        parts.append(bootstrap)

    # Role identity prose (user_instructions -- Handover 0813: now included!)
    role_prose = _build_role_prose(bootstrap, template.user_instructions or "")
    if role_prose:
        parts.append(f"\n{role_prose}")

    # Behavioral Rules section
    rules = template.behavioral_rules or []
    if isinstance(rules, list) and rules:
        parts.append("\n## Behavioral Rules")
        parts.extend(f"- {r}" for r in rules)

    # Success Criteria section
    criteria = template.success_criteria or []
    if isinstance(criteria, list) and criteria:
        parts.append("\n## Success Criteria")
        parts.extend(f"- {c}" for c in criteria)

    body_text = "\n".join(parts).rstrip() + "\n"
    return f"---\n{yaml_header}\n---\n\n{body_text}"


def select_templates_for_packaging(
    templates: Iterable[AgentTemplate], max_count: int = MAX_PACKAGED_TEMPLATES
) -> list[AgentTemplate]:
    """Select up to max_count templates using precedence rules.

    No role-based deduplication - the enabled (is_active) set is the source of
    truth; users control which templates ship via the UI toggle. The max_count
    cap (default MAX_PACKAGED_TEMPLATES) prevents context budget overflow.

    Precedence order (BE-9208 — user-created must never be starved by the seeded
    defaults):
      1) user-created before is_default (defaults are a low-priority TIEBREAK only)
      2) updated_at (falling back to created_at) descending (most recent first)
      3) name ascending (stable fallback)

    When the active set exceeds the cap, the omitted templates are logged at
    WARNING (their names) so the omission is surfaced, never silent.
    """

    # Ascending sort (no reverse), so each term controls its own direction:
    #  - is_default False (0) sorts before True (1) -> user-created win.
    #  - negative recency sorts most-recent first (updated_at, else created_at).
    #  - name ascending as the final stable tiebreak.
    def sort_key(t: AgentTemplate):
        is_default = bool(getattr(t, "is_default", False))
        modified = getattr(t, "updated_at", None) or getattr(t, "created_at", None)
        neg_recency = -modified.timestamp() if modified else float("inf")
        return (is_default, neg_recency, (t.name or ""))

    sorted_list = sorted(templates, key=sort_key)

    if len(sorted_list) > max_count:
        omitted = sorted_list[max_count:]
        logger.warning(
            "Template packaging cap reached: %d active templates exceed the cap of %d; "
            "shipping the %d highest-precedence (user-created preferred), omitting %d: %s",
            len(sorted_list),
            max_count,
            max_count,
            len(omitted),
            ", ".join(t.name or "<unnamed>" for t in omitted),
        )

    return sorted_list[:max_count]


def _build_body_parts(template: AgentTemplate) -> list[str]:
    """Build the shared body content parts used by all renderers.

    Returns list of text parts: system_instructions, user_instructions,
    behavioral_rules, success_criteria.
    """
    parts: list[str] = []

    # BE-6231: regenerated fresh at serve time when it is the system-owned bootstrap.
    bootstrap = _serve_bootstrap(template.system_instructions)
    if bootstrap:
        parts.append(bootstrap)

    role_prose = _build_role_prose(bootstrap, template.user_instructions or "")
    if role_prose:
        parts.append(f"\n{role_prose}")

    rules = template.behavioral_rules or []
    if isinstance(rules, list) and rules:
        parts.append("\n## Behavioral Rules")
        parts.extend(f"- {r}" for r in rules)

    criteria = template.success_criteria or []
    if isinstance(criteria, list) and criteria:
        parts.append("\n## Success Criteria")
        parts.extend(f"- {c}" for c in criteria)

    return parts


def render_generic_agent(template: AgentTemplate) -> str:
    """Render agent template to platform-neutral Markdown.

    Produces plain Markdown without YAML/TOML frontmatter, suitable for
    any MCP client that doesn't match a known platform profile.

    Args:
        template: AgentTemplate model instance

    Returns:
        Markdown content without platform-specific frontmatter
    """
    description = template.description or (f"Subagent for {template.role}" if template.role else "Subagent")

    parts = [
        f"# {template.name}",
        "",
        f"**Role:** {template.role or 'agent'}",
        f"**Description:** {description}",
    ]

    # BE-6231: regenerated fresh at serve time when it is the system-owned bootstrap.
    bootstrap = _serve_bootstrap(template.system_instructions)
    if bootstrap:
        parts.append("")
        parts.append("## System Instructions")
        parts.append("")
        parts.append(bootstrap)

    role_prose = (template.user_instructions or "").strip()
    if role_prose:
        parts.append("")
        parts.append("## User Instructions")
        parts.append("")
        parts.append(role_prose)

    rules = template.behavioral_rules or []
    if isinstance(rules, list) and rules:
        parts.append("")
        parts.append("## Behavioral Rules")
        parts.append("")
        parts.extend(f"- {r}" for r in rules)

    criteria = template.success_criteria or []
    if isinstance(criteria, list) and criteria:
        parts.append("")
        parts.append("## Success Criteria")
        parts.append("")
        parts.extend(f"- {c}" for c in criteria)

    return "\n".join(parts) + "\n"


def render_gemini_agent(template: AgentTemplate) -> str:
    """Render a single AgentTemplate to Gemini CLI-compatible Markdown.

    Gemini CLI uses YAML frontmatter with a different schema than Claude Code:
    - name, description, kind, model, max_turns
    - kind must be 'local' (not 'agent') — matches built-in agent format
    - No color support (Gemini doesn't support agent colors)

    Deliberately NOT emitted: ``tools``. Verified against the google-gemini/gemini-cli
    ``main`` branch on 2026-09-03 (packages/core/src/agents/local-executor.ts:247-266):
    when the frontmatter's ``tools`` key is absent, ``toolConfig`` is ``undefined`` and
    the executor takes the ``else`` branch -- ``for (const toolName of
    parentToolRegistry.getAllToolNames()) { registerToolByName(toolName); }`` -- so the
    subagent inherits every parent tool, MCP servers included. A hand-maintained
    allowlist can only narrow that, and BE-9567 found it had already silently drifted
    to zero: entries used the pre-rename ``giljo_mcp`` alias while the live MCP server
    is ``giljo_hq``, and one entry named a tool BE-9554 retired. Gemini CLI has no
    registry-aware validation to catch this -- ``isValidToolName``
    (packages/core/src/tools/tool-names.ts) checks FORM ONLY, and
    ``registerToolByName``'s ``parentToolRegistry.getTool(toolName)`` lookup is a bare
    ``if`` with no ``else``, so an unregistered name is silently dropped and the model
    never learns it existed -- no error surfaces anywhere. Mirrors the reasoning
    already recorded on ``render_opencode_agent`` below, and the BE-9563
    slash-command precedent of routing tool access through server-side resolution
    (or, here, platform inheritance) instead of a shipped roster that can only go
    stale.

    Handover 0836a: Multi-platform agent export.
    Handover 0836d: Fixed kind (local), tool names (run_shell_command), added
    file/search tools per Gemini CLI documentation. Superseded by BE-9567
    (2026-09-03): the explicit tools list resolved to nothing (see above) and was
    removed outright rather than repaired.
    """
    description = template.description or (f"Subagent for {template.role}" if template.role else "Subagent")

    frontmatter: dict[str, object] = {
        "name": template.name,
        "description": description,
        "kind": "local",
        "model": "inherit",
        "max_turns": 50,
    }

    yaml_header = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()

    body_parts = _build_body_parts(template)
    body_text = "\n".join(body_parts).rstrip() + "\n"
    return f"---\n{yaml_header}\n---\n\n{body_text}"


def render_opencode_agent(template: AgentTemplate) -> str:
    """Render a single AgentTemplate to an opencode agent Markdown file.

    opencode reads ``~/.config/opencode/agents/<name>.md`` (PLURAL -- the
    singular ``agent/`` is never read, and installing there looks successful
    while doing nothing). The FILENAME is the agent identifier, so the
    frontmatter carries no ``name`` field, unlike Claude Code and Gemini.

    Frontmatter verified empirically against opencode 1.18.22 on 2026-08-25 --
    a probe agent in exactly this shape was both DISCOVERED and SPAWNED, and
    returned its sentinel:

    * ``description`` -- required. opencode advertises this to the model when it
      decides whether to delegate, so it must read as a capability, not a title.
    * ``mode`` -- required: ``subagent`` (delegated to), ``primary``
      (user-selectable) or ``all``. Every Giljo role ships as ``subagent``: the
      orchestrator delegates to them, which is the whole execution model, and a
      primary-mode specialist would clutter the picker with roles a human never
      drives directly.
    * ``temperature`` -- optional, kept low for determinism, mirroring the other
      renderers' bias toward reproducible agent behaviour.

    Deliberately NOT emitted: ``model`` (inherit the session's -- a pinned model
    would fight the user's own provider config, and opencode users commonly run
    local gateways), ``tools``/``permission`` (opencode has no Giljo-specific
    tool-name vocabulary to allowlist the way Gemini does, and an incomplete
    allowlist silently disables MCP tools the worker protocol needs), and
    ``color`` (no Claude-style palette mapping exists here).
    """
    description = template.description or (f"Subagent for {template.role}" if template.role else "Subagent")

    frontmatter: dict[str, object] = {
        "description": description,
        "mode": "subagent",
        "temperature": 0.1,
    }

    yaml_header = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()

    body_parts = _build_body_parts(template)
    body_text = "\n".join(body_parts).rstrip() + "\n"
    return f"---\n{yaml_header}\n---\n\n{body_text}"


def render_codex_agent(template: AgentTemplate) -> dict[str, object]:
    """Render a single AgentTemplate to Codex CLI structured data.

    Codex AI coding agents are installed as standalone TOML files under
    ~/.codex/agents/. Model and reasoning are intentionally omitted from the
    structured data so generated TOML inherits the parent Codex session unless
    a user explicitly chooses per-agent overrides.

    Handover 0836a: Multi-platform agent export.
    """
    description = template.description or (f"Subagent for {template.role}" if template.role else "Subagent")

    body_parts = _build_body_parts(template)
    developer_instructions = "\n".join(body_parts).rstrip()

    return {
        "agent_name": template.name,
        "description": description,
        "role": template.role or "agent",
        "developer_instructions": developer_instructions,
    }


# Antigravity CLI (`agy`) — net-new nested agent.json (NOT an alias of the Gemini
# markdown-frontmatter renderer). Spike C2 (SOW §4 Q5, 2026-06-09) confirmed the
# `agy plugin validate` schema accepts ONLY the nested `config.customAgent` form;
# flat `systemPrompt`/markdown-frontmatter agents are ignored by the validator.
_ANTIGRAVITY_AGENT_TOOL_NAMES = [
    "read_url_content",
    "search_web",
    "view_file",
    "list_dir",
    "grep_search",
    "write_file",
    "run_command",
]

_ANTIGRAVITY_PROMPT_SECTIONS = [
    "user_information",
    "mcp_servers",
    "skills",
    "messaging",
    "user_rules",
]


def render_antigravity_agent(template: AgentTemplate) -> dict[str, object]:
    """Render a single AgentTemplate to an Antigravity (`agy`) ``agent.json`` dict.

    Antigravity custom agents load ONLY from an installed plugin and use a nested
    ``config.customAgent`` schema (spike C2 / SOW §4 Q5, 2026-06-09):

        {
          "name": "<agent_name>",
          "description": "...",
          "config": {
            "customAgent": {
              "systemPromptSections": [{"title": "...", "content": "...persona..."}],
              "toolNames": [...],
              "systemPromptConfig": {"includeSections": [..., "mcp_servers", ...]}
            }
          }
        }

    ``includeSections`` carrying ``mcp_servers`` is what wires the agent to the
    connected ``giljo_mcp`` tools. This is net-new (NOT ``render_gemini_agent``):
    the Gemini markdown-frontmatter format is ignored by the agy validator.
    """
    description = template.description or (f"Subagent for {template.role}" if template.role else "Subagent")

    body_parts = _build_body_parts(template)
    persona = "\n".join(body_parts).rstrip()

    return {
        "name": template.name,
        "description": description,
        "config": {
            "customAgent": {
                "systemPromptSections": [
                    {"title": "Agent System Instructions", "content": persona},
                ],
                "toolNames": list(_ANTIGRAVITY_AGENT_TOOL_NAMES),
                "systemPromptConfig": {"includeSections": list(_ANTIGRAVITY_PROMPT_SECTIONS)},
            }
        },
    }


def render_plugin_manifest(
    name: str,
    version: str,
    description: str,
) -> dict[str, str]:
    """Render an Antigravity ``plugin.json`` manifest.

    Spike C2 (SOW §4 Q4) confirmed the minimal valid manifest is exactly
    ``{"name", "version", "description"}``; ``agy plugin validate`` requires
    ``plugin.json`` at the plugin-dir root, then scans the component slots
    (``agents/``, ``skills/``, ``commands/``, ``mcpServers``, ``hooks/``).
    """
    return {
        "name": name,
        "version": version,
        "description": description,
    }


# TOML format reference string for Codex AI coding agent configuration
CODEX_TOML_FORMAT_REFERENCE = """\
# Codex AI coding agent file (install as ~/.codex/agents/gil-implementer.toml)
# Current Codex releases discover standalone TOML files in ~/.codex/agents/
# and do not require per-agent registrations in config.toml.
#
# name = "gil-implementer"
# description = "Implementation specialist for writing production-grade code"
# nickname_candidates = ["gil-implementer"]
# developer_instructions = "..."
#
# Omit model and model_reasoning_effort to inherit the parent Codex session.
# ~/.codex/config.toml remains optional for global [agents] settings.
"""


def render_template(template: AgentTemplate) -> str:
    """Render template based on cli_tool field.

    Dispatcher function that routes to appropriate renderer:
    - 'claude' → render_claude_agent() (YAML format)
    - 'codex', 'gemini', 'antigravity', 'generic' → render_generic_agent() (plaintext)
    - None or unknown → fallback to render_claude_agent()

    Args:
        template: AgentTemplate model instance

    Returns:
        Rendered content in appropriate format
    """
    cli_tool = (template.cli_tool or "").lower()

    if cli_tool == "claude":
        return render_claude_agent(template)
    if cli_tool in ("codex", "gemini", "antigravity", "generic"):
        return render_generic_agent(template)
    # Fallback to Claude format for backwards compatibility
    return render_claude_agent(template)


__all__ = [
    "CODEX_TOML_FORMAT_REFERENCE",
    "OWNERSHIP_MARKER_TOKEN",
    "_slugify_filename",
    "build_ownership_marker",
    "hex_to_claude_color",
    "inject_ownership_marker",
    "inject_toml_ownership_marker",
    "render_antigravity_agent",
    "render_claude_agent",
    "render_codex_agent",
    "render_gemini_agent",
    "render_generic_agent",
    "render_plugin_manifest",
    "render_template",
    "select_templates_for_packaging",
]
