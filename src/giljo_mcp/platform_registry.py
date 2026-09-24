# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from dataclasses import dataclass

from giljo_mcp.harness_resolver import (
    GENERIC_HARNESS,
    HARNESS_CLAUDE_CODE,
    HARNESS_CODEX,
    HARNESS_OPENCODE,
    _detected_harness_from_session,
    harness_from_client_info,  # noqa: F401  (re-exported for callers)
)


logger = logging.getLogger(__name__)


WORKSPACE_SHARED_WORKING_TREE = "shared_working_tree"
WORKSPACE_ISOLATED_PR = "isolated_pr"
WORKSPACE_NONE = "none"

VALID_WORKSPACE_MODELS: frozenset[str] = frozenset(
    {WORKSPACE_SHARED_WORKING_TREE, WORKSPACE_ISOLATED_PR, WORKSPACE_NONE}
)


EXPORT_CLAUDE_CODE = "claude_code"
EXPORT_CODEX_CLI = "codex_cli"
EXPORT_OPENCODE = "opencode"
EXPORT_GENERIC = "generic"


MODE_MULTI_TERMINAL = "multi_terminal"
MODE_SUBAGENT = "subagent"

MULTI_TERMINAL = MODE_MULTI_TERMINAL
DEFAULT_TOOL_TYPE = MULTI_TERMINAL


@dataclass(frozen=True)
class Mode:

    execution_mode: str
    display_label: str
    is_subagent: bool
    can_spawn_terminals: bool = True


MODES: tuple[Mode, ...] = (
    Mode(MODE_MULTI_TERMINAL, "Multi-Terminal", is_subagent=False, can_spawn_terminals=True),
    Mode(MODE_SUBAGENT, "Subagent", is_subagent=True, can_spawn_terminals=False),
)

_BY_MODE: dict[str, Mode] = {m.execution_mode: m for m in MODES}


@dataclass(frozen=True)
class Harness:

    tool_type: str
    cli_tool: str
    cli_binary: str
    display_label: str
    spawn_syntax: str
    export_platform: str | None = None
    launch_shell: str = "pwsh"
    launch_prompt_flag: str | None = None
    autonomy_flag: str | None = None

    @property
    def is_subagent(self) -> bool:
        return True


HARNESSES: tuple[Harness, ...] = (
    Harness(
        HARNESS_CLAUDE_CODE,
        "claude",
        "claude",
        "Claude Code",
        spawn_syntax="Task(subagent_type=X) where X = agent_name from spawn_job.",
        export_platform=EXPORT_CLAUDE_CODE,
        autonomy_flag="--dangerously-skip-permissions",
    ),
    Harness(
        HARNESS_CODEX,
        "codex",
        "codex",
        "Codex",
        spawn_syntax=(
            "spawn_agent(agent='gil-{agent_name}') where agent_name comes from spawn_job. "
            "CRITICAL: prepend 'gil-' to every agent_name when using Codex CLI."
        ),
        export_platform=EXPORT_CODEX_CLI,
        autonomy_flag="--dangerously-bypass-approvals-and-sandbox",
    ),
    Harness(
        HARNESS_OPENCODE,
        "opencode",
        "opencode",
        "opencode",
        spawn_syntax=(
            "Use your harness's own subagent/delegate mechanism to spawn the agent named "
            "by spawn_job (agent_name used as-is); if none exists, self-adopt the role."
        ),
        export_platform=EXPORT_OPENCODE,
        launch_shell="cmd",
        launch_prompt_flag="--prompt",
        autonomy_flag="--auto",
    ),
)

_BY_HARNESS: dict[str, Harness] = {h.tool_type: h for h in HARNESSES}


RETIRED_LEGACY_MODES: tuple[str, ...] = ("gemini_cli", "antigravity_cli")
RETIRED_HARNESS_TOKENS: tuple[str, ...] = ("gemini", "antigravity")

LEGACY_MODE_TO_HARNESS: dict[str, str] = {
    "claude_code_cli": HARNESS_CLAUDE_CODE,
    "codex_cli": HARNESS_CODEX,
    **dict.fromkeys(RETIRED_LEGACY_MODES, GENERIC_HARNESS),
    "generic_mcp": GENERIC_HARNESS,
}

LEGACY_MODE_ALIASES: frozenset[str] = frozenset(LEGACY_MODE_TO_HARNESS)


def normalize_execution_mode(execution_mode: str | None) -> str | None:
    if execution_mode is None:
        return None
    if execution_mode == MODE_MULTI_TERMINAL:
        return MODE_MULTI_TERMINAL
    return MODE_SUBAGENT



EXECUTION_MODES: tuple[str, ...] = tuple(m.execution_mode for m in MODES)

VALID_EXECUTION_MODES: frozenset[str] = frozenset(EXECUTION_MODES)

ACCEPTED_EXECUTION_MODES: frozenset[str] = VALID_EXECUTION_MODES | LEGACY_MODE_ALIASES

SUBAGENT_EXECUTION_MODES: frozenset[str] = frozenset({MODE_SUBAGENT} | LEGACY_MODE_ALIASES)

LOCAL_AGENT_FILE_MODES: frozenset[str] = frozenset(
    {MODE_SUBAGENT} | {mode for mode, harness in LEGACY_MODE_TO_HARNESS.items() if harness != GENERIC_HARNESS}
)

SUBAGENT_TOOL_TYPES: tuple[str, ...] = (*(h.tool_type for h in HARNESSES), "generic_mcp")

TERMINAL_CAPABLE_MODES: frozenset[str] = frozenset(m.execution_mode for m in MODES if m.can_spawn_terminals)

EXECUTION_MODE_TO_TOOL: dict[str, str] = {
    MODE_MULTI_TERMINAL: MODE_MULTI_TERMINAL,
    MODE_SUBAGENT: GENERIC_HARNESS,
    **LEGACY_MODE_TO_HARNESS,
}

CLI_BINARIES: dict[str, str] = {h.cli_tool: h.cli_binary for h in HARNESSES}


@dataclass(frozen=True)
class Platform:

    execution_mode: str
    tool_type: str
    cli_tool: str | None
    cli_binary: str | None
    display_label: str
    is_subagent: bool
    spawn_syntax: str | None = None
    template_locations: tuple[str, ...] = ()
    export_platform: str | None = None
    can_spawn_terminals: bool = True
    workspace_model: str = "shared_working_tree"

    @property
    def has_shell(self) -> bool:
        return self.workspace_model != WORKSPACE_NONE


PRESET_WEB_SANDBOX = "web_sandbox"
PRESET_DESKTOP_APP = "desktop_app"
PRESET_CHAT = "chat"

PLATFORM_PRESETS: tuple[Platform, ...] = (
    Platform(
        PRESET_WEB_SANDBOX,
        PRESET_WEB_SANDBOX,
        None,
        None,
        "Web Sandbox",
        is_subagent=True,
        can_spawn_terminals=False,
        workspace_model=WORKSPACE_ISOLATED_PR,
    ),
    Platform(
        PRESET_DESKTOP_APP,
        PRESET_DESKTOP_APP,
        None,
        None,
        "Desktop App",
        is_subagent=True,
        can_spawn_terminals=False,
        workspace_model=WORKSPACE_SHARED_WORKING_TREE,
    ),
    Platform(
        PRESET_CHAT,
        PRESET_CHAT,
        None,
        None,
        "Chat",
        is_subagent=True,
        can_spawn_terminals=False,
        workspace_model=WORKSPACE_NONE,
    ),
)

_BY_PRESET: dict[str, Platform] = {p.execution_mode: p for p in PLATFORM_PRESETS}
PRESET_NAMES: tuple[str, ...] = tuple(p.execution_mode for p in PLATFORM_PRESETS)
VALID_PRESETS: frozenset[str] = frozenset(PRESET_NAMES)

NON_TERMINAL_PRESETS: frozenset[str] = frozenset(
    p.execution_mode for p in PLATFORM_PRESETS if not p.can_spawn_terminals
)

PRESET_WORKSPACE_MODELS: dict[str, str] = {p.execution_mode: p.workspace_model for p in PLATFORM_PRESETS}



_EXPORT_BY_HARNESS: dict[str, str] = {h.tool_type: h.export_platform for h in HARNESSES if h.export_platform}

EXPORT_PLATFORMS: tuple[str, ...] = (
    *(h.export_platform for h in HARNESSES if h.export_platform),
    EXPORT_GENERIC,
)

VALID_EXPORT_PLATFORMS: frozenset[str] = frozenset(EXPORT_PLATFORMS)

SKILL_SLASH_PLATFORMS: frozenset[str] = frozenset({EXPORT_CODEX_CLI})

SKILL_SLASH_TOOL_TYPES: frozenset[str] = frozenset(
    h.tool_type for h in HARNESSES if h.export_platform in SKILL_SLASH_PLATFORMS
)


def giljo_invocation(tool_type: str | None) -> str:
    return "$giljo" if (tool_type or "") in SKILL_SLASH_TOOL_TYPES else "/giljo"


def task_list_phrase(tool_type: str | None) -> str:
    return "TodoWrite list" if (tool_type or "") == HARNESS_CLAUDE_CODE else "task list"


def export_platform_pattern() -> str:
    return "^(" + "|".join(EXPORT_PLATFORMS) + ")$"


def get_mode(execution_mode: str | None) -> Mode | None:
    return _BY_MODE.get(execution_mode or "")


get_platform = get_mode


GENERIC_SUBAGENT_SPAWN_SYNTAX = (
    "Use your harness's own subagent-spawn mechanism (a Task tool, an agent spawner, an "
    "@-mention, or a delegate command) to invoke the agent named by spawn_job — agent_name "
    "is used as-is. If ANY spawn mechanism exists in your harness, using it is MANDATORY. "
    "Only if your harness has NO spawn mechanism at all: self-adopt the role and do the "
    "work yourself in this session."
)


def get_harness(tool_type: str | None) -> Harness | None:
    return _BY_HARNESS.get(tool_type or "")


def get_preset(preset_name: str | None) -> Platform | None:
    return _BY_PRESET.get(preset_name or "")


def select_effective_preset(
    declared: str | None = None,
    capabilities: dict[str, object] | None = None,
) -> Platform | None:
    if declared:
        preset = _BY_PRESET.get(declared.strip())
        if preset is not None:
            return preset
    if capabilities:
        detected = capabilities.get("preset")
        if isinstance(detected, str):
            preset = _BY_PRESET.get(detected.strip())
            if preset is not None:
                return preset
    return None


def terminal_available(capabilities: dict[str, object] | None = None) -> bool:
    if capabilities:
        signal = capabilities.get("can_spawn_terminals")
        if isinstance(signal, bool):
            return signal
    return True


def tool_for_mode(execution_mode: str | None) -> str:
    return EXECUTION_MODE_TO_TOOL.get(execution_mode or "", DEFAULT_TOOL_TYPE)


def is_subagent_mode(execution_mode: str | None) -> bool:
    return execution_mode in SUBAGENT_EXECUTION_MODES


def has_local_agent_file_channel(execution_mode: str | None) -> bool:
    return execution_mode in LOCAL_AGENT_FILE_MODES


def is_subagent_render(execution_mode_or_tool: str | None) -> bool:
    token = execution_mode_or_tool or ""
    if not token or token == MULTI_TERMINAL:
        return False
    if token in SUBAGENT_EXECUTION_MODES:
        return True
    if token in _BY_HARNESS:
        return True
    preset = _BY_PRESET.get(token)
    if preset is not None:
        return preset.is_subagent
    mode = _BY_MODE.get(token)
    if mode is not None:
        return mode.is_subagent
    return True


def stage_mode_token(execution_mode: str | None) -> str:
    if execution_mode == MODE_MULTI_TERMINAL:
        return MODE_MULTI_TERMINAL
    legacy_harness = LEGACY_MODE_TO_HARNESS.get(execution_mode or "")
    if legacy_harness is not None:
        harness = _BY_HARNESS.get(legacy_harness)
        if harness is not None:
            return harness.cli_tool
        return MODE_SUBAGENT
    if execution_mode == MODE_SUBAGENT:
        return MODE_SUBAGENT
    return MODE_MULTI_TERMINAL


def execution_mode_pattern() -> str:
    ordered = list(EXECUTION_MODES) + list(LEGACY_MODE_TO_HARNESS)
    return "^(" + "|".join(ordered) + ")$"


def tool_type_pattern() -> str:
    return "^(" + "|".join(SUBAGENT_TOOL_TYPES) + ")$"


def mode_label_list() -> str:
    return " / ".join(m.display_label for m in MODES)


def mode_csv() -> str:
    return ", ".join(EXECUTION_MODES)



HARNESS_CLI_TOOL_TYPES: frozenset[str] = frozenset(h.tool_type for h in HARNESSES)


def effective_harness(declared_mode: str | None, session: object | None = None) -> str:
    detected = _detected_harness_from_session(session)
    if detected in HARNESS_CLI_TOOL_TYPES:
        return detected
    if declared_mode:
        hint = tool_for_mode(declared_mode)
        if hint in HARNESS_CLI_TOOL_TYPES:
            return hint
    return GENERIC_HARNESS
