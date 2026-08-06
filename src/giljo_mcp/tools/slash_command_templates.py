# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Slash command templates for Claude Code, Codex CLI, Gemini CLI, and Antigravity.

INF-6049a: the per-platform fleet (`gil_add` / `gil_get` / `gil_chain` /
`gil_get_reference` / `gil_get_agents`) was collapsed to ONE thin command per
platform -- `/giljo` -- whose entire job is to call the `get_giljo_guide` MCP
tool (BE-9012d, F1: bare -- this body renders to Codex/Gemini/Desktop too, where
the Claude Code `mcp__giljo_hq__` prefix is wrong) and follow what it returns.
The routing/judgment that used to live in N markdown bodies now lives server-side
in that one tool (see ``giljo_guide.py``), so the shipped command stays a 1-liner
and never drifts. Agent-template installs/refreshes are handled by the
``giljo_setup`` tool (its "Agents only" scope), not a separate command.

This module also provides bootstrap prompt templates for one-time CLI onboarding.
"""

from __future__ import annotations

from giljo_mcp import branding
from giljo_mcp.platform_registry import (
    EXPORT_ANTIGRAVITY_CLI,
    EXPORT_CLAUDE_CODE,
    EXPORT_CODEX_CLI,
    EXPORT_GEMINI_CLI,
    EXPORT_GENERIC,
    EXPORT_PLATFORMS,
)


# Semver for the skills/commands package. Bumped when slash command templates change.
# Referenced by health_check so the frontend can compare installed vs available.
SKILLS_VERSION = "1.1.21"


# =============================================================================
# THE ONE COMMAND -- /giljo (every platform). Body = "call get_giljo_guide".
# =============================================================================

_GILJO_DESCRIPTION = (
    "GiljoAI dashboard -- create, read, and update projects and tasks (and chains). "
    "Loads the server-side routing guide, then acts."
)

# Shared instruction body (platform-neutral). Command invocation differs by
# platform (/giljo vs $giljo) but the instruction is identical.
_GILJO_BODY = (
    f"This command is a thin entry point to {branding.PRODUCT_NAME}. Do this every time:\n"
    "\n"
    "1. Call the `get_giljo_guide` tool (no arguments; your MCP client may expose it\n"
    "   under a prefix, e.g. `mcp__<server>__get_giljo_guide` -- use the name your\n"
    "   harness lists).\n"
    "2. Follow what it returns -- it is the single source of truth for:\n"
    "   - project-vs-task routing (create_project vs create_task),\n"
    "   - the chain convention (one shared series_number + a/b/c suffixes for ordered,\n"
    "     dependent steps),\n"
    "   - the mandatory `Edition Scope: CE | SaaS | Both` line on every project,\n"
    "   - read-vs-write routing (reads: list_projects / list_tasks / get_context;\n"
    "     writes: create_* / update_*; never pass tenant_key; an active product is required),\n"
    "   - the staging -> human-gate -> implement lifecycle.\n"
    f"3. Then carry out the user's request with the {branding.PRODUCT_NAME} tools.\n"
    "\n"
    "To install or refresh GiljoAI agent templates, run the `giljo_setup` tool and choose\n"
    '"Agents only" -- there is no separate agents command.'
)


GILJO_CLAUDE_MD = f"""---
description: "{_GILJO_DESCRIPTION}"
---

# /giljo -- {branding.PRODUCT_NAME} commands

{_GILJO_BODY}
"""


GILJO_GEMINI_TOML = f"""description = "{_GILJO_DESCRIPTION}"

prompt = '''
# /giljo -- {branding.PRODUCT_NAME} commands

{_GILJO_BODY}
'''
"""


GILJO_SKILL_MD = f"""---
name: giljo
description: "{_GILJO_DESCRIPTION}"
---

# $giljo -- {branding.PRODUCT_NAME} commands

{_GILJO_BODY}
"""


# =============================================================================
# BOOTSTRAP PROMPT TEMPLATES (one-time CLI onboarding -> /api/download/bootstrap-prompt)
# =============================================================================

BOOTSTRAP_CLAUDE_CODE = """Install the GiljoAI CLI command. This is a one-time setup.

Step 1 — Install the slash command:
Download: {SLASH_COMMANDS_URL}
Extract to: ~/.claude/commands/ (create if needed, overwrite existing)
Delete the downloaded zip.

Adapt all commands for the OS you are running on.
After installation, tell the user:
One command is now available:
- /giljo — create/read/update projects and tasks (it loads the GiljoAI guide, then acts)

To install GiljoAI agent templates, run the giljo_setup tool and choose "Agents only".
Restart Claude Code.
Note: Download link expires in 15 minutes.
"""

BOOTSTRAP_GEMINI_CLI = """Install the GiljoAI CLI command. This is a one-time setup.

Step 1 — Install the custom command:
Download: {SLASH_COMMANDS_URL}
Extract to: ~/.gemini/commands/ (create if needed, overwrite existing)
Delete the downloaded zip.

Adapt all commands for the OS you are running on.
After installation, tell the user:
One command is now available:
- /giljo — create/read/update projects and tasks (it loads the GiljoAI guide, then acts)

To install GiljoAI agent templates, run the giljo_setup tool and choose "Agents only".
Restart Gemini CLI.
Note: Download link expires in 15 minutes.
"""

BOOTSTRAP_CODEX_CLI = """Install the GiljoAI CLI skill. This is a one-time setup.

Step 1 — Install the skill:
Download: {SKILLS_URL}
Extract to: ~/.codex/skills/ (create if needed, overwrite existing)
Delete the downloaded zip.

Step 2 — Leave Codex feature flags unchanged:
Current Codex releases enable subagent workflows by default, so this setup does not need
multi_agent or default_mode_request_user_input in ~/.codex/config.toml.

Adapt all commands for the OS you are running on.
After installation, tell the user:
One skill is now available:
- $giljo — create/read/update projects and tasks (it loads the GiljoAI guide, then acts)

To install GiljoAI agent templates, run the giljo_setup tool and choose "Agents only".
Restart Codex CLI.
Note: Download link expires in 15 minutes.
"""

BOOTSTRAP_GENERIC = """Your CLI platform was not auto-detected. Visit your GiljoAI server's
Tools -> Connect page to download the GiljoAI command reference file.
Install it according to your tool's documentation. Its job is to call the
get_giljo_guide tool and follow it (your MCP client may expose it under a
prefix, e.g. mcp__<server>__get_giljo_guide — use the name your harness lists).
To install agent templates, run the giljo_setup tool and choose "Agents only".
"""

BOOTSTRAP_ANTIGRAVITY_CLI = """Install the GiljoAI integration for Antigravity CLI (agy). This is a one-time setup.

agy loads agents and skills ONLY from an installed plugin (not loose files). The
GiljoAI bundle is one plugin tree: plugin.json + agents/<name>/agent.json +
skills/<name>/SKILL.md, registered with `agy plugin install`.

Step 1 — Download the plugin bundle:
Download: {SLASH_COMMANDS_URL}
Extract it so the plugins/giljoai/ tree lands at ~/.gemini/config/plugins/giljoai/
(create ~/.gemini/config/plugins/ if needed). Keep the nested layout — do NOT
flatten it. Delete the downloaded zip.

Step 2 — Validate and install the plugin:
  agy plugin validate ~/.gemini/config/plugins/giljoai
  agy plugin install ~/.gemini/config/plugins/giljoai
Do NOT add experimental.enableAgents to any settings file — that flag is
Gemini-CLI-only and is not used by agy.

Step 3 — Connect agy to the Giljo HQ server:
Visit your GiljoAI server's Tools -> Connect page, choose Antigravity CLI, and
copy the mcp_config.json snippet into ~/.gemini/config/mcp_config.json.
IMPORTANT — if migrating an existing config from Gemini CLI: agy uses the
`serverUrl` field, NOT `url`. A leftover `url` line causes a silent failure
(the server lists in the UI but the agent cannot use it). Delete any `url` line.

Step 4 — Restart agy. The GiljoAI agents and the $giljo skill are now available.
To refresh agent templates later, run the giljo_setup tool and choose "Agents only".
Note: Download link expires in 15 minutes.
"""

# =============================================================================
# HELPERS
# =============================================================================


def _strip_yaml_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (between --- markers) from Markdown content."""
    stripped = content.strip()
    if stripped.startswith("---"):
        end = stripped.find("---", 3)
        if end != -1:
            return stripped[end + 3 :].strip()
    return stripped


# Once-per-session in-chat nudge appended to every generated skill body. The
# skill compares the server-reported version (MCP tool ``_meta.skills_version``)
# against ``bundle_version`` in its own frontmatter and, at most once per chat
# session, advises the user to re-run /giljo_setup when the server is newer.
_BUNDLE_NUDGE_LINE = (
    "## Skills bundle freshness (check once per session)\n"
    "\n"
    f"This skill was generated from GiljoAI skills bundle `bundle_version: {SKILLS_VERSION}`.\n"
    f"Any {branding.PRODUCT_NAME} tool response includes `_meta.skills_version` (the version the server "
    f"currently ships). The FIRST time in a chat session that you call a {branding.PRODUCT_NAME} tool, "
    "compare that `_meta.skills_version` to this file's `bundle_version`. If the server's "
    'version is newer, tell the user once: "Your GiljoAI skills are out of date — run '
    '/giljo_setup to update." Do not repeat this notice again in the same session, and never '
    "block the user's actual request on it.\n"
)


def _stamp_bundle_version(filename: str, content: str) -> str:
    """Stamp ``bundle_version`` + the once-per-session nudge into a template.

    Format-aware (single write path for all generated skills):

    - ``.toml`` (Gemini): inject ``bundle_version = "X"`` after the leading
      ``description = ...`` line, and append the nudge inside the ``prompt``
      triple-quoted block.
    - ``.md`` with YAML frontmatter: inject ``bundle_version: X`` into the
      frontmatter and append the nudge to the body.
    - ``.md`` without frontmatter (reference files): prepend a minimal
      frontmatter block carrying ``bundle_version`` and append the nudge.
    """
    if filename.endswith(".toml"):
        return _stamp_toml(content)
    return _stamp_markdown(content)


def _stamp_toml(content: str) -> str:
    lines = content.split("\n")
    out: list[str] = []
    injected = False
    for line in lines:
        out.append(line)
        if not injected and line.lstrip().startswith("description ="):
            out.append(f'bundle_version = "{SKILLS_VERSION}"')
            injected = True
    stamped = "\n".join(out)

    # Append the nudge inside the prompt triple-quoted block (before its close).
    marker = "'''"
    last = stamped.rfind(marker)
    if last != -1:
        nudge = "\n" + _BUNDLE_NUDGE_LINE
        stamped = stamped[:last] + nudge + stamped[last:]
    return stamped


def _stamp_markdown(content: str) -> str:
    stripped = content.lstrip("\n")
    if stripped.startswith("---"):
        end = stripped.find("\n---", 3)
        if end != -1:
            close = stripped.find("\n", end + 1)
            frontmatter = stripped[:end]
            rest = stripped[close + 1 :] if close != -1 else ""
            body = f"---{frontmatter[3:]}\nbundle_version: {SKILLS_VERSION}\n---\n{rest}"
            return body.rstrip() + "\n\n" + _BUNDLE_NUDGE_LINE

    # No frontmatter: prepend a minimal block so the version is machine-readable.
    front = f"---\nbundle_version: {SKILLS_VERSION}\n---\n\n"
    return front + content.rstrip() + "\n\n" + _BUNDLE_NUDGE_LINE


# =============================================================================
# TEMPLATE REGISTRY
# =============================================================================

# BE-6117: the export-platform vocabulary is owned by the PlatformRegistry.
# Re-exported here so existing importers (file_staging) keep resolving the name.
_VALID_PLATFORMS = EXPORT_PLATFORMS


def get_all_templates(platform: str = "claude_code") -> dict[str, str]:
    """Return the GiljoAI command/skill template(s) for the given platform.

    INF-6049a: exactly ONE file per platform -- the thin ``/giljo`` command whose
    body calls ``get_giljo_guide`` (bare -- see ``_GILJO_BODY``).

    Args:
        platform: Target CLI platform. One of ``_VALID_PLATFORMS``.

    Returns:
        dict[str, str]: Mapping of filename to (bundle-version-stamped) content.

    Raises:
        ValueError: If platform is not recognized.
    """
    if platform not in _VALID_PLATFORMS:
        raise ValueError(f"Unknown platform '{platform}'. Must be one of: {', '.join(_VALID_PLATFORMS)}")

    # BE-6117: dict dispatch keyed off the registry's export vocabulary, replacing
    # the if/elif-on-bare-literal chain. Codex and Antigravity both load nested
    # <name>/SKILL.md skills invoked with a `$` prefix; generic is platform-neutral
    # reference markdown (frontmatter stripped).
    templates_by_platform = {
        EXPORT_CLAUDE_CODE: {"giljo.md": GILJO_CLAUDE_MD},
        EXPORT_GEMINI_CLI: {"giljo.toml": GILJO_GEMINI_TOML},
        EXPORT_CODEX_CLI: {"giljo/SKILL.md": GILJO_SKILL_MD},
        EXPORT_ANTIGRAVITY_CLI: {"giljo/SKILL.md": GILJO_SKILL_MD},
        EXPORT_GENERIC: {"giljo_reference.md": _strip_yaml_frontmatter(GILJO_CLAUDE_MD)},
    }
    templates = templates_by_platform[platform]

    # Stamp bundle_version + the once-per-session nudge into every generated file
    # (single write path), so each installed file is self-describing and can
    # compare itself against the server's `_meta.skills_version`.
    return {name: _stamp_bundle_version(name, content) for name, content in templates.items()}
