# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""PlatformRegistry -- one source of truth for orchestration identity.

BE-9035c collapses the historical SIX ``execution_mode`` values onto TWO
orthogonal axes:

* **MODES (topology, user-declared, 2 values):** :data:`MODE_MULTI_TERMINAL`
  (one terminal per agent, a human watches the fleet) vs :data:`MODE_SUBAGENT`
  (one orchestrator session manages workers). This is the project column and the
  UI choice. The 5 legacy per-CLI tokens (``claude_code_cli`` / ``codex_cli`` /
  ``gemini_cli`` / ``antigravity_cli`` / ``generic_mcp``) live in prod + CE
  self-hoster DBs FOREVER; they are accepted at every validation boundary as
  :data:`LEGACY_MODE_ALIASES` and folded onto ``subagent`` by
  :func:`normalize_execution_mode` (no migration -- tolerance in code, DESIGN §3).
* **HARNESSES (which CLI/agent app drives the session, runtime-resolved):**
  claude-code / codex / gemini / antigravity / opencode, plus the ``generic``
  fail-safe floor. Resolved from the MCP ``initialize`` handshake's clientInfo
  (BE-9035b :func:`harness_from_client_info`), NEVER declared by the user. A
  harness row carries the per-CLI knowledge that used to hang off the per-CLI
  ``Platform`` rows -- spawn syntax, launcher binary, template install locations,
  export vocabulary token.

The precedence rule (BE-9035b): for harness-specific RENDERING, a DETECTED harness
beats a DECLARED legacy CLI token (:func:`effective_harness`); a declared token is
only a hint used when detection is absent. Topology is 100% declared, never
detected. For the orthogonal harness PRESET axis (web_sandbox / desktop_app / chat)
the existing declared-beats-detected rule stays (:func:`select_effective_preset`).

The HO1020 fail-safe semantics are preserved: an unknown/unmapped mode resolves to
the platform-neutral ``multi_terminal`` tool via :func:`tool_for_mode`, and an
unknown/unrecognized clientInfo resolves to ``generic`` -- never crashing the render
layer.

Edition Scope: Both.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

# Harness token vocabulary + the runtime clientInfo resolver live in the leaf module
# harness_resolver (BE-9035c split for the file-size guardrail). Imported here so the
# HARNESSES table + derived constants reference one source, and RE-EXPORTED so existing
# ``from platform_registry import harness_from_client_info`` / ``HARNESS_CLAUDE_CODE``
# callers are unchanged. ``effective_harness`` (the two-axis precedence helper) stays
# below — it bridges the mode + harness axes and needs tool_for_mode.
from giljo_mcp.harness_resolver import (
    GENERIC_HARNESS,
    HARNESS_ANTIGRAVITY,
    HARNESS_CLAUDE_CODE,
    HARNESS_CODEX,
    HARNESS_GEMINI,
    HARNESS_OPENCODE,
    _detected_harness_from_session,
    harness_from_client_info,  # noqa: F401  (re-exported for callers)
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# workspace_model vocabulary (INF-8003e). The delivery axis, orthogonal to
# can_spawn_terminals -- named once here so the preset rows and any consumer (the
# (f) rendering layer) reference the constant, never a bare literal.
# ---------------------------------------------------------------------------
WORKSPACE_SHARED_WORKING_TREE = "shared_working_tree"  # writes into the shared local checkout
WORKSPACE_ISOLATED_PR = "isolated_pr"  # delivers an isolated branch/PR (web coding sandbox)
WORKSPACE_NONE = "none"  # no filesystem workspace (pure chat surface)

VALID_WORKSPACE_MODELS: frozenset[str] = frozenset(
    {WORKSPACE_SHARED_WORKING_TREE, WORKSPACE_ISOLATED_PR, WORKSPACE_NONE}
)


# Export/download platform vocabulary (BE-6117). This axis is DISTINCT from
# execution_mode: Claude drops the ``_cli`` suffix (``claude_code``),
# ``multi_terminal`` is not an export target, and ``generic`` is a pseudo-platform.
# Named once here so the duplicated frozensets/regex/dicts that were copied across
# slash_command_templates, agent_template_assembler, downloads, and file_staging
# all reference the registry.
EXPORT_CLAUDE_CODE = "claude_code"
EXPORT_GEMINI_CLI = "gemini_cli"
EXPORT_CODEX_CLI = "codex_cli"
EXPORT_ANTIGRAVITY_CLI = "antigravity_cli"
EXPORT_GENERIC = "generic"


# ---------------------------------------------------------------------------
# Axis 1 -- MODES: the topology the user declares (BE-9035c). Exactly two rows.
# ---------------------------------------------------------------------------
MODE_MULTI_TERMINAL = "multi_terminal"
MODE_SUBAGENT = "subagent"

# Alias kept for the many branch guards that reference the platform-neutral token.
# ``multi_terminal`` is both a mode and the HO1020 fail-safe ``tool_type``.
MULTI_TERMINAL = MODE_MULTI_TERMINAL
DEFAULT_TOOL_TYPE = MULTI_TERMINAL


@dataclass(frozen=True)
class Mode:
    """A project topology -- one of the two user-declared execution modes.

    Attributes:
        execution_mode: the ``projects.execution_mode`` column value
            (``"multi_terminal"`` or ``"subagent"``).
        display_label: user-facing label in the dashboard mode picker.
        is_subagent: ``True`` for ``subagent`` (the orchestrator's harness returns a
            spawned agent's result inline); ``False`` for ``multi_terminal``.
        can_spawn_terminals: whether the mode is INTRINSICALLY terminal-capable.
            ``multi_terminal`` is (a human opens a terminal per agent); ``subagent``
            is NOT -- terminal ability there is a runtime SESSION/harness property,
            never assumed from the mode. So ``subagent`` is the mode deliberately
            absent from :data:`TERMINAL_CAPABLE_MODES`.
    """

    execution_mode: str
    display_label: str
    is_subagent: bool
    can_spawn_terminals: bool = True


MODES: tuple[Mode, ...] = (
    # multi_terminal first so the derived regex/message ordering stays canonical.
    Mode(MODE_MULTI_TERMINAL, "Multi-Terminal", is_subagent=False, can_spawn_terminals=True),
    Mode(MODE_SUBAGENT, "Subagent", is_subagent=True, can_spawn_terminals=False),
)

_BY_MODE: dict[str, Mode] = {m.execution_mode: m for m in MODES}


# ---------------------------------------------------------------------------
# Axis 2 -- HARNESSES: which CLI / agent app drives the session (BE-9035c). The
# per-CLI knowledge table -- runtime-RESOLVED from clientInfo, never declared. Each
# row's ``tool_type`` is the render key the prose dispatchers already branch on
# (claude-code / codex / gemini / antigravity / opencode). ``generic`` has NO row --
# it is the floor handled by the render fallbacks + the universal subagent prose.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Harness:
    """Identity + behavior knowledge for one detectable CLI harness.

    Attributes:
        tool_type: the protocol/render key (e.g. ``"claude-code"`` -- note the
            hyphen -- ``"codex"``). DOUBLES as the harness token.
        cli_tool: the ``agent_templates.cli_tool`` vocabulary token (``"claude"``).
        cli_binary: the launcher binary (``"claude"``, ``"agy"``, ``"opencode"``).
        display_label: user-facing harness name (the "detected: <harness>" chip).
        spawn_syntax: the orchestrator-facing ``task_tool_mapping`` -- how the
            orchestrator invokes a spawned subagent under this harness.
        template_locations: agent-template install directories surfaced in the
            orchestrator's CLI mode rules.
        export_platform: this harness's token in the export/download vocabulary
            (``None`` when the harness is not an export target -- opencode today).
        launch_shell: the terminal wrapper the multi_terminal launch line uses --
            ``"pwsh"`` (``pwsh -NoExit``) for the 4 classic CLIs, ``"cmd"``
            (``cmd /k``) for opencode so ``opencode.cmd`` resolves from PATH
            (BE-9015).
        launch_prompt_flag: the flag that seeds a prompt into a fresh launch
            (``opencode --prompt``); ``None`` when the launcher takes the prompt
            positionally (the classic CLIs).
        autonomy_flag: the launcher's skip-permissions / autonomy flag, or ``None``.
    """

    tool_type: str
    cli_tool: str
    cli_binary: str
    display_label: str
    spawn_syntax: str
    template_locations: tuple[str, ...]
    export_platform: str | None = None
    launch_shell: str = "pwsh"
    launch_prompt_flag: str | None = None
    autonomy_flag: str | None = None

    @property
    def is_subagent(self) -> bool:
        """Every harness renders as a subagent orchestrator (never multi_terminal)."""
        return True


HARNESSES: tuple[Harness, ...] = (
    Harness(
        HARNESS_CLAUDE_CODE,
        "claude",
        "claude",
        "Claude Code",
        spawn_syntax="Task(subagent_type=X) where X = agent_name from spawn_job.",
        template_locations=("{project}/.claude/agents/", "~/.claude/agents/"),
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
        template_locations=("~/.codex/agents/", "{project}/.codex/agents/"),
        export_platform=EXPORT_CODEX_CLI,
        autonomy_flag="--dangerously-bypass-approvals-and-sandbox",
    ),
    Harness(
        HARNESS_GEMINI,
        "gemini",
        "gemini",
        "Gemini",
        spawn_syntax="@{agent_name} or /agent {agent_name} — agent_name is used as-is (no prefix).",
        template_locations=("~/.gemini/agents/", "{project}/.gemini/agents/"),
        export_platform=EXPORT_GEMINI_CLI,
        autonomy_flag="--yolo",
    ),
    Harness(
        HARNESS_ANTIGRAVITY,
        "antigravity",
        "agy",
        "Antigravity",
        # BE-6041b D1-B: agy reuses Gemini's @-syntax spawn behavior; plugins/agents
        # live under the antigravity-cli plugin tree.
        spawn_syntax="@{agent_name} or /agent {agent_name} — agent_name is used as-is (no prefix).",
        template_locations=(
            "~/.gemini/antigravity-cli/plugins/giljoai/agents/",
            "{project}/.gemini/antigravity-cli/plugins/giljoai/agents/",
        ),
        export_platform=EXPORT_ANTIGRAVITY_CLI,
        # BE-6205: agy's real autonomy flag (verified via `agy --help`) is
        # --dangerously-skip-permissions, NOT Gemini's --yolo. agy shares Gemini's
        # @-syntax for agent SPAWN, not its autonomy flag.
        autonomy_flag="--dangerously-skip-permissions",
    ),
    Harness(
        HARNESS_OPENCODE,
        "opencode",
        "opencode",
        "opencode",
        # BE-9035c: opencode self-identifies via clientInfo (name=="opencode",
        # BE-9035 harvest) so it is a FIRST-CLASS detectable harness, terminal-capable.
        # Its subagent-spawn mechanism is not a documented inline syntax, so the
        # orchestrator spawns via whatever mechanism its harness provides (the
        # universal subagent prose covers it). Launch is the BE-9015 verified
        # ``cmd /k opencode --prompt "<prompt>"`` (cmd wrapper so opencode.cmd resolves
        # from PATH). NOT an export target (no agent-template install path shipped).
        spawn_syntax=(
            "Use your harness's own subagent/delegate mechanism to spawn the agent named "
            "by spawn_job (agent_name used as-is); if none exists, self-adopt the role."
        ),
        template_locations=(),
        export_platform=None,
        launch_shell="cmd",
        launch_prompt_flag="--prompt",
    ),
)

_BY_HARNESS: dict[str, Harness] = {h.tool_type: h for h in HARNESSES}


# ---------------------------------------------------------------------------
# Legacy tolerance (BE-9035c, DESIGN §3). The old 5 per-CLI execution_mode tokens
# are stored in prod + CE DBs forever. They are NEVER rewritten (zero migrations);
# they are ACCEPTED at every validation boundary and NORMALIZED onto the 2 modes at
# read time. Each maps to the harness it historically implied, so a declared legacy
# token still functions as a harness hint through :func:`effective_harness`.
# ---------------------------------------------------------------------------
LEGACY_MODE_TO_HARNESS: dict[str, str] = {
    "claude_code_cli": HARNESS_CLAUDE_CODE,
    "codex_cli": HARNESS_CODEX,
    "gemini_cli": HARNESS_GEMINI,
    "antigravity_cli": HARNESS_ANTIGRAVITY,
    "generic_mcp": GENERIC_HARNESS,
}

# The old 5 tokens, accepted (never rejected) at validation boundaries.
LEGACY_MODE_ALIASES: frozenset[str] = frozenset(LEGACY_MODE_TO_HARNESS)


def normalize_execution_mode(execution_mode: str | None) -> str | None:
    """Fold any execution_mode token onto one of the 2 canonical modes (DESIGN §3).

    ``None`` stays ``None`` (unselected); ``multi_terminal`` stays ``multi_terminal``;
    EVERYTHING else (``subagent``, the 5 legacy CLI tokens, and any unknown non-empty
    token) folds to ``subagent``. Pure, total, and never raises -- the single place
    the collapse rule lives. Stored values are NEVER rewritten; callers normalize at
    read/branch time.
    """
    if execution_mode is None:
        return None
    if execution_mode == MODE_MULTI_TERMINAL:
        return MODE_MULTI_TERMINAL
    return MODE_SUBAGENT


# ---------------------------------------------------------------------------
# Derived identity constants -- consumed by the former scattered literal sites.
# ---------------------------------------------------------------------------

# The 2 canonical, user-selectable execution modes, in canonical order.
EXECUTION_MODES: tuple[str, ...] = tuple(m.execution_mode for m in MODES)

# The valid set a NEW project write (UI) may hold (NULL = not yet selected, handled
# separately by the gate). Exactly the 2 canonical modes.
VALID_EXECUTION_MODES: frozenset[str] = frozenset(EXECUTION_MODES)

# What a validation BOUNDARY accepts: the 2 canonical modes PLUS the 5 legacy
# aliases (tolerance -- legacy rows must never hard-fail a project update / sequence
# run / chain tool). Distinct from VALID_EXECUTION_MODES, which governs new writes.
ACCEPTED_EXECUTION_MODES: frozenset[str] = VALID_EXECUTION_MODES | LEGACY_MODE_ALIASES

# Modes (canonical + legacy) that render as a subagent orchestrator. ``subagent`` +
# all 5 legacy tokens (every legacy CLI folds to subagent); ``multi_terminal`` is
# deliberately excluded. Consumed by the is_subagent gates that must fire for both
# new subagent projects and stored legacy CLI projects.
SUBAGENT_EXECUTION_MODES: frozenset[str] = frozenset({MODE_SUBAGENT} | LEGACY_MODE_ALIASES)

# tool_type values a subagent PROMPT / render request may target, in canonical order:
# the 5 detectable harness tool_types (claude-code / codex / gemini / antigravity /
# opencode) PLUS the legacy ``generic_mcp`` token (tolerance). Consumed by
# tool_type_pattern() and by request-schema Literal types (BE-9035a) so a new harness's
# tool_type is accepted at every validation boundary without a second hand-copied list
# to forget. Registry-derived -- never a bare literal.
SUBAGENT_TOOL_TYPES: tuple[str, ...] = (*(h.tool_type for h in HARNESSES), "generic_mcp")

# BE-6165d: modes INTRINSICALLY able to open OS-level terminals. Only
# ``multi_terminal`` -- ``subagent`` terminal ability is a runtime session/harness
# property, not a mode property (BE-9035c generalizes the old generic_mcp opt-out to
# the whole subagent mode), so ``subagent`` is the ONE valid mode absent here.
TERMINAL_CAPABLE_MODES: frozenset[str] = frozenset(m.execution_mode for m in MODES if m.can_spawn_terminals)

# execution_mode -> protocol tool (tool_type / harness token). Callers use
# tool_for_mode() (or .get(mode, DEFAULT_TOOL_TYPE)) so an unknown mode falls back to
# the platform-neutral branch. multi_terminal -> multi_terminal; subagent -> generic
# (the floor -- effective_harness() upgrades it when a concrete harness is detected);
# each legacy token -> the harness it historically implied (the declared hint).
EXECUTION_MODE_TO_TOOL: dict[str, str] = {
    MODE_MULTI_TERMINAL: MODE_MULTI_TERMINAL,
    MODE_SUBAGENT: GENERIC_HARNESS,
    **LEGACY_MODE_TO_HARNESS,
}

# Coding-tool identifier (agent_templates.cli_tool vocabulary) -> launcher binary.
# Sourced from the HARNESSES table.
CLI_BINARIES: dict[str, str] = {h.cli_tool: h.cli_binary for h in HARNESSES}


# ---------------------------------------------------------------------------
# Harness capability PRESETS (INF-8003e) -- shell-less, non-CLI session classes the
# capability vector (INF-8003d) selects. DELIBERATELY a separate axis from MODES and
# HARNESSES: a preset = the harness ENVIRONMENT (web sandbox / desktop app / chat),
# orthogonal to topology and CLI. Presets keep their own ``Platform`` dataclass.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Platform:
    """Identity of one harness PRESET (INF-8003e). Presets only.

    Retained verbatim from the pre-collapse registry for the web_sandbox /
    desktop_app / chat rows; the execution-mode CLI rows it used to also hold are
    now :data:`MODES` + :data:`HARNESSES`.
    """

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
        """Does a session on this preset have a usable shell for code work? (BE-8003f).

        Derived strictly from ``workspace_model``: True unless the preset is a pure
        chat surface (``workspace_model == "none"``). This is the SINGLE signal the
        (f) worker-prose render branches its shell asides on, so the check can never
        drift from ``workspace_model``.
        """
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
        # A web coding agent (Claude Code web / Codex web) returns subagent results
        # inline -> render as a subagent orchestrator, NEVER the multi_terminal
        # human-driven identity.
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
        # Claude Desktop / ChatGPT desktop / Antigravity -- writes into the shared
        # local checkout, but cannot open its own OS-level terminals.
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
        # claude.ai / ChatGPT chat -- no filesystem workspace, no terminals.
        is_subagent=True,
        can_spawn_terminals=False,
        workspace_model=WORKSPACE_NONE,
    ),
)

# Preset lookup + derived sets. Consumed by select_effective_preset() and the (f)
# rendering layer; kept parallel to (never merged into) the mode/harness maps.
_BY_PRESET: dict[str, Platform] = {p.execution_mode: p for p in PLATFORM_PRESETS}
PRESET_NAMES: tuple[str, ...] = tuple(p.execution_mode for p in PLATFORM_PRESETS)
VALID_PRESETS: frozenset[str] = frozenset(PRESET_NAMES)

# Presets that cannot open OS terminals (the shell-less harness classes). All three
# presets qualify today; derived so the set can never drift from the rows.
NON_TERMINAL_PRESETS: frozenset[str] = frozenset(
    p.execution_mode for p in PLATFORM_PRESETS if not p.can_spawn_terminals
)

# preset name -> workspace_model, the delivery axis (f) branches instruction text on.
PRESET_WORKSPACE_MODELS: dict[str, str] = {p.execution_mode: p.workspace_model for p in PLATFORM_PRESETS}


# ---------------------------------------------------------------------------
# Export/download platform vocabulary (BE-6117) -- single source for the
# duplicated frozensets/regex/dicts formerly copied across the export sites. The
# export axis is UNTOUCHED by the mode collapse (DESIGN §6); it is now sourced from
# the HARNESSES rows (each export-target harness carries its export_platform token).
# ---------------------------------------------------------------------------

# harness tool_type -> export_platform, for the harnesses that ARE export targets.
_EXPORT_BY_HARNESS: dict[str, str] = {h.tool_type: h.export_platform for h in HARNESSES if h.export_platform}

# All valid export platforms in canonical display order. Sourced from the harness
# rows (claude_code / gemini_cli / codex_cli / antigravity_cli) plus the ``generic``
# pseudo-platform. Byte-compatible with the pre-collapse literals (the downloads
# Query regex + slash _VALID_PLATFORMS) -- gemini before codex, note.
EXPORT_PLATFORMS: tuple[str, ...] = (
    _EXPORT_BY_HARNESS[HARNESS_CLAUDE_CODE],
    _EXPORT_BY_HARNESS[HARNESS_GEMINI],
    _EXPORT_BY_HARNESS[HARNESS_CODEX],
    _EXPORT_BY_HARNESS[HARNESS_ANTIGRAVITY],
    EXPORT_GENERIC,
)

# The valid set an export ``platform`` parameter may hold.
VALID_EXPORT_PLATFORMS: frozenset[str] = frozenset(EXPORT_PLATFORMS)

# Export platforms whose slash commands install as ``$``-prefixed SKILLS (nested
# ``<name>/SKILL.md``) rather than ``/``-commands: Codex and Antigravity.
SKILL_SLASH_PLATFORMS: frozenset[str] = frozenset({EXPORT_CODEX_CLI, EXPORT_ANTIGRAVITY_CLI})

# tool_type values whose installed giljo command uses the ``$giljo`` (skill) invocation
# instead of ``/giljo``. Derived from SKILL_SLASH_PLATFORMS so the runtime token can
# NEVER drift from the install form (a hardcoded ``tool == "codex"`` check previously
# dropped Antigravity, which also installs ``$giljo``).
SKILL_SLASH_TOOL_TYPES: frozenset[str] = frozenset(
    h.tool_type for h in HARNESSES if h.export_platform in SKILL_SLASH_PLATFORMS
)


def giljo_invocation(tool_type: str | None) -> str:
    """``$giljo`` for skill-install platforms (Codex, Antigravity); ``/giljo`` otherwise."""
    return "$giljo" if (tool_type or "") in SKILL_SLASH_TOOL_TYPES else "/giljo"


def task_list_phrase(tool_type: str | None) -> str:
    """ "TodoWrite list" for claude-code, else "task list" (BE-9260, guard-exempt module)."""
    return "TodoWrite list" if (tool_type or "") == HARNESS_CLAUDE_CODE else "task list"


def export_platform_pattern() -> str:
    """Anchored regex of the valid export platforms (FastAPI Query ``pattern``)."""
    return "^(" + "|".join(EXPORT_PLATFORMS) + ")$"


# ---------------------------------------------------------------------------
# Export behavior facet (BE-6116): agent-template install paths per EXPORT
# platform. Keyed by the export/download vocabulary (note ``claude_code`` drops
# the ``_cli`` suffix and ``generic`` is the pseudo-platform) -- a non-branching
# sibling table consumed by AgentTemplateAssembler. The dict shape varies per
# platform (the installer surfaces different keys), so this is data, not identity.
# ---------------------------------------------------------------------------
INSTALL_PATHS: dict[str, dict[str, str]] = {
    "claude_code": {
        "project": ".claude/agents/",
        "user": "~/.claude/agents/",
    },
    "gemini_cli": {
        "project": ".gemini/agents/",
        "user": "~/.gemini/agents/",
    },
    "antigravity_cli": {
        "plugin_root": "~/.gemini/config/plugins/giljoai/",
        "install_command": "agy plugin install ~/.gemini/config/plugins/giljoai/",
    },
    "codex_cli": {
        "agent_files": "~/.codex/agents/",
        "global_config_optional": "~/.codex/config.toml",
    },
    "generic": {
        "project": "agents/",
        "user": "~/agents/",
    },
}


def get_mode(execution_mode: str | None) -> Mode | None:
    """Return the :class:`Mode` for a CANONICAL ``execution_mode``, or ``None``.

    Resolves only the 2 canonical modes (``multi_terminal`` / ``subagent``). A legacy
    token, an unknown token, or ``None`` -> ``None`` (normalize it first with
    :func:`normalize_execution_mode` if you need the canonical mode of a legacy row).
    """
    return _BY_MODE.get(execution_mode or "")


# BE-9035c compatibility shim: the historical name. Resolves a canonical MODE row.
# Callers that used to read per-CLI facts (spawn_syntax / template_locations) off
# ``get_platform(execution_mode)`` now resolve the harness via :func:`get_harness`
# (the collapse moved that knowledge to the HARNESSES table).
get_platform = get_mode


# Universal harness-neutral subagent spawn prose — single source for the ``generic``
# floor (no detected harness / legacy ``generic_mcp``); all renders read THIS (BE-9099).
GENERIC_SUBAGENT_SPAWN_SYNTAX = (
    "Use your harness's own subagent-spawn mechanism (a Task tool, an agent spawner, an "
    "@-mention, or a delegate command) to invoke the agent named by spawn_job — agent_name "
    "is used as-is. If ANY spawn mechanism exists in your harness, using it is MANDATORY. "
    "Only if your harness has NO spawn mechanism at all: self-adopt the role and do the "
    "work yourself in this session."
)


def get_harness(tool_type: str | None) -> Harness | None:
    """Return the :class:`Harness` for a harness ``tool_type`` token, or ``None``.

    ``claude-code`` / ``codex`` / ``gemini`` / ``antigravity`` / ``opencode`` -> its
    row; ``generic`` / an unknown token / ``None`` -> ``None`` (the caller uses the
    universal generic subagent prose :data:`GENERIC_SUBAGENT_SPAWN_SYNTAX`). Never
    resolves a mode or a preset token.
    """
    return _BY_HARNESS.get(tool_type or "")


def get_preset(preset_name: str | None) -> Platform | None:
    """Return the harness :class:`Platform` PRESET for ``preset_name`` (INF-8003e).

    ``web_sandbox`` / ``desktop_app`` / ``chat`` -> its preset row; anything else
    (an unknown name, an execution_mode, a harness token, empty/None) -> ``None``.
    Kept separate from :func:`get_mode`/:func:`get_harness` so the axes never
    cross-resolve.
    """
    return _BY_PRESET.get(preset_name or "")


def select_effective_preset(
    declared: str | None = None,
    capabilities: dict[str, object] | None = None,
) -> Platform | None:
    """Resolve the effective session harness preset -- DECLARED beats DETECTED (INF-8003e).

    Implements DoD item 3's capability-trust ordering:

      1. ``declared`` -- an explicitly declared preset name (highest trust: the
         session/project stated its harness). If it names a known preset, it wins
         outright, even over a conflicting detected signal.
      2. detected -- read from the session capability vector produced by
         ``get_session_capabilities`` (INF-8003d) + the captured ``client_info``.
         The caller passes that vector as ``capabilities``; a preset hint under the
         ``"preset"`` key is honored. This helper does NOT re-probe / re-implement
         detection -- it consumes (d)'s output shape.
      3. Neither resolves -> ``None``: no preset applies, so the caller uses the
         normal terminal-capable path (the preset-axis analogue of the HO1020
         fail-safe -- an unknown/absent signal never crashes and never forces a
         preset).

    NOTE the PRESET axis keeps declared-beats-detected; the mode-collapse precedence
    FLIP (detected-beats-declared) is HARNESS-only (:func:`effective_harness`). Both
    tiers validate against :data:`VALID_PRESETS`, so a garbage name in either slot
    degrades to the next tier rather than raising.
    """
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
    """Authoritative "can this session spawn OS terminals?" signal (INF-8003e, DoD item 5).

    The capability-vector replacement for the legacy ``$DISPLAY`` / ``$WAYLAND_DISPLAY``
    probe, which is invisible to exactly the shell-less web/desktop/chat harnesses
    that need the fallback. This is the clearly-named registry-layer SEAM the (f)
    rendering layer reads from instead of keying instruction prose on ``$DISPLAY``.

    Contract: honor an explicit ``can_spawn_terminals`` boolean in the session
    capability vector when present; otherwise default ``True`` (terminal-capable) to
    match today's all-CLI-workstation behavior -- fail-SAFE toward not wrongly
    blocking a real CLI.
    """
    if capabilities:
        signal = capabilities.get("can_spawn_terminals")
        if isinstance(signal, bool):
            return signal
    return True


def tool_for_mode(execution_mode: str | None) -> str:
    """Map an execution mode to its protocol tool, HO1020 fail-safe to multi_terminal.

    ``multi_terminal`` -> ``multi_terminal``; ``subagent`` -> ``generic`` (the floor;
    :func:`effective_harness` upgrades it when a concrete harness is detected); a
    legacy CLI token -> the harness it historically implied (the declared hint). An
    unknown/empty mode -> :data:`DEFAULT_TOOL_TYPE` so the render layer degrades to
    the platform-neutral protocol instead of the Claude Code branch.
    """
    return EXECUTION_MODE_TO_TOOL.get(execution_mode or "", DEFAULT_TOOL_TYPE)


def is_subagent_mode(execution_mode: str | None) -> bool:
    """True when ``execution_mode`` renders as a subagent orchestrator (not multi_terminal).

    True for ``subagent`` and every legacy CLI token; False for ``multi_terminal`` /
    empty / ``None``. Equivalent to ``normalize_execution_mode(mode) == "subagent"``.
    """
    return execution_mode in SUBAGENT_EXECUTION_MODES


def is_subagent_render(execution_mode_or_tool: str | None) -> bool:
    """Canonical "render for a CLI subagent orchestrator" signal -- the ONE source of
    truth that replaces the scattered ``execution_mode != MULTI_TERMINAL`` string
    compares in the orchestrator protocol body + FORBIDDEN banner (BE-6209f).

    Accepts EITHER axis -- an execution_mode (canonical ``subagent`` OR a legacy
    ``claude_code_cli``) OR a tool_type/harness token (``claude-code``);
    ``multi_terminal`` is the single shared token that renders False.

    Resolution:
      1. ``multi_terminal`` / empty / ``None`` -> ``False`` -- the human-driven
         multi-terminal identity, the only render carrying multi-terminal-only prose.
      2. A canonical/legacy subagent mode, a registered harness tool_type, or a
         harness PRESET token -> ``True`` (the authoritative registry signal).
      3. An unknown, non-empty token (a future harness not yet registered) -> ``True``:
         it is a subagent context, so multi-terminal-only prose is stripped and it
         falls back to subagent-generic phrasing -- never a multi-terminal leak.
    """
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
    """Map a project/run ``execution_mode`` to the ``stage_project`` short ``mode`` token.

    BE-6177/BE-9035c: ``stage_project(mode=...)`` accepts SHORT tokens
    (``multi_terminal`` / ``subagent`` / a per-CLI ``claude`` / ``codex`` / ``gemini`` /
    ``antigravity``). The conductor's CH_CHAIN_STAGING chapter holds the run's
    ``execution_mode`` and must emit a short token. ``multi_terminal`` -> itself;
    a legacy CLI token -> its harness ``cli_tool`` (``claude_code_cli`` -> ``claude``);
    ``subagent`` / anything else subagent-shaped -> ``subagent`` (the harness is
    detection-resolved at render, no CLI to name). Fail-safe: unknown/empty ->
    ``multi_terminal``.
    """
    if execution_mode == MODE_MULTI_TERMINAL:
        return MODE_MULTI_TERMINAL
    legacy_harness = LEGACY_MODE_TO_HARNESS.get(execution_mode or "")
    if legacy_harness is not None:
        harness = _BY_HARNESS.get(legacy_harness)
        if harness is not None:
            return harness.cli_tool
        return MODE_SUBAGENT  # legacy generic_mcp -> no CLI -> subagent
    if execution_mode == MODE_SUBAGENT:
        return MODE_SUBAGENT
    return MODE_MULTI_TERMINAL


def execution_mode_pattern() -> str:
    """Anchored regex of the ACCEPTED execution_mode values (FastAPI Query ``pattern``).

    Includes the 2 canonical modes AND the 5 legacy aliases so a boundary that
    validates a stored/legacy execution_mode (e.g. a prompt endpoint reading an
    existing project's mode) tolerates legacy rows. Canonical modes first, then the
    legacy tokens in registry order.
    """
    ordered = list(EXECUTION_MODES) + list(LEGACY_MODE_TO_HARNESS)
    return "^(" + "|".join(ordered) + ")$"


def tool_type_pattern() -> str:
    """Anchored regex of the accepted harness tool_type values (FastAPI Query ``pattern``).

    The 5 harness tool_types (claude-code / codex / gemini / antigravity / opencode)
    plus the legacy ``generic_mcp`` token (tolerance -- a legacy caller passing
    ``tool=generic_mcp`` still validates). A superset of the pre-collapse set, so no
    boundary tightens. Derived from :data:`SUBAGENT_TOOL_TYPES` (BE-9035a) so the regex
    and the request-schema Literal can never drift.
    """
    return "^(" + "|".join(SUBAGENT_TOOL_TYPES) + ")$"


def mode_label_list() -> str:
    """``' / '``-joined display labels for the mode-not-selected dashboard guidance."""
    return " / ".join(m.display_label for m in MODES)


def mode_csv() -> str:
    """``', '``-joined canonical execution_mode values for validation error messages."""
    return ", ".join(EXECUTION_MODES)


# Two-axis harness precedence (BE-9035b/c): detection layer lives in
# :mod:`giljo_mcp.harness_resolver`; ``effective_harness`` stays HERE (bridges the
# mode + harness axes via tool_for_mode); HARNESS_CLI_TOOL_TYPES derives from HARNESSES.

# The concrete CLI harnesses whose token DOUBLES as a render ``tool_type`` and whose
# per-harness prose overrides a declared render key. ``generic`` is absent (it is the
# floor); ``opencode`` is present -- a first-class detectable harness with its own
# HARNESSES row, though its per-render prose falls back to the universal subagent block
# where no opencode-specific block exists.
HARNESS_CLI_TOOL_TYPES: frozenset[str] = frozenset(h.tool_type for h in HARNESSES)


def effective_harness(declared_mode: str | None, session: object | None = None) -> str:
    """Resolve the harness token that drives per-harness RENDERING (BE-9035b).

    The ONE place the mode-collapse precedence rule lives -- never inline it per site:

      1. DETECTED -- a harness resolved at runtime from the session's clientInfo and
         stamped on the session (``session_data['resolved_harness']``). Wins whenever
         it is a CONCRETE (non-generic) harness. This is the DESIGN precedence flip:
         for harness-specific rendering, DETECTED beats DECLARED.
      2. DECLARED-CLI-HINT -- the declared ``execution_mode``'s harness
         (``tool_for_mode`` -> tool_type, honored only for the concrete CLI harnesses).
         Used only when detection is absent or resolves to generic. A collapsed
         ``subagent`` mode has no CLI hint (-> generic); a stored legacy ``*_cli``
         token still supplies its historical harness here.
      3. ``generic`` -- no session and no CLI hint -> the BE-9013/9033 fail-safe floor.

    ``session`` is read tolerantly (see :func:`_detected_harness_from_session`): an
    ``MCPSession``-like row, a raw session_data dict, a capability vector
    (``{"harness": ...}``), or ``None``. ``None`` -> detection absent -> the declared
    path -> today's exact bytes (the byte-safety floor the multi_terminal golden
    proves). For the PRESET axis the existing declared-beats-detected rule still
    governs (:func:`select_effective_preset`); this precedence flip is HARNESS-only.
    """
    detected = _detected_harness_from_session(session)
    if detected and detected != GENERIC_HARNESS:
        return detected
    if declared_mode:
        hint = tool_for_mode(declared_mode)  # tool_type; HO1020 fail-safe -> multi_terminal
        if hint in HARNESS_CLI_TOOL_TYPES:
            return hint
    return GENERIC_HARNESS
