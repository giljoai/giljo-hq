# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.tools.slash_command_templates import (
    BOOTSTRAP_CLAUDE_CODE,
    BOOTSTRAP_CODEX_CLI,
    BOOTSTRAP_GENERIC,
    BOOTSTRAP_OPENCODE,
    SKILLS_VERSION,
    get_all_templates,
)


_EXPECTED_FILE = {
    "claude_code": "giljo.md",
    "codex_cli": "giljo/SKILL.md",
    "generic": "giljo_reference.md",
}


class TestSlashCommandPlatformAwareness:

    def test_every_platform_returns_exactly_one_file(self):
        for platform, expected_name in _EXPECTED_FILE.items():
            result = get_all_templates(platform=platform)
            assert list(result.keys()) == [expected_name], (
                f"{platform} must export exactly one file {expected_name!r}, got {list(result)}"
            )

    def test_the_one_file_calls_the_guide_tool(self):
        for platform in _EXPECTED_FILE:
            (body,) = get_all_templates(platform=platform).values()
            assert "get_giljo_guide" in body, f"{platform} body must call get_giljo_guide"
            assert "mcp__giljo_mcp__get_giljo_guide" not in body, f"{platform} tool call must be bare, not prefixed"
            assert body.strip(), f"{platform} body is empty"

    def test_the_one_file_is_bundle_version_stamped(self):
        for platform in _EXPECTED_FILE:
            (body,) = get_all_templates(platform=platform).values()
            assert SKILLS_VERSION in body, f"{platform} body missing bundle_version {SKILLS_VERSION}"

    def test_no_legacy_gil_commands_are_exported(self):
        for platform in _EXPECTED_FILE:
            result = get_all_templates(platform=platform)
            for fname in result:
                for legacy in ("gil_add", "gil-add", "gil_get", "gil-get", "gil_chain", "gil-chain"):
                    assert legacy not in fname, f"{platform} still exports legacy file {fname}"

    def test_default_returns_claude_format(self):
        assert get_all_templates() == get_all_templates(platform="claude_code")


class TestBootstrapPromptTemplates:

    def test_url_placeholders_preserved(self):
        assert "{SLASH_COMMANDS_URL}" in BOOTSTRAP_CLAUDE_CODE
        assert "{AGENT_TEMPLATES_URL}" not in BOOTSTRAP_CLAUDE_CODE
        assert "{SKILLS_URL}" in BOOTSTRAP_CODEX_CLI

    def test_bootstraps_advertise_only_the_giljo_command(self):
        for bootstrap in (BOOTSTRAP_CLAUDE_CODE, BOOTSTRAP_CODEX_CLI, BOOTSTRAP_OPENCODE):
            assert "giljo" in bootstrap
            for legacy in ("gil_get_agents", "gil-get-agents", "gil_add", "gil-add", "/gil_get", "$gil-get"):
                assert legacy not in bootstrap, f"bootstrap still advertises deleted command {legacy}"

    def test_bootstraps_never_advertise_an_agent_file_install(self):
        for bootstrap in (BOOTSTRAP_CLAUDE_CODE, BOOTSTRAP_CODEX_CLI, BOOTSTRAP_OPENCODE, BOOTSTRAP_GENERIC):
            assert "Agents only" not in bootstrap
            assert "profile from the server" in bootstrap

    def test_generic_points_at_the_guide_tool(self):
        assert "get_giljo_guide" in BOOTSTRAP_GENERIC

    def test_all_bootstraps_mention_restart_and_expiry(self):
        for bootstrap in (BOOTSTRAP_CLAUDE_CODE, BOOTSTRAP_CODEX_CLI, BOOTSTRAP_OPENCODE):
            assert "restart" in bootstrap.lower()
            assert "expire" in bootstrap.lower()
