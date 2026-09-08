# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Where an export platform's agent files are installed -- the export behavior facet.

Extracted from ``platform_registry`` (BE-9385b). The registry's own comment already
called this "a non-branching sibling table" and "data, not identity", i.e. a
*facet* rather than part of platform identity -- so it separates cleanly, and it
had to: ``platform_registry.py`` sits at exactly the flat 800-line cap with no
budget entry, so there was no room to answer "which of these paths do we use?"
beside the table that lists them.

Two things live here, and the split between them is the point:

* ``INSTALL_PATHS`` -- which locations each platform *has*. Pure data, unchanged
  from BE-6116, still consumed by ``AgentTemplateAssembler`` for the
  ``install_paths`` key it returns to clients.
* ``resolve_install_scope`` -- which of them this session should actually *use*.
  That question was never asked before: every install instruction hardcoded the
  user-level ``~/…`` path even for the platforms whose project-level path the
  registry had recorded all along.
"""

from __future__ import annotations

from typing import NamedTuple

from giljo_mcp.platform_registry import WORKSPACE_NONE, get_preset


# ---------------------------------------------------------------------------
# Export behavior facet (BE-6116): agent-template install paths per EXPORT
# platform. Keyed by the export/download vocabulary (note ``claude_code`` drops
# the ``_cli`` suffix and ``generic`` is the pseudo-platform) -- a non-branching
# sibling table consumed by AgentTemplateAssembler. The dict shape varies per
# platform (the installer surfaces different keys), so this is data, not identity.
# ---------------------------------------------------------------------------
INSTALL_PATHS: dict[str, dict[str, str]] = {
    "claude_code": {
        "project": ".claude/agents/",
        "user": "~/.claude/agents/",
    },
    "gemini_cli": {
        "project": ".gemini/agents/",
        "user": "~/.gemini/agents/",
    },
    "antigravity_cli": {
        "plugin_root": "~/.gemini/config/plugins/giljoai/",
        "install_command": "agy plugin install ~/.gemini/config/plugins/giljoai/",
    },
    "codex_cli": {
        "agent_files": "~/.codex/agents/",
        "global_config_optional": "~/.codex/config.toml",
    },
    # BE-9501: paths verified against opencode 1.18.22 on 2026-08-25. Every
    # directory is PLURAL -- opencode never reads the singular ``agent/`` or
    # ``command/``, so installing there reports success and does nothing. This is
    # not a nit: the first agent to attempt this install guessed singular.
    "opencode": {
        "project": ".opencode/agents/",
        "user": "~/.config/opencode/agents/",
    },
    "generic": {
        "project": "agents/",
        "user": "~/agents/",
    },
}


# The key inside each INSTALL_PATHS entry that names its USER-level location.
# The entry shapes deliberately differ per platform (see the note above), so the
# user-level key is DECLARED here rather than guessed by each caller with an
# if-chain -- the same reason INSTALL_PATHS itself is data and not branching.
_USER_INSTALL_KEY: dict[str, str] = {
    "claude_code": "user",
    "gemini_cli": "user",
    "generic": "user",
    "opencode": "user",
    "codex_cli": "agent_files",
    "antigravity_cli": "plugin_root",
}


class InstallTarget(NamedTuple):
    """Where one platform's agent files should be installed for this session."""

    scope: str  # "project" | "user"
    path: str


def resolve_install_scope(platform: str, preset_name: str | None = None) -> InstallTarget | None:
    """Return where ``platform``'s agent files should land, or ``None`` for nowhere.

    BE-9385b. ``INSTALL_PATHS`` records which locations a platform *has*; this
    answers which one to actually use, which the install prose previously did not
    ask -- it hardcoded the user-level ``~/…`` path for every platform even where
    the registry already knew a project-level path existed.

    **Repo-level is preferred wherever it exists**, for a reason that is about
    correctness rather than tidiness: a repo is, in practice, one product's working
    tree, so agents installed into ``{repo}/.claude/agents/`` are product-bound by
    the filesystem itself and cannot collide with another product's install. The
    user-level directory is the shared namespace where collisions live, so it is
    the fallback, not the default.

    Args:
        platform: An export platform token (``claude_code``, ``codex_cli``, …).
        preset_name: The resolved harness PRESET, when the session has one. A
            session with no preset is an ordinary CLI, which always has a working
            tree -- so ``None`` means "assume a working tree", not "assume nothing".

    Returns:
        ``InstallTarget(scope, path)``, or ``None`` when this session installs no
        files at all -- either an unknown platform, or a preset with no filesystem
        (``WORKSPACE_NONE``, i.e. pure chat), whose agents are server-delivered via
        ``get_job_mission`` and have nowhere to be written.
    """
    paths = INSTALL_PATHS.get(platform)
    if not paths:
        return None

    preset = get_preset(preset_name) if preset_name else None
    if preset is not None and preset.workspace_model == WORKSPACE_NONE:
        # No filesystem: giljo_setup's inline branch already handles this session,
        # so there is no install location to name and inventing one would be a lie.
        return None

    # A preset with an isolated PR checkout (web_sandbox) still has a working tree
    # it can write to, so it qualifies for project scope alongside the plain CLIs.
    if "project" in paths:
        return InstallTarget("project", paths["project"])

    user_key = _USER_INSTALL_KEY.get(platform)
    if user_key is None or user_key not in paths:
        return None
    return InstallTarget("user", paths[user_key])


__all__ = ["INSTALL_PATHS", "InstallTarget", "resolve_install_scope"]
