# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp import branding
from giljo_mcp.platform_registry import (
    EXPORT_CLAUDE_CODE,
    EXPORT_CODEX_CLI,
    EXPORT_GENERIC,
    EXPORT_OPENCODE,
    EXPORT_PLATFORMS,
)


SKILLS_VERSION = "1.1.21"



_GILJO_DESCRIPTION = (
    f"{branding.PRODUCT_NAME} dashboard -- create, read, and update projects and tasks "
    "(and chains). Loads the server-side routing guide, then acts."
)

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
    f"{branding.PRODUCT_NAME} agent templates are never installed as files: every spawned "
    "agent receives its full profile from the server when its job starts."
)


GILJO_CLAUDE_MD = f"""---
description: "{_GILJO_DESCRIPTION}"
---

# /giljo -- {branding.PRODUCT_NAME} commands

{_GILJO_BODY}
"""


GILJO_OPENCODE_MD = GILJO_CLAUDE_MD


GILJO_SKILL_MD = f"""---
name: giljo
description: "{_GILJO_DESCRIPTION}"
---

# $giljo -- {branding.PRODUCT_NAME} commands

{_GILJO_BODY}
"""



BOOTSTRAP_CLAUDE_CODE = f"""Install the {branding.PRODUCT_NAME} CLI command. This is a one-time setup.

Step 1 — Install the slash command:
Download: {{SLASH_COMMANDS_URL}}
Extract to: ~/.claude/commands/ (create if needed, overwrite existing)
Delete the downloaded zip.

Adapt all commands for the OS you are running on.
After installation, tell the user:
One command is now available:
- /giljo — create/read/update projects and tasks (it loads the {branding.PRODUCT_NAME} guide, then acts)

Agent templates are not installed as files: agents receive their profile from the server when a job starts.
Restart Claude Code.
Note: Download link expires in 15 minutes.
"""

BOOTSTRAP_CODEX_CLI = f"""Install the {branding.PRODUCT_NAME} CLI skill. This is a one-time setup.

Step 1 — Install the skill:
Download: {{SKILLS_URL}}
Extract to: ~/.codex/skills/ (create if needed, overwrite existing)
Delete the downloaded zip.

Step 2 — Leave Codex feature flags unchanged:
Current Codex releases enable subagent workflows by default, so this setup does not need
multi_agent or default_mode_request_user_input in ~/.codex/config.toml.

Adapt all commands for the OS you are running on.
After installation, tell the user:
One skill is now available:
- $giljo — create/read/update projects and tasks (it loads the {branding.PRODUCT_NAME} guide, then acts)

Agent templates are not installed as files: agents receive their profile from the server when a job starts.
Restart Codex CLI.
Note: Download link expires in 15 minutes.
"""

BOOTSTRAP_OPENCODE = f"""Install the {branding.PRODUCT_NAME} CLI command. This is a one-time setup.

Step 1 — Install the command:
Download: {{SLASH_COMMANDS_URL}}
Extract to: ~/.config/opencode/commands/ (create if needed, overwrite existing)
Delete the downloaded zip.

Adapt all commands for the OS you are running on.
After installation, tell the user:
One command is now available:
- /giljo — create/read/update projects and tasks (it loads the {branding.PRODUCT_NAME} guide, then acts)

Agent templates are not installed as files: agents receive their profile from the server when a job starts.
Restart opencode — commands are read at startup.
Note: Download link expires in 15 minutes.
"""

BOOTSTRAP_GENERIC = f"""Your CLI platform was not auto-detected. Visit your {branding.PRODUCT_NAME} server's
Tools -> Connect page to download the {branding.PRODUCT_NAME} command reference file.
Install it according to your tool's documentation. Its job is to call the
get_giljo_guide tool and follow it (your MCP client may expose it under a
prefix, e.g. mcp__<server>__get_giljo_guide — use the name your harness lists).
Agent templates are not installed as files: agents receive their profile from the server when a job starts.
"""



def _strip_yaml_frontmatter(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("---"):
        end = stripped.find("---", 3)
        if end != -1:
            return stripped[end + 3 :].strip()
    return stripped


_BUNDLE_NUDGE_LINE = (
    "## Skills bundle freshness (check once per session)\n"
    "\n"
    f"This skill was generated from {branding.PRODUCT_NAME} skills bundle `bundle_version: {SKILLS_VERSION}`.\n"
    f"Any {branding.PRODUCT_NAME} tool response includes `_meta.skills_version` (the version the server "
    f"currently ships). The FIRST time in a chat session that you call a {branding.PRODUCT_NAME} tool, "
    "compare that `_meta.skills_version` to this file's `bundle_version`. If the server's "
    f'version is newer, tell the user once: "Your {branding.PRODUCT_NAME} skills are out of date — run '
    '/giljo_setup to update." Do not repeat this notice again in the same session, and never '
    "block the user's actual request on it.\n"
)


def _stamp_bundle_version(filename: str, content: str) -> str:
    return _stamp_markdown(content)


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

    front = f"---\nbundle_version: {SKILLS_VERSION}\n---\n\n"
    return front + content.rstrip() + "\n\n" + _BUNDLE_NUDGE_LINE



_VALID_PLATFORMS = EXPORT_PLATFORMS


def get_all_templates(platform: str = "claude_code") -> dict[str, str]:
    if platform not in _VALID_PLATFORMS:
        raise ValueError(f"Unknown platform '{platform}'. Must be one of: {', '.join(_VALID_PLATFORMS)}")

    templates_by_platform = {
        EXPORT_CLAUDE_CODE: {"giljo.md": GILJO_CLAUDE_MD},
        EXPORT_OPENCODE: {"giljo.md": GILJO_OPENCODE_MD},
        EXPORT_CODEX_CLI: {"giljo/SKILL.md": GILJO_SKILL_MD},
        EXPORT_GENERIC: {"giljo_reference.md": _strip_yaml_frontmatter(GILJO_CLAUDE_MD)},
    }
    templates = templates_by_platform[platform]

    return {name: _stamp_bundle_version(name, content) for name, content in templates.items()}
