# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp import platform_registry as reg
from giljo_mcp.services.protocol_sections.chapters_reference import (
    _REACTIVATION_GENERIC,
    _build_ch3_spawning_rules,
    _build_reactivation_spawn_block,
)


_LEGACY = [
    ("claude_code_cli", "claude-code", "claude"),
    ("codex_cli", "codex", "codex"),
    ("gemini_cli", "generic", "subagent"),
    ("antigravity_cli", "generic", "subagent"),
    ("generic_mcp", "generic", "subagent"),
]


@pytest.mark.parametrize("legacy, harness, short_token", _LEGACY)
def test_legacy_token_normalizes_to_subagent(legacy, harness, short_token):
    assert reg.normalize_execution_mode(legacy) == "subagent"
    assert reg.is_subagent_mode(legacy) is True
    assert reg.is_subagent_render(legacy) is True


@pytest.mark.parametrize("legacy, harness, short_token", _LEGACY)
def test_legacy_token_accepted_at_boundaries_not_a_new_write(legacy, harness, short_token):
    assert legacy in reg.ACCEPTED_EXECUTION_MODES
    assert legacy in reg.LEGACY_MODE_ALIASES
    assert legacy not in reg.VALID_EXECUTION_MODES


@pytest.mark.parametrize("legacy, harness, short_token", _LEGACY)
def test_legacy_token_keeps_its_harness_hint(legacy, harness, short_token):
    assert reg.tool_for_mode(legacy) == harness
    assert reg.stage_mode_token(legacy) == short_token


def test_canonical_modes_are_exactly_two():
    assert {"multi_terminal", "subagent"} == reg.VALID_EXECUTION_MODES
    assert reg.EXECUTION_MODES == ("multi_terminal", "subagent")
    assert reg.tool_for_mode("subagent") == reg.GENERIC_HARNESS
    assert reg.normalize_execution_mode(None) is None
    assert reg.normalize_execution_mode("multi_terminal") == "multi_terminal"


@pytest.mark.parametrize("legacy, harness, short_token", _LEGACY)
def test_sequence_run_validator_accepts_legacy(legacy, harness, short_token):
    from giljo_mcp.services.sequence_run_validation import validate_create_fields

    validate_create_fields(
        project_ids=["11111111-1111-1111-1111-111111111111"],
        execution_mode=legacy,
        status="pending",
        review_policy="per_card",
        project_statuses={},
    )


def test_sequence_run_validator_still_rejects_garbage():
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.sequence_run_validation import validate_create_fields

    with pytest.raises(ValidationError):
        validate_create_fields(
            project_ids=["11111111-1111-1111-1111-111111111111"],
            execution_mode="not_a_real_mode",
            status="pending",
            review_policy="per_card",
            project_statuses={},
        )


_UNIVERSAL_MARKER = "ANY MCP-CONNECTED AGENT (generic_mcp)"
_DELEGATE_MARKER = "DELEGATE FIRST"
_SELF_ADOPT_MANDATORY = "using it is MANDATORY"


@pytest.mark.parametrize("tool", ["generic", "opencode", "generic_mcp", "gemini", "antigravity"])
def test_ch3_universal_ladder_for_subagent_floor(tool):
    ch3 = _build_ch3_spawning_rules(tool=tool)
    assert _UNIVERSAL_MARKER in ch3, f"{tool!r} must render the universal subagent ladder"
    assert _DELEGATE_MARKER in ch3, f"{tool!r} must carry the DELEGATE-first lead banner (BE-9034)"
    assert _SELF_ADOPT_MANDATORY in ch3, f"{tool!r} must carry the strengthened SELF-ADOPT framing"


def test_ch3_dedicated_cli_keeps_native_syntax():
    assert "Task(subagent_type=" in _build_ch3_spawning_rules(tool="claude-code")
    assert "spawn_agent(" in _build_ch3_spawning_rules(tool="codex")
    assert "CODEX CLI" in _build_ch3_spawning_rules(tool="codex")


def test_ch3_multi_terminal_is_not_the_universal_ladder():
    assert _UNIVERSAL_MARKER not in _build_ch3_spawning_rules(tool="multi_terminal")


@pytest.mark.parametrize("tool", ["generic", "opencode", "generic_mcp", "unknown-harness"])
def test_reactivation_subagent_floor_is_harness_native(tool):
    block = _build_reactivation_spawn_block(tool)
    assert block == _REACTIVATION_GENERIC
    assert "using it is MANDATORY" in block
    assert "Open a new session with your AI" not in block


def test_reactivation_dedicated_and_multi_terminal_unchanged():
    assert "Task(subagent_type=" in _build_reactivation_spawn_block("claude-code")
    assert "Open a new session with your AI" in _build_reactivation_spawn_block("multi_terminal")
