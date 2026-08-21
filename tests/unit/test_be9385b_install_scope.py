# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9385b -- ``resolve_install_scope``: WHERE a platform's agent files go.

``INSTALL_PATHS`` has recorded a project-level path for Claude Code, Gemini CLI and
generic since BE-6116, but every install instruction hardcoded the user-level
``~/…`` location, so the registry knew something the prose never asked. Repo-level
installs matter here beyond tidiness: a repo is in practice one product's working
tree, so agents installed into ``{repo}/.claude/agents/`` cannot collide with
another product's install at all. The shared user-level directory is where
collisions live, so it is the fallback rather than the default.

Pure function, no DB, no network, no fixtures -- parallel-safe by construction.
"""

from __future__ import annotations

import pytest

from giljo_mcp.install_targets import INSTALL_PATHS, resolve_install_scope
from giljo_mcp.platform_registry import (
    EXPORT_ANTIGRAVITY_CLI,
    EXPORT_CLAUDE_CODE,
    EXPORT_CODEX_CLI,
    EXPORT_GEMINI_CLI,
    EXPORT_GENERIC,
    EXPORT_PLATFORMS,
    PRESET_CHAT,
    PRESET_DESKTOP_APP,
    PRESET_WEB_SANDBOX,
)


@pytest.mark.parametrize(
    ("platform", "expected_path"),
    [
        (EXPORT_CLAUDE_CODE, ".claude/agents/"),
        (EXPORT_GEMINI_CLI, ".gemini/agents/"),
        (EXPORT_GENERIC, "agents/"),
    ],
)
def test_a_platform_with_a_project_path_installs_repo_level(platform, expected_path):
    """The whole point: prefer the repo, which is naturally one product's tree."""
    target = resolve_install_scope(platform)
    assert target is not None
    assert target.scope == "project"
    assert target.path == expected_path


@pytest.mark.parametrize(
    ("platform", "expected_path"),
    [
        (EXPORT_CODEX_CLI, "~/.codex/agents/"),
        (EXPORT_ANTIGRAVITY_CLI, "~/.gemini/config/plugins/giljoai/"),
    ],
)
def test_a_platform_with_no_project_path_falls_back_to_user_level(platform, expected_path):
    """Codex and Antigravity have only a user-level location, and their INSTALL_PATHS
    entries name it with DIFFERENT keys (``agent_files`` / ``plugin_root``).

    That shape variance is exactly why the user-level key is declared as data next
    to INSTALL_PATHS instead of being guessed by an if-chain at each call site.
    """
    target = resolve_install_scope(platform)
    assert target is not None
    assert target.scope == "user"
    assert target.path == expected_path


@pytest.mark.parametrize("preset", [PRESET_WEB_SANDBOX, PRESET_DESKTOP_APP])
def test_a_preset_with_a_working_tree_still_installs_repo_level(preset):
    """web_sandbox is an isolated PR checkout and desktop_app writes the shared tree.

    Both have somewhere to put a file, so neither is a reason to fall back to the
    user-level namespace. This is the same distinction AUDIT-9327 F1 drew when it
    kept the per-agent ``filename`` for web_sandbox and stripped it only for chat.
    """
    target = resolve_install_scope(EXPORT_CLAUDE_CODE, preset)
    assert target is not None
    assert target.scope == "project"


def test_a_session_with_no_filesystem_installs_nowhere():
    """chat (WORKSPACE_NONE) has nowhere to write, so naming a path would be a lie.

    giljo_setup already routes this session to its inline branch; the agents arrive
    server-delivered via get_job_mission. Returning a path here would produce
    install prose instructing a chat client to write to a home directory it does
    not have.
    """
    assert resolve_install_scope(EXPORT_CLAUDE_CODE, PRESET_CHAT) is None


def test_an_unknown_platform_installs_nowhere():
    assert resolve_install_scope("not_a_platform") is None
    assert resolve_install_scope("") is None


def test_no_preset_means_an_ordinary_cli_not_an_unknown_session():
    """``preset_name=None`` is the plain-CLI case, which always has a working tree.

    Reading None as "assume nothing" would push every ordinary Claude Code / Gemini
    CLI install back to the user-level directory -- i.e. it would silently undo the
    feature for the overwhelmingly common case.
    """
    assert resolve_install_scope(EXPORT_CLAUDE_CODE, None) == resolve_install_scope(EXPORT_CLAUDE_CODE)
    assert resolve_install_scope(EXPORT_CLAUDE_CODE, None).scope == "project"


def test_every_export_platform_resolves_to_a_real_location():
    """Drift guard: a newly added export platform must not silently install nowhere.

    Without this, adding a platform to EXPORT_PLATFORMS and INSTALL_PATHS but
    forgetting the user-level key would make ``resolve_install_scope`` return None
    for it -- and the failure would surface as install prose that quietly omits the
    agents step, which is far harder to notice than an exception.
    """
    for platform in EXPORT_PLATFORMS:
        target = resolve_install_scope(platform)
        assert target is not None, (
            f"{platform!r} is an export platform but resolves to no install location. "
            "Add its user-level key to _USER_INSTALL_KEY (or a 'project' entry to "
            "INSTALL_PATHS)."
        )
        assert target.path, f"{platform!r} resolved to an empty path"
        assert target.path in INSTALL_PATHS[platform].values(), (
            f"{platform!r} resolved to {target.path!r}, which is not one of its own "
            f"declared INSTALL_PATHS values {sorted(INSTALL_PATHS[platform].values())}."
        )


# ---------------------------------------------------------------------------
# Cross-platform golden coverage for the naming + marker contract (BE-9385b).
# The assembler is pure, so this needs no database: it is the cheapest place to
# pin that EVERY platform got the same treatment, including the one that
# deliberately did not.
# ---------------------------------------------------------------------------


class _FakeTemplate:
    """Minimal stand-in with only the attributes the renderers read."""

    def __init__(self):
        self.id = "tmpl-1234"
        self.name = "implementer-backend"
        self.role = "custom"
        self.description = "Does the work."
        self.model = "opus"
        self.tools = ""
        self.background_color = None
        self.system_instructions = "bootstrap"
        self.user_instructions = "body"
        self.behavioral_rules = []
        self.success_criteria = []
        self.cli_tool = "claude"


def _ctx():
    from giljo_mcp.tools.agent_template_assembler import ExportContext

    return ExportContext(tenant_key="tk_golden", product_id="prod-9999", product_slug="acme-corp")


@pytest.mark.parametrize("platform", [EXPORT_CLAUDE_CODE, EXPORT_GEMINI_CLI, EXPORT_GENERIC])
def test_markdown_platforms_get_a_product_qualified_name_and_a_marker(platform):
    from giljo_mcp.template_renderer import OWNERSHIP_MARKER_TOKEN
    from giljo_mcp.tools.agent_template_assembler import AgentTemplateAssembler

    agent = AgentTemplateAssembler().assemble([_FakeTemplate()], platform, export_context=_ctx())["agents"][0]

    assert agent["filename"] == "implementer-backend--acme-corp.md", (
        f"{platform}: exported filename is not product-qualified -- got {agent['filename']!r}"
    )
    marker = next((ln for ln in agent["content"].splitlines() if OWNERSHIP_MARKER_TOKEN in ln), None)
    assert marker is not None, f"{platform}: no ownership marker, so an installer cannot tell whose file it is"
    assert marker.startswith("<!--") and marker.endswith("-->"), (
        f"{platform}: the marker must be an inert HTML comment, not something a frontmatter "
        f"schema validator could reject -- got {marker!r}"
    )
    for field in ("tenant=tk_golden", "product=prod-9999", "template=tmpl-1234", "hash="):
        assert field in marker, f"{platform}: marker is missing {field} -- {marker!r}"


def test_codex_carries_the_marker_as_a_toml_comment():
    """Codex ships TOML, where an HTML comment would be a syntax error."""
    from giljo_mcp.file_staging import _codex_agents_to_toml
    from giljo_mcp.template_renderer import OWNERSHIP_MARKER_TOKEN
    from giljo_mcp.tools.agent_template_assembler import AgentTemplateAssembler

    export = AgentTemplateAssembler().assemble([_FakeTemplate()], EXPORT_CODEX_CLI, export_context=_ctx())
    (path, content) = _codex_agents_to_toml(export["agents"])[0]

    assert path == "agents/gil-implementer-backend--acme-corp.toml", f"codex filename not qualified: {path}"
    assert content.startswith(f"# {OWNERSHIP_MARKER_TOKEN}"), (
        f"codex marker must lead the file as a TOML comment -- got {content.splitlines()[0]!r}"
    )
    assert "product=prod-9999" in content.splitlines()[0]
    # The marker must NOT be folded into the agent's operating identity.
    assert OWNERSHIP_MARKER_TOKEN not in content.split("developer_instructions", 1)[1], (
        "the ownership marker leaked into developer_instructions -- installer bookkeeping "
        "must never become part of the agent's persona"
    )


def test_antigravity_deliberately_carries_no_marker():
    """The documented carve-out, pinned so it reads as a decision and not an oversight.

    `agy plugin validate` accepts only the nested ``config.customAgent`` shape, so an
    extra top-level key risks failing validation outright, and hiding the marker in
    the agent's prompt would pollute its persona. It is safe to omit precisely
    because the whole tree installs into a fixed GiljoAI-owned plugin root -- there
    are no user-authored files in there to protect, which is the marker's only job.
    """
    from giljo_mcp.template_renderer import OWNERSHIP_MARKER_TOKEN
    from giljo_mcp.tools.agent_template_assembler import AgentTemplateAssembler

    agent = AgentTemplateAssembler().assemble([_FakeTemplate()], EXPORT_ANTIGRAVITY_CLI, export_context=_ctx())[
        "agents"
    ][0]

    assert OWNERSHIP_MARKER_TOKEN not in str(agent["agent_json"]), (
        "A marker appeared in the antigravity agent.json. If this is intentional, the "
        "agy validator must be re-checked first -- see the carve-out note in the assembler."
    )
    # The product qualifier still applies: the plugin's agent DIRECTORY is namespaced.
    assert agent["agent_dir"] == "implementer-backend--acme-corp"


def test_no_export_context_reproduces_the_pre_be9385b_output():
    """The anonymous system-default bundle must stay exactly as it was.

    It has no tenant and no product, so a marker there would name an owner that does
    not exist, and a product qualifier would name a product nobody chose.
    """
    from giljo_mcp.template_renderer import OWNERSHIP_MARKER_TOKEN
    from giljo_mcp.tools.agent_template_assembler import AgentTemplateAssembler

    agent = AgentTemplateAssembler().assemble([_FakeTemplate()], EXPORT_CLAUDE_CODE)["agents"][0]

    assert agent["filename"] == "implementer-backend.md", "bare export gained a product qualifier"
    assert OWNERSHIP_MARKER_TOKEN not in agent["content"], "bare export gained an ownership marker"
