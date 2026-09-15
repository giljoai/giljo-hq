# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.tools.setup_instructions import (
    GILJOAI_MCP_PRIMER,
    build_inline_primer_note,
    build_setup_instructions,
)


def test_claude_code_instructions_contain_download_url():
    url = "https://example.com/download/test"
    result = build_setup_instructions("claude_code", url)
    assert url in result
    assert "~/.claude/" in result


def test_codex_cli_instructions_contain_download_url():
    url = "https://example.com/download/test"
    result = build_setup_instructions("codex_cli", url)
    assert url in result
    assert "~/.codex/" in result


def test_codex_cli_instructions_offer_global_agents_md_display_rule():
    result = build_setup_instructions("codex_cli", "https://example.com/download/test")

    assert "~/.codex/AGENTS.md" in result
    assert "GILJOAI_CODEX_SUBAGENT_DISPLAY_START" in result
    assert "GILJOAI_CODEX_SUBAGENT_DISPLAY_END" in result
    assert "Waiting for <dashboard-display-name> (<codex-agent-id-short>)" in result
    assert "pipeline-implementer (019e74bb...)" in result
    assert "Dashboard initials such as `TE` or `PI` are badges only" in result


def test_generic_instructions_contain_download_url():
    url = "https://example.com/download/test"
    result = build_setup_instructions("generic", url)
    assert url in result
    assert "platform was not identified" in result


def test_primer_is_well_under_2kb():
    assert len(GILJOAI_MCP_PRIMER.encode("utf-8")) < 2000


def test_primer_persist_step_present_on_every_platform_branch():
    url = "https://example.com/download/test"
    for platform in ("claude_code", "codex_cli", "opencode", "generic"):
        result = build_setup_instructions(platform, url)
        assert GILJOAI_MCP_PRIMER in result, f"{platform} missing the shared primer constant"
        assert "GILJOAI_MCP_PRIMER_START" in result, f"{platform} missing the primer start marker"
        assert "GILJOAI_MCP_PRIMER_END" in result, f"{platform} missing the primer end marker"
        assert "code-memory system" in result, f"{platform} missing the memory-system fallback"
        assert "Ask the user ONCE" in result, f"{platform} missing the ask-first consent step"


def test_primer_persist_step_targets_platform_specific_startup_file():
    url = "https://example.com/download/test"
    assert "~/.claude/CLAUDE.md" in build_setup_instructions("claude_code", url)
    assert "~/.codex/AGENTS.md" in build_setup_instructions("codex_cli", url)


def test_inline_primer_note_has_no_filesystem_write_instructions():
    note = build_inline_primer_note()

    assert GILJOAI_MCP_PRIMER in note
    assert "code-memory system" in note
    for marker in ("~/.claude", "~/.codex", "CLAUDE.md", "AGENTS.md"):
        assert marker not in note, f"inline primer note leaked a filesystem path: {marker!r}"
