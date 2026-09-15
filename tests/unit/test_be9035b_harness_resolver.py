# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

import pytest

from giljo_mcp.platform_registry import (
    GENERIC_HARNESS,
    HARNESS_CLAUDE_CODE,
    HARNESS_CODEX,
    HARNESS_OPENCODE,
    effective_harness,
    harness_from_client_info,
)




def test_confirmed_claude_code_row_resolves_exact():
    assert harness_from_client_info("claude-code", "2.1.199") == HARNESS_CLAUDE_CODE
    assert harness_from_client_info("claude-code", None) == HARNESS_CLAUDE_CODE


def test_confirmed_codex_mcp_client_row_resolves_exact_and_silent(caplog):
    with caplog.at_level(logging.INFO):
        assert harness_from_client_info("codex-mcp-client", "0.42.0") == HARNESS_CODEX
        assert harness_from_client_info("codex-mcp-client", None) == HARNESS_CODEX
    assert "[harness-detect]" not in caplog.text


def test_confirmed_opencode_row_resolves_exact_and_silent(caplog):
    with caplog.at_level(logging.INFO):
        assert harness_from_client_info("opencode", "9.9.9") == HARNESS_OPENCODE
        assert harness_from_client_info("opencode", None) == HARNESS_OPENCODE
    assert "[harness-detect]" not in caplog.text


@pytest.mark.parametrize(
    "name",
    [
        "Anthropic/ClaudeAI",
        "Anthropic/Toolbox",
        "openai-mcp",
        "openai-mcp (ChatGPT)",
        "openai-mcp (Codex)",
        "opencode-check",
    ],
)
def test_tsk9088_known_generic_surfaces_resolve_generic_and_silent(name, caplog):
    with caplog.at_level(logging.INFO):
        assert harness_from_client_info(name, "1.0.0") == GENERIC_HARNESS
    assert "[harness-detect]" not in caplog.text


@pytest.mark.parametrize("name", [None, "", "   ", "\t\n"])
def test_absent_or_empty_name_resolves_generic_silently(name, caplog):
    with caplog.at_level(logging.INFO):
        assert harness_from_client_info(name, None) == GENERIC_HARNESS
    assert "[harness-detect]" not in caplog.text


@pytest.mark.parametrize(
    "name",
    [
        "codex",
        "codex-mcp",
        "gemini-cli",
        "antigravity",
        "totally-made-up-client",
    ],
)
def test_unrecognized_nonempty_name_resolves_generic_and_logs(name, caplog):
    with caplog.at_level(logging.INFO):
        assert harness_from_client_info(name, "9.9.9") == GENERIC_HARNESS
    assert "[harness-detect]" in caplog.text
    assert name in caplog.text


def test_openai_mcp_hosted_surface_stays_generic():
    assert harness_from_client_info("openai-mcp", "9.9.9") == GENERIC_HARNESS


@pytest.mark.parametrize(
    "spoof",
    [
        "claude-code-proxy",
        "claudecode",
        "claude_code",
        "Claude-Code",
        "x-claude-code",
        " claude-code-x ",
    ],
)
def test_spoofed_lookalikes_never_resolve_to_claude(spoof):
    assert harness_from_client_info(spoof, None) == GENERIC_HARNESS


def test_surrounding_whitespace_on_confirmed_name_is_tolerated():
    assert harness_from_client_info("  claude-code  ", None) == HARNESS_CLAUDE_CODE




@pytest.mark.parametrize(
    "declared_mode,expected",
    [
        ("claude_code_cli", HARNESS_CLAUDE_CODE),
        ("codex_cli", "codex"),
        ("gemini_cli", GENERIC_HARNESS),
        ("antigravity_cli", GENERIC_HARNESS),
        ("generic_mcp", GENERIC_HARNESS),
        ("multi_terminal", GENERIC_HARNESS),
        ("", GENERIC_HARNESS),
        (None, GENERIC_HARNESS),
        ("some_unknown_future_mode", GENERIC_HARNESS),
    ],
)
def test_declared_hint_when_no_detection_is_byte_safe(declared_mode, expected):
    assert effective_harness(declared_mode, None) == expected


@pytest.mark.parametrize("session_shape", [{"harness": "claude-code"}, {"resolved_harness": "claude-code"}])
def test_detected_concrete_harness_beats_declared(session_shape):
    assert effective_harness("generic_mcp", session_shape) == HARNESS_CLAUDE_CODE
    assert effective_harness("claude_code_cli", {"harness": "codex"}) == "codex"


@pytest.mark.parametrize("detected", [None, "", "generic"])
def test_generic_or_absent_detection_falls_through_to_declared(detected):
    assert effective_harness("claude_code_cli", {"harness": detected}) == HARNESS_CLAUDE_CODE


def test_reads_mcpsession_like_row_via_session_data():

    class _Row:
        session_data = {"resolved_harness": "codex", "client_info": {"name": "codex-mcp-client"}}

    assert effective_harness("multi_terminal", _Row()) == "codex"


def test_no_declared_and_no_detection_is_generic_floor():
    assert effective_harness(None, None) == GENERIC_HARNESS
    assert effective_harness("", {"harness": "generic"}) == GENERIC_HARNESS
