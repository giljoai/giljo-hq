# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp import platform_registry as reg
from giljo_mcp.harness_resolver import GENERIC_HARNESS, harness_from_client_info
from giljo_mcp.prompts.launch_command_synth import AUTONOMY_FLAGS, PROMPT_FLAGS, resolve_binary
from giljo_mcp.services.protocol_sections.agent_lifecycle import _FORBIDDEN_BY_TOOL, _WAKE_BY_TOOL
from giljo_mcp.services.protocol_sections.chapters_reference import (
    _build_ch3_spawning_rules,
    _build_reactivation_spawn_block,
)
from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch1_mission
from giljo_mcp.services.protocol_sections.orchestrator_body import _SUBAGENT_SPAWN_BY_TOOL
from giljo_mcp.thin_prompt_lifecycle import (
    SUBAGENT_EXECUTION_PROMPT_TYPE,
    select_implementation_prompt_type,
)
from giljo_mcp.tools.tool_accessor._project_tools import _STAGE_MODE_MAP


RETIRED_TOOL_TYPES = ("gemini", "antigravity")
RETIRED_LEGACY_MODES = ("gemini_cli", "antigravity_cli")
RETIRED_CLIENT_NAMES = ("gemini-cli-mcp-client", "antigravity-client")




def test_registry_keeps_exactly_the_surviving_harness_rows():
    assert {h.tool_type for h in reg.HARNESSES} == {"claude-code", "codex", "opencode"}


@pytest.mark.parametrize("tool_type", RETIRED_TOOL_TYPES)
def test_get_harness_returns_none_for_retired_tool_type(tool_type):
    assert reg.get_harness(tool_type) is None
    assert tool_type not in reg.SUBAGENT_TOOL_TYPES
    assert tool_type not in reg.HARNESS_CLI_TOOL_TYPES


def test_export_platforms_drop_retired_targets():
    assert reg.EXPORT_PLATFORMS == ("claude_code", "codex_cli", "opencode", "generic")
    assert frozenset({"codex_cli"}) == reg.SKILL_SLASH_PLATFORMS


@pytest.mark.parametrize("name", RETIRED_CLIENT_NAMES)
def test_client_info_detection_resolves_retired_clients_to_generic(name):
    assert harness_from_client_info(name, "1.0.0") == GENERIC_HARNESS




@pytest.mark.parametrize("mode", RETIRED_LEGACY_MODES)
def test_legacy_mode_token_is_still_accepted_but_hints_generic(mode):
    assert mode in reg.LEGACY_MODE_ALIASES
    assert mode in reg.ACCEPTED_EXECUTION_MODES
    assert reg.normalize_execution_mode(mode) == reg.MODE_SUBAGENT
    assert reg.tool_for_mode(mode) == GENERIC_HARNESS
    assert reg.effective_harness(mode, None) == GENERIC_HARNESS
    assert reg.stage_mode_token(mode) == reg.MODE_SUBAGENT
    assert reg.has_local_agent_file_channel(mode) is False


@pytest.mark.parametrize("mode", RETIRED_LEGACY_MODES)
def test_implement_prompt_for_legacy_mode_uses_the_neutral_subagent_builder(mode):
    prompt_type, resolved = select_implementation_prompt_type(mode, None)
    assert prompt_type == SUBAGENT_EXECUTION_PROMPT_TYPE
    assert resolved == GENERIC_HARNESS




@pytest.mark.parametrize("tool_type", RETIRED_TOOL_TYPES)
def test_stamped_retired_harness_is_read_as_generic(tool_type):
    assert reg.effective_harness(reg.MODE_SUBAGENT, {"harness": tool_type}) == GENERIC_HARNESS
    assert reg.effective_harness(None, {"resolved_harness": tool_type}) == GENERIC_HARNESS
    prompt_type, resolved = select_implementation_prompt_type(reg.MODE_SUBAGENT, tool_type)
    assert prompt_type == SUBAGENT_EXECUTION_PROMPT_TYPE
    assert resolved == GENERIC_HARNESS


@pytest.mark.parametrize("tool_type", RETIRED_TOOL_TYPES)
def test_protocol_prose_for_retired_tool_type_is_the_generic_render(tool_type):
    assert _build_ch3_spawning_rules(tool=tool_type) == _build_ch3_spawning_rules(tool=GENERIC_HARNESS)
    assert _build_reactivation_spawn_block(tool_type) == _build_reactivation_spawn_block(GENERIC_HARNESS)
    assert _build_ch1_mission(tool=tool_type) == _build_ch1_mission(tool=GENERIC_HARNESS)
    assert tool_type not in _FORBIDDEN_BY_TOOL
    assert tool_type not in _WAKE_BY_TOOL
    assert tool_type not in _SUBAGENT_SPAWN_BY_TOOL
    assert "@agent" not in _build_ch3_spawning_rules(tool=tool_type)




@pytest.mark.parametrize("alias", RETIRED_TOOL_TYPES)
def test_stage_project_retired_mode_alias_stages_like_plain_subagent(alias):
    assert _STAGE_MODE_MAP[alias] == _STAGE_MODE_MAP[reg.MODE_SUBAGENT]
    assert _STAGE_MODE_MAP[alias][1] == reg.MODE_SUBAGENT




@pytest.mark.parametrize("cli_tool", RETIRED_TOOL_TYPES)
def test_launch_binary_for_retired_cli_tool_falls_back_to_default(cli_tool):
    assert resolve_binary(cli_tool) == resolve_binary(None)
    assert cli_tool not in reg.CLI_BINARIES


def test_no_retired_launcher_flags_remain():
    for binary in ("gemini", "agy"):
        assert binary not in AUTONOMY_FLAGS
        assert binary not in PROMPT_FLAGS




def test_surviving_harnesses_still_resolve():
    assert reg.get_harness("claude-code") is not None
    assert reg.get_harness("codex") is not None
    assert reg.get_harness("opencode") is not None
    assert harness_from_client_info("claude-code") == "claude-code"
    assert harness_from_client_info("codex-mcp-client") == "codex"
    assert reg.tool_for_mode("claude_code_cli") == "claude-code"
    assert reg.tool_for_mode("generic_mcp") == GENERIC_HARNESS
    assert reg.effective_harness("subagent", {"harness": "codex"}) == "codex"


def test_generic_and_unknown_still_fold_to_the_floor():
    assert harness_from_client_info("") == GENERIC_HARNESS
    assert harness_from_client_info("something-new") == GENERIC_HARNESS
    assert reg.effective_harness("subagent", None) == GENERIC_HARNESS
