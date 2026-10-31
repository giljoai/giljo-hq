# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.harness_resolver import (
    GENERIC_HARNESS,
    HARNESS_CLAUDE_CODE,
    HARNESS_CODEX,
    harness_for_connection,
)


SHARED_ANTHROPIC_ID = "https://claude.ai/oauth/mcp-oauth-client-metadata"


def test_claude_code_on_the_shared_anthropic_id_resolves_to_claude_code() -> None:
    assert (
        harness_for_connection({"name": "claude-code", "version": "2.1.311"}, SHARED_ANTHROPIC_ID)
        == HARNESS_CLAUDE_CODE
    )


def test_desktop_and_web_on_the_shared_anthropic_id_stay_generic() -> None:
    assert (
        harness_for_connection({"name": "Anthropic/ClaudeAI", "version": "1.0.0"}, SHARED_ANTHROPIC_ID)
        == GENERIC_HARNESS
    )
    assert harness_for_connection({}, SHARED_ANTHROPIC_ID) == GENERIC_HARNESS


def test_a_concrete_cimd_row_still_outranks_clientinfo() -> None:
    assert (
        harness_for_connection(
            {"name": "claude-code", "version": "2.1.311"}, "https://chatgpt.com/oauth/codex/client.json"
        )
        == HARNESS_CODEX
    )


def test_no_cimd_id_resolves_from_clientinfo_as_before() -> None:
    assert harness_for_connection({"name": "claude-code", "version": "2.1.311"}, None) == HARNESS_CLAUDE_CODE
    assert harness_for_connection({"name": "unknown-thing", "version": "1"}, None) == GENERIC_HARNESS
