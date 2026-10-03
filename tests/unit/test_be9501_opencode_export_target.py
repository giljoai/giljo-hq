# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pathlib

from giljo_mcp.platform_registry import (
    EXPORT_CLAUDE_CODE,
    EXPORT_CODEX_CLI,
    EXPORT_GENERIC,
    EXPORT_OPENCODE,
    EXPORT_PLATFORMS,
    HARNESSES,
)
from giljo_mcp.tools.setup_instructions import build_setup_instructions
from giljo_mcp.tools.slash_command_templates import get_all_templates


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestConnectableImpliesInstallable:

    def test_no_harness_is_left_without_an_export_target(self) -> None:
        orphans = sorted(h.harness for h in HARNESSES if h.export_platform is None)
        assert not orphans, (
            f"harness(es) {orphans} are detectable/launchable but have no export target, "
            "so giljo_setup cannot install agents for them"
        )


class TestFullHarnessParity:

    _REAL_CLI_PLATFORMS = (
        EXPORT_CLAUDE_CODE,
        EXPORT_CODEX_CLI,
        EXPORT_OPENCODE,
    )

    def test_every_real_cli_ships_a_giljo_command_file(self) -> None:
        for platform in self._REAL_CLI_PLATFORMS:
            files = get_all_templates(platform=platform)
            assert files, f"{platform} ships no /giljo command or skill file at all"
            assert any("giljo" in name for name in files), (
                f"{platform}'s command bundle has no giljo entry: {sorted(files)}"
            )

    def test_every_real_cli_gets_its_own_setup_instructions(self) -> None:
        generic = build_setup_instructions(EXPORT_GENERIC, "https://example/x.zip", None)
        for platform in self._REAL_CLI_PLATFORMS:
            out = build_setup_instructions(platform, "https://example/x.zip", None)
            assert out != generic, (
                f"{platform} falls through to the generic manual-steps text -- it has no "
                "install branch of its own, so giljo_setup installs nothing for it"
            )

    def test_every_real_cli_persists_a_primer_to_its_startup_context(self) -> None:
        for platform in self._REAL_CLI_PLATFORMS:
            out = build_setup_instructions(platform, "https://example/x.zip", None)
            assert "Step P" in out, f"{platform}'s instructions never persist the primer"

    def test_opencode_instructions_name_its_real_locations(self) -> None:
        out = build_setup_instructions(EXPORT_OPENCODE, "https://example/x.zip", None)
        assert "~/.config/opencode/agents/" not in out
        assert "~/.config/opencode/commands/" in out
        assert "AGENTS.md" in out, "opencode reads ~/.config/opencode/AGENTS.md as its global rules file"

    def test_opencode_instructions_warn_about_the_singular_directory_trap(self) -> None:
        out = build_setup_instructions(EXPORT_OPENCODE, "https://example/x.zip", None)
        assert "opencode/command/" in out and "PLURAL" in out


class TestTheDoorTheFixDidNotClose:

    def test_giljo_setup_description_names_every_platform_it_accepts(self) -> None:
        src = (REPO_ROOT / "api" / "endpoints" / "mcp_tools" / "_setup_tools.py").read_text(encoding="utf-8")
        block = src[src.index("description=(") : src.index('annotations=_tool_hints("giljo_setup", destructive=True)')]
        for platform in EXPORT_PLATFORMS:
            if platform == EXPORT_GENERIC:
                continue
            assert platform in block, (
                f"giljo_setup's tool description does not mention '{platform}', so an agent "
                "running in that tool cannot know to pass it and will take the default"
            )

    def test_no_harness_reports_an_agent_template_directory(self) -> None:
        carriers = sorted(h.tool_type for h in HARNESSES if hasattr(h, "template_locations"))
        assert not carriers, f"harness(es) {carriers} carry a retired agent-template location field"
