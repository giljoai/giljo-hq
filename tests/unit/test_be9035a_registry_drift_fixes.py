# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9035a -- registry-drift regression guards (DESIGN_execution_mode_collapse.md §4).

Locks the fixes for the 4 known drift/bug sites so a future platform add can never
silently repeat them:

1. ``thin_prompt_lifecycle`` derives its execution-mode gate + implementation prompt
   type map from the registry (was a hand-copied tuple/dict that omitted generic_mcp).
2. Antigravity is present (a specific, non-fallback entry) in all 4 prose dicts that
   previously omitted it.
3. ``OrchestratorPromptRequest.tool`` accepts every registered subagent tool_type.

Edition Scope: Both. Pure unit tests -- no DB, parallel-safe under pytest-xdist.
"""

from __future__ import annotations

import inspect

import pytest

from giljo_mcp.platform_registry import SUBAGENT_TOOL_TYPES


# Subagent tool_types that have a dedicated, hand-authored entry in the 4 prose
# dicts below. generic_mcp is deliberately excluded: its CH3 block is built by the
# dynamic capability ladder (_ch3_generic_mcp_triple), not a static dict entry, and
# its safe fallback in the other 3 dicts is intentional (design §4 item 2 scopes the
# fix to Antigravity, not generic_mcp).
# opencode is also excluded (BE-9035a/c reconciliation): it is a detected harness but
# rides the universal subagent floor for spawning (terminal `opencode --prompt`), so it
# has no dedicated @-syntax dict entry — the universal ladder covers it (test_be9035c).
_DICT_KEYED_SUBAGENT_TOOLS = tuple(t for t in SUBAGENT_TOOL_TYPES if t not in ("generic_mcp", "opencode"))


class TestSubagentSpawnByToolCoverage:
    """orchestrator_body._SUBAGENT_SPAWN_BY_TOOL -- every dict-keyed tool has its own
    entry (BE-9035a: Antigravity previously fell through to the generic fallback)."""

    @pytest.mark.parametrize("tool", _DICT_KEYED_SUBAGENT_TOOLS)
    def test_tool_has_specific_entry(self, tool):
        from giljo_mcp.services.protocol_sections.orchestrator_body import (
            _SUBAGENT_SPAWN_BY_TOOL,
            _SUBAGENT_SPAWN_GENERIC,
        )

        assert tool in _SUBAGENT_SPAWN_BY_TOOL, f"{tool!r} missing a specific spawn-syntax entry"
        assert _SUBAGENT_SPAWN_BY_TOOL[tool] != _SUBAGENT_SPAWN_GENERIC

    def test_gemini_and_antigravity_share_the_same_at_syntax(self):
        from giljo_mcp.services.protocol_sections.orchestrator_body import _SUBAGENT_SPAWN_BY_TOOL

        assert _SUBAGENT_SPAWN_BY_TOOL["gemini"] == _SUBAGENT_SPAWN_BY_TOOL["antigravity"] == "@agent-name"


class TestCh3SpawnBlocksCoverage:
    """chapters_reference._CH3_SPAWN_BLOCKS -- every CLI tool_type renders its OWN
    platform block, never the ANY-MCP-CONNECTED-AGENT generic fallback."""

    @pytest.mark.parametrize("tool", _DICT_KEYED_SUBAGENT_TOOLS)
    def test_tool_has_specific_ch3_block(self, tool):
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch3_spawning_rules

        ch3 = _build_ch3_spawning_rules(tool=tool)
        assert "ANY MCP-CONNECTED AGENT" not in ch3, f"{tool!r} fell through to the generic CH3 block"

    def test_antigravity_ch3_block_names_its_own_install_path(self):
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch3_spawning_rules

        ch3 = _build_ch3_spawning_rules(tool="antigravity")
        assert "ANTIGRAVITY CLI" in ch3
        assert "antigravity-cli/plugins/giljoai/agents" in ch3

    def test_antigravity_and_gemini_ch3_blocks_share_the_at_syntax_template(self):
        """BE-9035a anti-pattern guard: Antigravity's block must come from the SAME
        parameterized template as Gemini's (label swap), not a hand-copied literal
        with independently-drifting prose. Only the label-bearing lines (header +
        final 'installed X agent template' line) may differ."""
        from giljo_mcp.services.protocol_sections.chapters_reference import _CH3_ANTIGRAVITY, _CH3_GEMINI

        gemini_note_lines = _CH3_GEMINI[1].splitlines()
        antigravity_note_lines = _CH3_ANTIGRAVITY[1].splitlines()
        # Lines 0 ("<Label> CLI Note:") and 3 ("... installed <Label> agent template")
        # are label-specific by design; every other line must be byte-identical.
        assert gemini_note_lines[1:3] == antigravity_note_lines[1:3], (
            "platform_note body diverged from the shared template"
        )


class TestReactivationSpawnBlocksCoverage:
    """chapters_reference._REACTIVATION_SPAWN_BLOCKS -- every CLI tool_type
    self-reactivates via its OWN spawn syntax, never the multi_terminal
    ask-the-human block (design §4 item 2: 'the worst' omission)."""

    @pytest.mark.parametrize("tool", _DICT_KEYED_SUBAGENT_TOOLS)
    def test_tool_has_specific_reactivation_block(self, tool):
        from giljo_mcp.services.protocol_sections.chapters_reference import (
            _REACTIVATION_SPAWN_BLOCKS,
            _build_reactivation_spawn_block,
        )

        assert tool in _REACTIVATION_SPAWN_BLOCKS, f"{tool!r} missing a specific reactivation-spawn entry"
        block = _build_reactivation_spawn_block(tool)
        assert block == _REACTIVATION_SPAWN_BLOCKS[tool]
        assert "Open a new session with your AI" not in block, (
            f"{tool!r} reactivation must not tell a self-reactivating CLI to ask the human"
        )

    def test_antigravity_reactivation_uses_at_syntax(self):
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_reactivation_spawn_block

        block = _build_reactivation_spawn_block("antigravity")
        assert "@{role}" in block or "@" in block
        assert "get_job_mission" in block


class TestSpawnWarningMapCoverage:
    """chapters_startup._build_ch1_mission's spawn_warning_map -- every CLI
    tool_type gets its own 'do not spawn during staging' warning."""

    @pytest.mark.parametrize("tool", _DICT_KEYED_SUBAGENT_TOOLS)
    def test_tool_has_specific_warning(self, tool):
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch1_mission

        ch1 = _build_ch1_mission(tool=tool)
        assert "You do NOT execute implementation work directly" not in ch1, (
            f"{tool!r} fell through to the generic spawn warning"
        )

    def test_antigravity_and_gemini_share_the_at_agent_warning(self):
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch1_mission

        gemini_ch1 = _build_ch1_mission(tool="gemini")
        antigravity_ch1 = _build_ch1_mission(tool="antigravity")
        assert "You do NOT invoke @agent commands" in gemini_ch1
        assert "You do NOT invoke @agent commands" in antigravity_ch1


class TestOrchestratorPromptRequestToolLiteral:
    """api.schemas.prompt.OrchestratorPromptRequest.tool -- registry-derived Literal
    (BE-9035a: previously hardcoded to 3 values, 400ing antigravity + generic_mcp)."""

    @pytest.mark.parametrize("tool", SUBAGENT_TOOL_TYPES)
    def test_every_subagent_tool_type_is_accepted(self, tool):
        from api.schemas.prompt import OrchestratorPromptRequest

        request = OrchestratorPromptRequest(project_id="p-1", tool=tool)
        assert request.tool == tool

    def test_unknown_tool_is_rejected(self):
        from pydantic import ValidationError

        from api.schemas.prompt import OrchestratorPromptRequest

        with pytest.raises(ValidationError):
            OrchestratorPromptRequest(project_id="p-1", tool="bogus-tool")


class TestImplementationPromptTypeMapCoverage:
    """thin_prompt_lifecycle._IMPLEMENTATION_PROMPT_TYPE_MAP -- built by iterating
    every registry execution_mode (BE-9035a), so it can never omit one again."""

    def test_map_covers_every_valid_execution_mode(self):
        # BE-9035c: the map is keyed by every ACCEPTED execution mode (canonical +
        # legacy *_cli aliases), so implement() can resolve a stored legacy-token
        # project without a KeyError. VALID (2 canonical) is a subset of these keys.
        from giljo_mcp.platform_registry import ACCEPTED_EXECUTION_MODES
        from giljo_mcp.thin_prompt_lifecycle import _IMPLEMENTATION_PROMPT_TYPE_MAP

        assert set(_IMPLEMENTATION_PROMPT_TYPE_MAP) == ACCEPTED_EXECUTION_MODES

    def test_generic_mcp_maps_to_the_platform_neutral_builder_not_claude(self):
        """The BE-9035a regression this guards: generic_mcp must NOT map to
        'claude_code_execution' (no Claude-specific ToolSearch bootstrap / Task() prose
        into a harness with neither). BE-9099 UPDATE (conscious): the correct neutral
        target is now the harness-neutral SUBAGENT builder, not the multi_terminal
        builder. generic_mcp is a subagent-family (generic-floor) mode — routing it to
        the multi_terminal per-session seed was the very BE-9035c bug BE-9099 fixes. The
        INTENT ('never Claude') is unchanged; the target improved from multi_terminal to
        the proper harness-neutral subagent prompt."""
        from giljo_mcp.thin_prompt_lifecycle import (
            _IMPLEMENTATION_PROMPT_TYPE_MAP,
            SUBAGENT_EXECUTION_PROMPT_TYPE,
        )

        assert _IMPLEMENTATION_PROMPT_TYPE_MAP["generic_mcp"] == SUBAGENT_EXECUTION_PROMPT_TYPE
        assert _IMPLEMENTATION_PROMPT_TYPE_MAP["generic_mcp"] != "claude_code_execution"
        assert _IMPLEMENTATION_PROMPT_TYPE_MAP["generic_mcp"] != "multi_terminal_orchestrator"

    def test_class_attribute_is_the_same_object_as_the_module_constant(self):
        from giljo_mcp.thin_prompt_lifecycle import _IMPLEMENTATION_PROMPT_TYPE_MAP, ThinClientLifecycleMixin

        assert ThinClientLifecycleMixin._IMPLEMENTATION_PROMPT_TYPE_MAP is _IMPLEMENTATION_PROMPT_TYPE_MAP

    def test_supported_execution_modes_gate_signature_unchanged(self):
        """implement() still validates against a registry-derived set (not a
        hand-copied tuple) -- source-text guard against re-introducing the literal."""
        from pathlib import Path

        src = Path("src/giljo_mcp/thin_prompt_lifecycle.py").read_text(encoding="utf-8")
        assert '("claude_code_cli", "multi_terminal", "codex_cli", "gemini_cli", "antigravity_cli")' not in src, (
            "the hand-copied supported_execution_modes tuple was reintroduced"
        )
        # BE-9335: the gate now validates the mode a project actually RUNS in (a chain
        # member resolves the chain's via effective_execution_mode), not the raw column.
        # Guard BOTH halves: the registry-derived membership check is still there, AND
        # the raw-column subject has not come back. Asserting only the former is weaker
        # than the original literal, because "project.execution_mode not in ..." also
        # contains "not in ...".
        assert "not in ACCEPTED_EXECUTION_MODES" in src, (
            "implement() no longer validates the execution mode against the registry-derived set"
        )
        assert "project.execution_mode not in ACCEPTED_EXECUTION_MODES" not in src, (
            "implement() validates the raw project column again — a chain member must be "
            "gated on the mode it actually runs in, not the one it was staged with"
        )


class TestGiljoSetupPlatformLiteral:
    """api/endpoints/mcp_tools/_setup_tools.py giljo_setup's platform Literal is
    derived from EXPORT_PLATFORMS (BE-9035a item 5 cleanup)."""

    def test_literal_matches_export_platforms(self):
        from typing import get_args

        from api.endpoints.mcp_tools._setup_tools import giljo_setup
        from giljo_mcp.platform_registry import EXPORT_PLATFORMS

        sig = inspect.signature(giljo_setup)
        annotation = sig.parameters["platform"].annotation
        assert get_args(annotation) == EXPORT_PLATFORMS
