# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Orchestrator 3-phase coordination lifecycle protocol generation."""

from __future__ import annotations

import logging

from giljo_mcp.platform_registry import Platform, is_subagent_render
from giljo_mcp.services.protocol_sections.orchestrator_body import (
    _CONDUCTOR_CLOSEOUT_NOTE,  # noqa: F401 — re-exported for back-compat (test imports)
    _CONDUCTOR_COORDINATION_NOTE,  # noqa: F401 — re-exported for back-compat (test imports)
    _ORCHESTRATOR_CONSTRAINTS_ANCHOR,  # noqa: F401 — re-exported for back-compat (test imports)
    _PHASE3_CLOSEOUT_START,  # noqa: F401 — re-exported for back-compat (test imports)
    _PROGRESS_REPORTING_ANCHOR,  # noqa: F401 — re-exported for back-compat (test imports)
    _WORKER_SPAWN_BLOCK_START,  # noqa: F401 — re-exported for back-compat (test imports)
    _build_orchestrator_protocol_body,
    render_capability_ladder,
)
from giljo_mcp.services.protocol_sections.thread_refs import apply_thread_reference


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-platform behavior prose (BE-6116). Dispatched by dict lookup keyed off the
# registry's canonical tool_type, HO1020 fail-safe to the generic entry -- NOT an
# inline if/elif on bare literals. The prose stays here in the renderer; only the
# dispatch is registry-keyed.
# ---------------------------------------------------------------------------

# tool_type -> (forbidden_lines, tool_label) for the multi_terminal FORBIDDEN
# banner (BE-5103). Unknown tools fall back to the generic three-CLI listing.
_FORBIDDEN_BY_TOOL: dict[str, tuple[str, str]] = {
    "claude-code": (
        '  ✗ Task(subagent_type="implementer-frontend", ...)\n'
        '  ✗ Agent(subagent_type="...", ...)\n'
        "  ✗ Any in-process spawn of a name from your Claude Code subagent_type\n"
        "    menu. That menu is irrelevant in this mode — ignore it.",
        "Claude Code",
    ),
    "codex": (
        '  ✗ spawn_agent(name="...", ...)   ← Codex in-process subagent\n'
        "  ✗ Any in-process spawn of an agent. spawn_agent is forbidden here.",
        "Codex",
    ),
    "gemini": (
        "  ✗ @agent-name ...   ← Gemini @-syntax invocation\n  ✗ Any @-syntax agent invocation. Use spawn_job only.",
        "Gemini",
    ),
    "antigravity": (
        "  ✗ @agent-name ...   ← Antigravity @-syntax invocation\n  ✗ Any @-syntax agent invocation. Use spawn_job only.",
        "Antigravity",
    ),
}

_FORBIDDEN_GENERIC: tuple[str, str] = (
    '  ✗ Task(subagent_type="...")  ← Claude Code\n'
    '  ✗ spawn_agent(name="...")    ← Codex\n'
    "  ✗ @agent-name ...            ← Gemini\n"
    "  ✗ Any in-process subagent spawn — user opens each agent's new session.",
    "Multi-Terminal (generic)",
)

# BE-6205 follow-up: the project-less chain CONDUCTOR is pinned to multi_terminal so it
# never steers itself with Task(), but it does NOT match the stock banner's "the USER
# opens terminals" model — the conductor RUNS the fresh-terminal launch command itself
# (CH_CHAIN_DRIVE STEP A), autonomously. Its FORBIDDEN block keeps the load-bearing
# no-Task()-for-sub-orchestrators forbid but drops the "user opens terminals" tail.
_CONDUCTOR_FORBIDDEN_LINES = (
    '  ✗ Task(subagent_type="...")  ← Claude Code\n'
    '  ✗ spawn_agent(name="...")    ← Codex\n'
    "  ✗ @agent-name ...            ← Gemini\n"
    "  ✗ Any in-process subagent spawn. Do NOT use Task() (or any of the\n"
    "    above) to spawn your sub-orchestrators — run the fresh-terminal\n"
    "    launch command instead."
)

# tool_type -> constellation wake-and-check block.
#
# BE-6211e: the OWN-WORKER wait pattern. In a CLI subagent mode the orchestrator's
# spawn call (Task() / spawn_agent() / @agent) BLOCKS and hands the worker's result
# straight back inline — there is NO waiting gap to sleep-poll across for a worker the
# orchestrator launched itself. So these blocks tell it to call get_agent_result the
# instant the spawn returns and NEVER sleep to "wait" for its own worker (the old
# sleep-and-check-on-your-own-agents prose was wrong for inline-returning CLIs). A
# cross-terminal get_thread_history note stays in EVERY block — peer agents / other
# terminals still reach the orchestrator by message, which is a real wait it must drain
# on each wake. The multi_terminal/generic block (_WAKE_GENERIC) is unchanged: that
# render is human-mediated across separate terminals and stays byte-identical.
_WAKE_CODEX = """**CONSTELLATION: CODEX CLI**
Your subagents are Codex spawn_agent() processes you spawn IN-PROCESS — they run and
return their result to you inline.

**Your OWN workers return INLINE — never sleep-poll them:**
  `spawn_agent(...)` BLOCKS until the subagent finishes and hands its result straight
  back to you. The instant it returns:
  → `get_agent_result(job_id="...")` — read the worker's recorded
    result and verify its deliverable.
  There is NO waiting gap to poll across for a spawn_agent() YOU launched — do NOT
  `sleep` to "wait" for your own worker.

**Cross-terminal peers still reach you by message — drain on every wake:**
  → `get_thread_history(thread_id=<your coordination thread>, as_participant="{executor_id}", unread_only=true, mark_read=true)` — messages from peer
    agents / other terminals (blockers, hand-offs, the user)
  → `get_workflow_status(project_id="...")` — live agent statuses

**User-triggered wake:** The user may also tell you to check on things.
  Regardless of trigger source, always run the full coordination loop."""

_WAKE_CLAUDE = """**CONSTELLATION: CLAUDE CODE CLI**
Your subagents are Claude Code Task() processes you spawn IN-PROCESS — they run and
return their result to you inline.

**Your OWN workers return INLINE — never sleep-poll them:**
  `Task(subagent_type="...")` BLOCKS until the subagent finishes and hands its result
  straight back to you. The instant it returns:
  → `get_agent_result(job_id="...")` — read the worker's recorded
    result and verify its deliverable.
  There is NO waiting gap to poll across for a Task() YOU launched — do NOT `sleep`
  to "wait" for your own worker.

**Cross-terminal peers still reach you by message — drain on every wake:**
  → `get_thread_history(thread_id=<your coordination thread>, as_participant="{executor_id}", unread_only=true, mark_read=true)` — messages from peer
    agents / other terminals (blockers, hand-offs, the user)
  → `get_workflow_status(project_id="...")` — live agent statuses

**User-triggered wake:** The user may also tell you to check on things.
  Regardless of trigger source, always run the full coordination loop."""

_WAKE_GEMINI = """**CONSTELLATION: GEMINI CLI**
Your subagents are Gemini @agent processes you spawn IN-PROCESS — they run and return
their result to you inline.

**Your OWN workers return INLINE — never sleep-poll them:**
  `@agent-name ...` BLOCKS until the subagent finishes and hands its result straight
  back to you. The instant it returns:
  → `get_agent_result(job_id="...")` — read the worker's recorded
    result and verify its deliverable.
  There is NO waiting gap to poll across for an @agent call YOU launched — do NOT
  `sleep` to "wait" for your own worker.

**Cross-terminal peers still reach you by message — drain on every wake:**
  → `get_thread_history(thread_id=<your coordination thread>, as_participant="{executor_id}", unread_only=true, mark_read=true)` — messages from peer
    agents / other terminals (blockers, hand-offs, the user)
  → `get_workflow_status(project_id="...")` — live agent statuses

**User-triggered wake:** The user may also tell you to check on things.
  Regardless of trigger source, always run the full coordination loop."""

_WAKE_ANTIGRAVITY = """**CONSTELLATION: ANTIGRAVITY CLI**
Your subagents are Antigravity @agent processes you spawn IN-PROCESS — they run and
return their result to you inline.

**Your OWN workers return INLINE — never sleep-poll them:**
  `@agent-name ...` BLOCKS until the subagent finishes and hands its result straight
  back to you. The instant it returns:
  → `get_agent_result(job_id="...")` — read the worker's recorded
    result and verify its deliverable.
  There is NO waiting gap to poll across for an @agent call YOU launched — do NOT
  `sleep` to "wait" for your own worker.

**Cross-terminal peers still reach you by message — drain on every wake:**
  → `get_thread_history(thread_id=<your coordination thread>, as_participant="{executor_id}", unread_only=true, mark_read=true)` — messages from peer
    agents / other terminals (blockers, hand-offs, the user)
  → `get_workflow_status(project_id="...")` — live agent statuses

**User-triggered wake:** The user may also tell you to check on things.
  Regardless of trigger source, always run the full coordination loop."""

# BE-6211e subagent fail-safe: an unknown future CLI. Same inline-return contract in
# tool-neutral wording — NEVER the human-mediated multi_terminal block (HO1020
# fail-safe: an unrecognized subagent CLI must not be handed multi-terminal-only prose).
_WAKE_SUBAGENT_GENERIC = """**CONSTELLATION: CLI SUBAGENT**
Your subagents run IN-PROCESS via your CLI's own subagent syntax — they run and return
their result to you inline.

**Your OWN workers return INLINE — never sleep-poll them:**
  Your subagent spawn call BLOCKS until the subagent finishes and hands its result
  straight back to you. The instant it returns:
  → `get_agent_result(job_id="...")` — read the worker's recorded
    result and verify its deliverable.
  There is NO waiting gap to poll across for a subagent YOU launched — do NOT `sleep`
  to "wait" for your own worker.

**Cross-terminal peers still reach you by message — drain on every wake:**
  → `get_thread_history(thread_id=<your coordination thread>, as_participant="{executor_id}", unread_only=true, mark_read=true)` — messages from peer
    agents / other terminals (blockers, hand-offs, the user)
  → `get_workflow_status(project_id="...")` — live agent statuses

**User-triggered wake:** The user may also tell you to check on things.
  Regardless of trigger source, always run the full coordination loop."""

# multi_terminal or generic (HO1020 fail-safe target).
_WAKE_GENERIC = """**CONSTELLATION: MULTI-TERMINAL**
Your subagents run in separate sessions. The user mediates between sessions.

**How you get woken up:**
  - User switches to your session and tells you something happened
  - User says "check messages" or "check status"
  - User reports an agent is blocked or finished

**On every wake-up**, regardless of what the user said, run the active coordination
loop below. The user's message is a trigger — your TODO list is your authority."""

_WAKE_BY_TOOL: dict[str, str] = {
    "codex": _WAKE_CODEX,
    "claude-code": _WAKE_CLAUDE,
    "gemini": _WAKE_GEMINI,
    "antigravity": _WAKE_ANTIGRAVITY,
}


def _build_conductor_forbidden_banner(tool_label: str) -> str:
    """
    Build the CONDUCTOR-scoped FORBIDDEN-spawn banner (BE-6205 follow-up).

    The project-less chain conductor is pinned to multi_terminal so it never steers
    itself with Task(), but the stock banner's "the USER opens terminals / you do NOT
    execute your specialists yourself" prose is FALSE for it: the conductor RUNS the
    fresh-terminal launch command ITSELF (CH_CHAIN_DRIVE STEP A), autonomously. This
    variant keeps the load-bearing no-Task()-for-sub-orchestrators forbid but swaps the
    user-mediated prose for conductor-autonomy wording, so a cold conductor self-spawns
    instead of stalling on the user.
    """
    return f"""═══════════════════════════════════════════════════════════════════════
SUB-ORCH SPAWN: FRESH TERMINAL   |   YOUR TOOL: {tool_label}   |   ROLE: CHAIN CONDUCTOR
═══════════════════════════════════════════════════════════════════════

As the CONDUCTOR you spawn each sub-orchestrator YOURSELF by
RUNNING the fresh-terminal launch command (Bash/PowerShell tool)
given in CH_CHAIN_DRIVE STEP A — autonomously, NEVER waiting for the
user to open a terminal.

This header is NOT an execution_mode: the run mode (CH_CAPABILITY) governs ONLY
how each sub-orch spawns its WORKERS, never how you spawn sub-orchs.

FORBIDDEN for spawning your sub-orchestrators (zero exceptions):
{_CONDUCTOR_FORBIDDEN_LINES}

CORRECT:
  ✓ Run the server-rendered launch command YOURSELF with the Bash /
    PowerShell tool to open each sub-orchestrator in its own fresh
    terminal — see CH_CHAIN_DRIVE STEP A.
  → Then drive the chain (poll → advance) via the sleep-and-check pattern.
═══════════════════════════════════════════════════════════════════════

"""


def _build_forbidden_banner(execution_mode: str, tool: str, is_chain_conductor: bool = False) -> str:
    """
    Build the tool-aware FORBIDDEN-spawn banner for multi_terminal orchestrators.

    BE-5103: Multi-terminal orchestrators must NEVER spawn specialists with their
    CLI's in-process subagent syntax (Task() / spawn_agent() / @-syntax). They
    must call spawn_job (bare) and let the user open a terminal.

    The banner is gated on execution_mode == "multi_terminal". For CLI subagent
    modes (claude-code / codex / gemini) the banner is suppressed — those modes
    legitimately use in-process subagent spawning.

    The `tool` selector picks the literal forbidden-call line:
      - claude-code  -> Task(subagent_type=...) / Agent(subagent_type=...)
      - codex        -> spawn_agent(name=...)
      - gemini       -> @agent-name ... (@-syntax)
      - multi_terminal (generic fallback) -> list all three

    BE-6205 follow-up: when `is_chain_conductor` is True (the project-less chain
    conductor), render the conductor-autonomy variant instead of the stock
    user-mediated banner — the conductor self-spawns each sub-orch in a fresh terminal
    and must not stall waiting for the user. Only the project-less conductor sets this;
    a genuine multi_terminal sub-orch / solo orchestrator keeps the stock banner.

    Other execution_mode values return "" (no banner).

    BE-6209f: the multi_terminal gate is the canonical ``is_subagent_render`` signal
    (registry ``Platform.is_subagent``), not a bare ``!= MULTI_TERMINAL`` string compare —
    one source of truth shared with the body predicate below. Behavior is unchanged: a
    subagent OR unknown mode suppresses the banner; only multi_terminal renders it.
    """
    if is_subagent_render(execution_mode):
        return ""

    # BE-6116: dict dispatch keyed off the registry's canonical tool_type, fail-safe
    # to the generic three-CLI listing. Replaces the former if/elif-on-literal chain.
    forbidden_lines, tool_label = _FORBIDDEN_BY_TOOL.get(tool, _FORBIDDEN_GENERIC)

    if is_chain_conductor:
        return _build_conductor_forbidden_banner(tool_label)

    return f"""═══════════════════════════════════════════════════════════════════════
EXECUTION_MODE: multi_terminal   |   YOUR TOOL: {tool_label}
═══════════════════════════════════════════════════════════════════════

You create job ORDERS. The USER opens each agent's new session. You do NOT execute
your specialists yourself.

FORBIDDEN in this mode (zero exceptions):
{forbidden_lines}

CORRECT:
  ✓ spawn_job(
        agent_name="implementer-frontend",
        agent_display_name="ui-implementer",
        mission="...", project_id="...")
  → returns job_id. User opens a new session and starts the agent
    from the dashboard. You wait via the sleep-and-check pattern.
═══════════════════════════════════════════════════════════════════════

"""


def _build_wake_pattern(
    execution_mode: str,
    executor_id: str,
    tenant_key: str,
) -> str:
    """
    Build the constellation-specific wake-and-check pattern block.

    The returned string is already interpolated with executor_id and tenant_key.
    """
    # BE-6211e: branch the OWN-WORKER wait pattern on the canonical is_subagent_render
    # signal (Platform.is_subagent — the SAME source of truth the FORBIDDEN banner and the
    # body predicate use). A CLI subagent mode gets the inline-return wake block (its spawn
    # call BLOCKS and returns the worker result inline, so it calls get_agent_result rather
    # than sleep-polls its own workers); multi_terminal keeps the byte-identical generic
    # block (human-mediated across separate terminals). The per-CLI dispatch picks the
    # tool-specific block; an unregistered subagent CLI (antigravity / unknown) fails safe
    # to the subagent-generic block, NEVER leaking the multi_terminal block.
    if is_subagent_render(execution_mode):
        raw = _WAKE_BY_TOOL.get(execution_mode, _WAKE_SUBAGENT_GENERIC)
    else:
        raw = _WAKE_GENERIC
    return raw.replace("{executor_id}", executor_id).replace("{tenant_key}", tenant_key)


def _build_preset_waiting_ladder(preset: Platform) -> str:
    """Shell-less-harness coordination/waiting ladder prepended to the orchestrator
    protocol on a preset-active render (BE-8003f, D3-S3).

    The orchestrator body below carries CLI/terminal-workstation asides — the FORBIDDEN
    banner's "the USER opens terminals" model, the multi_terminal wake block's "separate
    terminals" model, and the resting-state background-timer/sleep guidance. On a
    preset-active (shell-less) harness those mislead. Rather than surgically re-write that
    golden-locked prose in v1, this ladder is prepended so it is READ FIRST and GOVERNS:
    coordinate by re-checking state when you next act, never a background timer, never a
    terminal. Deeper per-aside gating of the banner/wake/body is deferred (see the DONE
    no-instruction-lost table)."""
    return render_capability_ladder(
        preferred=(
            f"**COORDINATING FROM A {preset.display_label.upper()} SESSION (shell-less)** — you have\n"
            "no OS terminals and no reliable background timer. Coordinate by RE-CHECKING state the\n"
            "next time you act: get_thread_history / get_my_turn, and\n"
            "get_workflow_status. Do NOT use a background `sleep`/timer wake trick and do NOT tell\n"
            "the user to open a terminal. Where the CLI/terminal asides below assume a workstation\n"
            "shell, this instruction governs over them on this harness."
        ),
        fallback=(
            "If you cannot re-check between turns on your own, ask the user to prompt you to check on\n"
            "your agents, then run the full coordination loop when they do."
        ),
        floor_user_line=(
            "Prompt me to check on the agents when you want a status update — this session has no "
            "terminals or background timers to self-wake."
        ),
        preset_display=preset.display_label,
    )


def _generate_orchestrator_protocol(
    job_id: str,
    tenant_key: str,
    executor_id: str,
    execution_mode: str = "multi_terminal",
    tool: str | None = None,
    is_chain_conductor: bool = False,
    preset: Platform | None = None,
    comm_thread_id: str | None = None,
) -> str:
    """
    Generate 3-phase orchestrator coordination protocol (Handover 0830, 0851).

    Handover 0851: Rewrote Phase 2 from passive/reactive menu to active TODO-driven
    coordination loop. Orchestrator now actively works its TODO list on every wake-up
    regardless of trigger source. Added constellation-specific coordination patterns.

    BE-5103: In multi_terminal mode, prepend a tool-aware FORBIDDEN banner at the very
    top of the protocol so the orchestrator cannot miss it. The banner forbids the CLI's
    in-process subagent syntax (Task/Agent/spawn_agent/@-syntax) and points at spawn_job
    as the only correct path. Suppressed for CLI subagent modes (claude-code/codex/gemini)
    where in-process spawn is the legitimate mechanism. `tool` defaults to `execution_mode`
    when omitted, matching the historical conflation in mission_service.

    TSK-9459: `comm_thread_id` is the project's bound Hub thread, resolved by
    ``mission_service.get_agent_mission`` on the same session. It replaces the
    ``<your coordination thread>`` placeholder the body renders, which the
    orchestrator had no way to resolve — see ``thread_refs`` for why the
    substitution happens here rather than as a body parameter. None (a project-less
    conductor, or an unresolvable thread) keeps the placeholder byte-identical.

    BE-6205 follow-up: `is_chain_conductor` selects the conductor-autonomy banner variant
    (the project-less chain conductor self-spawns each sub-orch in a fresh terminal and
    must not stall on the user). Default False keeps the stock banner for every other mode.

    Unlike the worker 5-phase lifecycle, the orchestrator coordinates rather than implements.
    It reads pre-planned TODOs from staging and updates statuses via todo_items (full list).
    """
    effective_tool = tool if tool is not None else execution_mode
    forbidden_banner = _build_forbidden_banner(execution_mode, effective_tool, is_chain_conductor)
    wake_pattern = _build_wake_pattern(execution_mode, executor_id, tenant_key)
    body = _build_orchestrator_protocol_body(
        job_id,
        tenant_key,
        executor_id,
        wake_pattern,
        execution_mode,
        effective_tool,
        is_chain_conductor=is_chain_conductor,
    )
    body = apply_thread_reference(body, comm_thread_id)
    # BE-8003f (D3-S3): preset is None -> today's exact bytes (D1). On a preset-active
    # (shell-less) render, prepend the coordination/waiting ladder so it governs over the
    # CLI/terminal asides in the banner + body below.
    if preset is None:
        return forbidden_banner + body
    return _build_preset_waiting_ladder(preset) + "\n\n" + forbidden_banner + body
