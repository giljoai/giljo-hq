# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
}

_FORBIDDEN_GENERIC: tuple[str, str] = (
    '  ✗ Task(subagent_type="...")  ← Claude Code\n'
    '  ✗ spawn_agent(name="...")    ← Codex\n'
    "  ✗ Any in-process subagent spawn — user opens each agent's new session.",
    "Multi-Terminal (generic)",
)

_CONDUCTOR_FORBIDDEN_LINES = (
    '  ✗ Task(subagent_type="...")  ← Claude Code\n'
    '  ✗ spawn_agent(name="...")    ← Codex\n'
    "  ✗ Any in-process subagent spawn. Do NOT use Task() (or any of the\n"
    "    above) to spawn your sub-orchestrators — run the fresh-terminal\n"
    "    launch command instead."
)

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
}


def _build_conductor_forbidden_banner(tool_label: str) -> str:
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
    if is_subagent_render(execution_mode):
        return ""

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
) -> str:
    if is_subagent_render(execution_mode):
        raw = _WAKE_BY_TOOL.get(execution_mode, _WAKE_SUBAGENT_GENERIC)
    else:
        raw = _WAKE_GENERIC
    return raw.replace("{executor_id}", executor_id)


def _build_preset_waiting_ladder(preset: Platform) -> str:
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
    effective_tool = tool if tool is not None else execution_mode
    forbidden_banner = _build_forbidden_banner(execution_mode, effective_tool, is_chain_conductor)
    wake_pattern = _build_wake_pattern(execution_mode, executor_id)
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
    if preset is None:
        return forbidden_banner + body
    return _build_preset_waiting_ladder(preset) + "\n\n" + forbidden_banner + body
