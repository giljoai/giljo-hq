# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.tools.slash_command_templates import (
    _BUNDLE_NUDGE_LINE,
    SKILLS_VERSION,
    get_all_templates,
)


_PLATFORMS = ("claude_code", "codex_cli", "generic")

_NUDGE_PHRASE = "bundle_version"
_NUDGE_SESSION_PHRASE = "once per session"


@pytest.mark.parametrize("platform", _PLATFORMS)
def test_all_templates_carry_bundle_version(platform: str):
    templates = get_all_templates(platform)
    assert templates, f"get_all_templates({platform!r}) returned empty dict"

    for filename, content in templates.items():
        assert SKILLS_VERSION in content, (
            f"[{platform}] {filename}: bundle_version {SKILLS_VERSION!r} not found in content"
        )


@pytest.mark.parametrize("platform", _PLATFORMS)
def test_all_templates_carry_nudge(platform: str):
    templates = get_all_templates(platform)

    for filename, content in templates.items():
        assert _NUDGE_SESSION_PHRASE in content, f"[{platform}] {filename}: once-per-session nudge phrase not found"


def test_bundle_nudge_line_references_skills_version():
    assert SKILLS_VERSION in _BUNDLE_NUDGE_LINE, (
        f"_BUNDLE_NUDGE_LINE does not reference current SKILLS_VERSION {SKILLS_VERSION!r}"
    )


def test_claude_code_markdown_has_frontmatter_bundle_version():
    templates = get_all_templates("claude_code")
    for filename, content in templates.items():
        assert filename.endswith(".md"), f"unexpected file extension: {filename}"
        assert f"bundle_version: {SKILLS_VERSION}" in content, (
            f"claude_code/{filename}: YAML frontmatter bundle_version missing"
        )


def test_codex_skill_md_has_frontmatter_bundle_version():
    templates = get_all_templates("codex_cli")
    for filename, content in templates.items():
        if filename.endswith("SKILL.md"):
            assert f"bundle_version: {SKILLS_VERSION}" in content, (
                f"codex_cli/{filename}: YAML frontmatter bundle_version missing"
            )


def test_generic_templates_carry_bundle_version():
    templates = get_all_templates("generic")
    assert templates
    for filename, content in templates.items():
        assert SKILLS_VERSION in content, f"generic/{filename}: bundle_version {SKILLS_VERSION!r} not found"
