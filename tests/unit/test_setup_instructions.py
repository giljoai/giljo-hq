# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for setup_instructions module (Sprint 002e extraction)."""

from giljo_mcp.template_renderer import OWNERSHIP_MARKER_TOKEN
from giljo_mcp.tools.setup_instructions import (
    GILJOAI_MCP_PRIMER,
    build_inline_primer_note,
    build_setup_instructions,
)


def test_claude_code_instructions_contain_download_url():
    """Claude Code instructions include the download URL."""
    url = "https://example.com/download/test"
    result = build_setup_instructions("claude_code", url)
    assert url in result
    assert "~/.claude/" in result


def test_gemini_cli_instructions_contain_download_url():
    """Gemini CLI instructions include the download URL."""
    url = "https://example.com/download/test"
    result = build_setup_instructions("gemini_cli", url)
    assert url in result
    assert "~/.gemini/" in result


def test_codex_cli_instructions_contain_download_url():
    """Codex CLI instructions include the download URL."""
    url = "https://example.com/download/test"
    result = build_setup_instructions("codex_cli", url)
    assert url in result
    assert "~/.codex/" in result


def test_codex_cli_instructions_include_agents():
    """Codex setup instructions install standalone agent TOML files."""
    result = build_setup_instructions("codex_cli", "https://example.com/download/test")

    assert "standalone TOML" in result
    assert "~/.codex/agents/" in result
    assert "inherit the parent Codex session" in result
    assert "model = 'gpt-5.4'" not in result
    assert "Register agent templates" not in result
    assert "config_file =" not in result
    assert "Do NOT add default_mode_request_user_input" in result
    # INF-6049a: agent-only refresh now routes through giljo_setup's "Agents only" scope
    assert "Agents only" in result


def test_setup_instructions_offer_scope_choice_on_all_primary_platforms():
    """giljo_setup supports skills/commands-only, agents-only, or both on all CLI modes."""
    url = "https://example.com/download/test"
    for platform in ("claude_code", "gemini_cli", "codex_cli"):
        result = build_setup_instructions(platform, url)
        assert "What should giljo_setup install or refresh?" in result
        assert "Agents only" in result
        assert "Both" in result

    assert "Commands/skills only" in build_setup_instructions("claude_code", url)
    assert "Commands/skills only" in build_setup_instructions("gemini_cli", url)
    assert "Skills only" in build_setup_instructions("codex_cli", url)


def test_setup_instructions_do_not_touch_agents_when_scope_excludes_agents():
    """Skills/commands refreshes must not mutate agent directories or config."""
    url = "https://example.com/download/test"

    # BE-9385b: the target directory is now resolved per harness (repo-level where
    # supported), so the guarantee is stated once without naming a fixed path.
    claude = build_setup_instructions("claude_code", url)
    assert "If INSTALL_AGENTS=false, do not touch any agents directory." in claude

    gemini = build_setup_instructions("gemini_cli", url)
    assert "If INSTALL_AGENTS=false, do not touch any agents directory." in gemini
    assert "do not touch ~/.gemini/settings.json" in gemini

    codex = build_setup_instructions("codex_cli", url)
    assert "If INSTALL_AGENTS=false, set AGENTS_INSTALLED=false and do not touch ~/.codex/agents/." in codex
    assert "If INSTALL_AGENTS=false, do not touch ~/.codex/config.toml" in codex


def test_codex_cli_instructions_offer_global_agents_md_display_rule():
    """Codex setup can add the GiljoAI subagent display convention globally."""
    result = build_setup_instructions("codex_cli", "https://example.com/download/test")

    assert "~/.codex/AGENTS.md" in result
    assert "GILJOAI_CODEX_SUBAGENT_DISPLAY_START" in result
    assert "GILJOAI_CODEX_SUBAGENT_DISPLAY_END" in result
    assert "Waiting for <dashboard-display-name> / <codex-template-name>" in result
    assert "pipeline-implementer / gil-implementer-devops" in result
    assert "Dashboard initials such as `TE` or `PI` are badges only" in result


def test_codex_cli_instructions_clean_legacy_agent_config_blocks():
    """Codex setup tells agents to remove stale GiljoAI config registrations."""
    result = build_setup_instructions("codex_cli", "https://example.com/download/test")

    assert "legacy [agents.gil-*] tables" in result
    assert "back up config.toml" in result
    assert "remove ONLY those GiljoAI legacy registration blocks" in result
    assert "Preserve all non-GiljoAI agent blocks" in result
    assert "Validate the edited file with a TOML parser" in result
    assert "Do not add replacement [agents.gil-*] blocks" in result


def test_codex_cli_instructions_move_agent_backups_outside_discovery_dir():
    """Codex setup prevents backup TOML from being discovered as duplicate agents."""
    result = build_setup_instructions("codex_cli", "https://example.com/download/test")

    assert "~/.codex/agent_backups/" in result
    assert "*.model-backup" in result
    assert "duplicate agent roles" in result


def test_codex_cli_instructions_explain_request_user_input_cleanup():
    """Codex setup explains stale default_mode_request_user_input warning cleanup."""
    result = build_setup_instructions("codex_cli", "https://example.com/download/test")

    assert "default_mode_request_user_input = true is present" in result
    assert "unrelated to GiljoAI agents" in result
    assert "under-development warning" in result
    assert "unless the user explicitly wants to keep" in result


def test_agent_install_protects_user_authored_files_on_all_platforms():
    """Installing agents must never silently destroy a file the user wrote.

    BE-9385b REPLACED the old whole-directory "Overwrite (all) / Skip (all)"
    consent prompt this test used to assert, and the replacement is strictly
    stronger, which is why the assertions moved rather than relaxed. The old
    prompt could not tell a GiljoAI export from a hand-written agent, so
    "Overwrite" destroyed user files and "Skip" left GiljoAI's own agents stale --
    the user was asked to choose between two bad outcomes because nothing on disk
    recorded ownership.

    Now every exported file carries an ownership marker, so the guarantee is
    unconditional instead of a prompt: an unmarked file is the user's and is never
    touched, under any answer. These assertions pin THAT.
    """
    url = "https://example.com/download/test"
    for platform in ("claude_code", "gemini_cli", "codex_cli"):
        result = build_setup_instructions(platform, url)
        assert OWNERSHIP_MARKER_TOKEN in result, f"{platform} never mentions the ownership marker"
        assert "A file with NO marker" in result, f"{platform} missing the user-authored-file rule"
        assert "DO NOT TOUCH IT" in result, f"{platform} does not forbid touching user files"
        assert "Rule 4 has no exceptions" in result, f"{platform} leaves the user-file rule negotiable"
        assert "ONE FILE AT A TIME" in result, f"{platform} still installs by directory"


def test_agent_install_flags_a_conflict_for_the_user_instead_of_enforcing_a_rename():
    """BE-9396: a conflict is the user's to resolve, and the prose says the cost out loud.

    giljo_setup guarantees server -> disk and nothing past it. So on a genuine
    conflict the installing LLM offers the two answers that install cleanly, and
    if the user would rather rename a file by hand it tells them the consequence
    -- the orchestrator spawns by name, so a hand-renamed file is not spawnable
    until the name matches again -- rather than making the server chase the rename.

    The negative assertion is the load-bearing one: BE-9385b shipped a
    set_agent_export_alias round-trip here for one day, and this is what keeps the
    enforcement layer from growing back into the prose unnoticed.
    """
    for platform in ("claude_code", "gemini_cli", "codex_cli"):
        result = build_setup_instructions(platform, "https://example.com/download/test")
        assert "set_agent_export_alias" not in result, (
            f"{platform} still tells the installer to round-trip a rename through the server. "
            "That enforcement layer was retracted in BE-9396."
        )
        assert "REPLACE" in result and "SKIP" in result, (
            f"{platform} does not offer the two answers that install cleanly."
        )
        assert "not be\nspawnable" in result or "not be spawnable" in result, (
            f"{platform} lets the user hand-rename a file without being told it stops being spawnable."
        )


def test_generic_instructions_contain_download_url():
    """Generic instructions include the download URL."""
    url = "https://example.com/download/test"
    result = build_setup_instructions("generic", url)
    assert url in result
    assert "platform was not identified" in result


def test_primer_is_well_under_2kb():
    """BE-9067: the primer is a persisted artifact, not the full guide -- keep it small."""
    assert len(GILJOAI_MCP_PRIMER.encode("utf-8")) < 2000


def test_primer_persist_step_present_on_every_platform_branch():
    """BE-9067: every build_setup_instructions branch ships the same primer, marker
    block, memory-system fallback, and ask-first consent -- no duplicated primer
    literals, no drift."""
    url = "https://example.com/download/test"
    for platform in ("claude_code", "gemini_cli", "codex_cli", "antigravity_cli", "generic"):
        result = build_setup_instructions(platform, url)
        assert GILJOAI_MCP_PRIMER in result, f"{platform} missing the shared primer constant"
        assert "GILJOAI_MCP_PRIMER_START" in result, f"{platform} missing the primer start marker"
        assert "GILJOAI_MCP_PRIMER_END" in result, f"{platform} missing the primer end marker"
        assert "code-memory system" in result, f"{platform} missing the memory-system fallback"
        assert "Ask the user ONCE" in result, f"{platform} missing the ask-first consent step"


def test_primer_persist_step_targets_platform_specific_startup_file():
    """BE-9067: the persist step names the right startup file per platform."""
    url = "https://example.com/download/test"
    assert "~/.claude/CLAUDE.md" in build_setup_instructions("claude_code", url)
    assert "~/.gemini/GEMINI.md" in build_setup_instructions("gemini_cli", url)
    assert "~/.gemini/GEMINI.md" in build_setup_instructions("antigravity_cli", url)
    assert "~/.codex/AGENTS.md" in build_setup_instructions("codex_cli", url)


def test_inline_primer_note_has_no_filesystem_write_instructions():
    """BE-9067: the no-home-dir inline branch offers the primer + memory fallback,
    never a file path to write (there is no filesystem in that session)."""
    note = build_inline_primer_note()

    assert GILJOAI_MCP_PRIMER in note
    assert "code-memory system" in note
    for marker in ("~/.claude", "~/.codex", "~/.gemini", "CLAUDE.md", "AGENTS.md", "GEMINI.md"):
        assert marker not in note, f"inline primer note leaked a filesystem path: {marker!r}"
