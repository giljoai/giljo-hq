# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect

import pytest

from giljo_mcp.platform_registry import SUBAGENT_TOOL_TYPES


_DICT_KEYED_SUBAGENT_TOOLS = tuple(t for t in SUBAGENT_TOOL_TYPES if t not in ("generic_mcp", "opencode"))


class TestSubagentSpawnByToolCoverage:

    @pytest.mark.parametrize("tool", _DICT_KEYED_SUBAGENT_TOOLS)
    def test_tool_has_specific_entry(self, tool):
        from giljo_mcp.services.protocol_sections.orchestrator_body import (
            _SUBAGENT_SPAWN_BY_TOOL,
            _SUBAGENT_SPAWN_GENERIC,
        )

        assert tool in _SUBAGENT_SPAWN_BY_TOOL, f"{tool!r} missing a specific spawn-syntax entry"
        assert _SUBAGENT_SPAWN_BY_TOOL[tool] != _SUBAGENT_SPAWN_GENERIC


class TestCh3SpawnBlocksCoverage:

    @pytest.mark.parametrize("tool", _DICT_KEYED_SUBAGENT_TOOLS)
    def test_tool_has_specific_ch3_block(self, tool):
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch3_spawning_rules

        ch3 = _build_ch3_spawning_rules(tool=tool)
        assert "ANY MCP-CONNECTED AGENT" not in ch3, f"{tool!r} fell through to the generic CH3 block"


class TestReactivationSpawnBlocksCoverage:

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


class TestSpawnWarningMapCoverage:

    @pytest.mark.parametrize("tool", _DICT_KEYED_SUBAGENT_TOOLS)
    def test_tool_has_specific_warning(self, tool):
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch1_mission

        ch1 = _build_ch1_mission(tool=tool)
        assert "You do NOT execute implementation work directly" not in ch1, (
            f"{tool!r} fell through to the generic spawn warning"
        )


class TestOrchestratorPromptRequestToolLiteral:

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

    def test_map_covers_every_valid_execution_mode(self):
        from giljo_mcp.platform_registry import ACCEPTED_EXECUTION_MODES
        from giljo_mcp.thin_prompt_lifecycle import _IMPLEMENTATION_PROMPT_TYPE_MAP

        assert set(_IMPLEMENTATION_PROMPT_TYPE_MAP) == ACCEPTED_EXECUTION_MODES

    def test_generic_mcp_maps_to_the_platform_neutral_builder_not_claude(self):
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
        from pathlib import Path

        src = Path("src/giljo_mcp/thin_prompt_lifecycle.py").read_text(encoding="utf-8")
        assert '("claude_code_cli", "multi_terminal", "codex_cli", "gemini_cli", "antigravity_cli")' not in src, (
            "the hand-copied supported_execution_modes tuple was reintroduced"
        )
        assert "not in ACCEPTED_EXECUTION_MODES" in src, (
            "implement() no longer validates the execution mode against the registry-derived set"
        )
        assert "project.execution_mode not in ACCEPTED_EXECUTION_MODES" not in src, (
            "implement() validates the raw project column again — a chain member must be "
            "gated on the mode it actually runs in, not the one it was staged with"
        )


class TestGiljoSetupPlatformLiteral:

    def test_literal_matches_export_platforms(self):
        from typing import get_args

        from api.endpoints.mcp_tools._setup_tools import giljo_setup
        from giljo_mcp.platform_registry import EXPORT_PLATFORMS

        sig = inspect.signature(giljo_setup)
        annotation = sig.parameters["platform"].annotation
        assert get_args(annotation) == EXPORT_PLATFORMS
