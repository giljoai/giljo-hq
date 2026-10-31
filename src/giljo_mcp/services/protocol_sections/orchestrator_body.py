# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
import textwrap

from giljo_mcp.platform_registry import giljo_invocation, is_subagent_render
from giljo_mcp.services.memory_entry_write_validator import CONTROLLED_TAG_VOCABULARY


def render_capability_ladder(
    preferred: str,
    fallback: str,
    floor_user_line: str,
    preset_display: str = "",
) -> str:
    header = f"[YOUR PATH — {preset_display}]" if preset_display else "[YOUR PATH]"
    return (
        f"{header}\n"
        f"{preferred}\n"
        "[IF YOU CANNOT DO THE ABOVE]\n"
        f"{fallback}\n"
        "[FLOOR] If none of the above works in your environment: post_to_thread on your "
        "coordination thread stating exactly what you cannot do, and show the user this "
        f'line verbatim: "{floor_user_line}".'
    )


_WORKER_SPAWN_BLOCK_START = "**COORDINATION ACTIONS (use as needed within the loop):**"
_PROGRESS_REPORTING_ANCHOR = "**PROGRESS REPORTING (MANDATORY after every coordination action):**"
_CONDUCTOR_COORDINATION_NOTE = (
    "**COORDINATION ACTIONS (chain conductor):**\n"
    "  → You are the project-less CHAIN CONDUCTOR. You do NOT spawn, unblock, broadcast to,\n"
    "    or spawn verification for WORKERS — every project's own sub-orchestrator owns that.\n"
    "  → Your coordination loop is the CHAIN itself: advance project-to-project per\n"
    "    CH_CHAIN_DRIVE and relay directives over the Hub thread. See the chain chapters\n"
    "    appended below — they are your only coordination actions.\n\n"
)

_PHASE3_CLOSEOUT_START = "### PHASE 3 — CLOSEOUT (all agents complete or decommissioned)"
_ORCHESTRATOR_CONSTRAINTS_ANCHOR = "## ORCHESTRATOR CONSTRAINTS"
_CONDUCTOR_CLOSEOUT_NOTE = (
    "### CHAIN FINALE (chain conductor — the solo PHASE-3 CLOSEOUT does NOT apply)\n"
    "  → You are the project-less CHAIN CONDUCTOR. You do NOT run a per-project closeout:\n"
    "    NO per-project `write_project_closeout`, NO per-project `complete_job`-as-finale —\n"
    "    every project's own sub-orchestrator closes ITS OWN project out.\n"
    "  → Your ONE-AND-ONLY finale is the chain series-summary AFTER the FINAL project\n"
    "    closes: advance project-to-project per the chain chapters below, then post the\n"
    "    chain series-summary over the Hub thread and call `complete_job` ONCE to close\n"
    "    your conductor job. The chain chapters below are your only finale. Never emit a\n"
    "    per-project closeout here.\n\n"
)


_SUBAGENT_SPAWN_BY_TOOL: dict[str, str] = {
    "claude-code": 'Task(subagent_type="general-purpose")',
    "codex": "spawn_agent(name=...)",
}
_SUBAGENT_SPAWN_GENERIC = "your CLI's in-process subagent syntax"


_CHAIN_PROTOCOL_REGION_START = "## Orchestrator Coordination Protocol (3 Phases)"
_CHAIN_PROTOCOL_REGION_END = "## ORCHESTRATOR CONSTRAINTS"
_CONDUCTOR_EMBEDDED_NOTE = (
    "## Orchestrator Coordination Protocol — REPLACED by the chain chapters below\n\n"
    "You are the project-less CHAIN CONDUCTOR. The solo 3-phase coordination protocol\n"
    "does NOT govern you — CH_CHAIN_DRIVE below is your operating\n"
    "procedure end to end: STEP A spawns each project's sub-orchestrator, STEP B parks /\n"
    "polls / advances on ready_to_advance, and the SERIES SUMMARY is your only finale.\n"
    "Still call `get_job_mission(job_id=...)` once at session start (it flips you\n"
    "waiting→working) and remember the returned `protocol_etag` for any later refetch.\n\n"
)

_SUBORCH_PHASE1_START = "### PHASE 1 — STARTUP (execute once, after get_job_mission)"
_SUBORCH_PHASE1_END = "### PHASE 2 — ACTIVE COORDINATION"
_SUBORCH_PHASE1_NOTE = (
    "### PHASE 1 — STARTUP (chain sub-orchestrator)\n\n"
    "CH_SUB_ORCHESTRATOR step 5 above is your AUTHORITATIVE implementation entry: the one\n"
    "`get_job_mission` ONCE after staging-end flips you waiting→working. NO human Implement click,\n"
    "no waiting on the user or the dashboard. Read `current_team_state` (live-queried) and your\n"
    "pre-planned coordination TODOs (do NOT drop any items), then begin PHASE 2 immediately.\n\n"
)

_SUBORCH_STAGING_IMPL_REGION_START = "### PHASE 2 — ACTIVE COORDINATION"
_SUBORCH_STAGING_IMPL_REGION_END = "## ORCHESTRATOR CONSTRAINTS"
_SUBORCH_STAGING_IMPL_NOTE = (
    "### PHASES 2-3 — IMPLEMENTATION COORDINATION + CLOSEOUT (deferred to your implementation fetch)\n\n"
    "This is a STAGING-phase fetch: the implementation coordination loop (PHASE 2), the\n"
    "resting states, and the closeout procedure (PHASE 3) are deliberately omitted to keep\n"
    "this payload small. They arrive with your implementation protocol: after complete_job\n"
    "(staging-end), call get_job_mission ONCE, without your boot protocol_etag — no gate, no\n"
    "human Implement click, do NOT wait — exactly as CH_SUB_ORCHESTRATOR step 5 instructs.\n"
    "Until then, stage per CH_SUB_ORCHESTRATOR steps 2-4 above.\n\n"
)

_SUBORCH_PHASE3_START = "### PHASE 3 — CLOSEOUT (all agents complete or decommissioned)"
_SUBORCH_PHASE3_END = "**Closeout steps (order matters):**"
_SUBORCH_PHASE3_NOTE = (
    "### PHASE 3 — CLOSEOUT\n\n"
    "You are a chain SUB-ORCHESTRATOR: CH_SUB_ORCHESTRATOR step 7 below is your\n"
    "AUTHORITATIVE closeout order — `complete_job` FIRST (closes your execution so the\n"
    "readiness gate passes), THEN `write_project_closeout` (the conductor's ADVANCE\n"
    "signal), then post DONE to the Hub. The inverse raises COMPLETION_BLOCKED and stalls\n"
    "the chain. Confirm all agents complete and drain messages (`get_thread_history` on your "
    "coordination thread) first;\n"
    "file deferred findings via `create_task` / `create_project` and cite the IDs in\n"
    "`decisions_made`. Closeout works WITHOUT git: if `complete_job` returns\n"
    "`git_unavailable: true` (non-git env / missing binary / bare repo) the job still\n"
    "closes — note 'git not available — commits omitted' in your summary so the trail is\n"
    "honest. The standard closeout steps follow:\n\n"
)


def _apply_anchor_slice(protocol: str, start_anchor: str, end_anchor: str, note: str) -> str:
    start = protocol.find(start_anchor)
    end = protocol.find(end_anchor)
    if start == -1 or end == -1 or start >= end:
        return protocol
    return protocol[:start] + note + protocol[end:]


def trim_embedded_protocol_for_chain(protocol: str, role: str, phase: str | None = None) -> str:
    if not protocol:
        return protocol
    if role == "conductor":
        cuts = [(_CHAIN_PROTOCOL_REGION_START, _CHAIN_PROTOCOL_REGION_END, _CONDUCTOR_EMBEDDED_NOTE)]
    elif role == "sub_orchestrator":
        if phase == "staging":
            cuts = [
                (_SUBORCH_PHASE1_START, _SUBORCH_PHASE1_END, _SUBORCH_PHASE1_NOTE),
                (_SUBORCH_STAGING_IMPL_REGION_START, _SUBORCH_STAGING_IMPL_REGION_END, _SUBORCH_STAGING_IMPL_NOTE),
            ]
        else:
            cuts = [
                (_SUBORCH_PHASE1_START, _SUBORCH_PHASE1_END, _SUBORCH_PHASE1_NOTE),
                (_SUBORCH_PHASE3_START, _SUBORCH_PHASE3_END, _SUBORCH_PHASE3_NOTE),
            ]
    else:
        return protocol
    for start_anchor, end_anchor, note in cuts:
        protocol = _apply_anchor_slice(protocol, start_anchor, end_anchor, note)
    return protocol


_CHAIN_MISSION_PI_HEADER = re.compile(r"(?m)^#{1,6}\s*P_?(\d+)\b")
_MARKDOWN_HEADER = re.compile(r"(?m)^#{1,6}\s.*$")


def find_chain_mission_block(chain_mission: str, position: int, project_id: str | None = None) -> str | None:
    if not chain_mission:
        return None
    headers = list(_MARKDOWN_HEADER.finditer(chain_mission))
    own = next(
        (h for h in headers if (m := _CHAIN_MISSION_PI_HEADER.match(h.group(0))) and int(m.group(1)) == position),
        None,
    )
    if own is None and project_id:
        own = next((h for h in headers if project_id in h.group(0)), None)
    if own is None:
        return None
    level = len(own.group(0)) - len(own.group(0).lstrip("#"))
    end = len(chain_mission)
    for h in headers:
        if h.start() > own.start() and len(h.group(0)) - len(h.group(0).lstrip("#")) <= level:
            end = h.start()
            break
    return chain_mission[own.start() : end].rstrip()


_GIT_CONSTRAINT_SELF_ADOPT = """- **Git commit requirement does NOT apply *while you are delegating*.** When you SPAWN a
  worker, IT commits its work and you coordinate — you do not commit on its behalf. A job you
  SELF-ADOPT (only when your harness has no spawn mechanism at all)
  carries that worker's commit duty: commit its work (git add the specific files;
  NEVER git add -A) before complete_job, exactly as the worker protocol requires."""
_GIT_CONSTRAINT_SUBAGENT = """- **You are the committer (subagent mode).** Your workers run in this session and do NOT
  commit: each lists its changed files in `complete_job(result={"artifacts": [...]})`. Stage
  those files by name (git add the specific files; NEVER git add -A) and commit once before
  closeout. A job you SELF-ADOPT (only when your harness has no spawn mechanism at all) is
  committed the same way."""
_GIT_WARNING_MULTI_TERMINAL = """expected for a PURE coordinator or a docs-only agent, but
if you SELF-ADOPTED any job it is a RED FLAG that your own work is uncommitted: commit it and re-verify."""
_GIT_WARNING_SUBAGENT = """on a project that changed code it is a RED FLAG that your workers'
files are uncommitted (you are the committer): commit them and re-verify. Docs-only needs no action."""
_GIT_CONSTRAINT_CONDUCTOR_SUBAGENT = (
    "- **Git commit requirement does NOT apply.** You only delegate. In this subagent chain each "
    "project's sub-orchestrator commits once for its project; its workers hand it their files."
)
_GIT_CONSTRAINT_CONDUCTOR_MULTI_TERMINAL = (
    "- **Git commit requirement does NOT apply.** You only delegate. In this multi-terminal chain "
    "each worker commits its own work in its own tree."
)


def _apply_conductor_body_trims(body: str) -> str:
    body = _apply_anchor_slice(
        body, _WORKER_SPAWN_BLOCK_START, _PROGRESS_REPORTING_ANCHOR, _CONDUCTOR_COORDINATION_NOTE
    )
    return _apply_anchor_slice(body, _PHASE3_CLOSEOUT_START, _ORCHESTRATOR_CONSTRAINTS_ANCHOR, _CONDUCTOR_CLOSEOUT_NOTE)


CLOSEOUT_TAG_LIST = ", ".join(sorted(CONTROLLED_TAG_VOCABULARY))


CHAIN_DRIVER_MODEL = (
    "Who starts each project: when a project closes out, the server advances the chain and opens "
    "the next project's gate. The user (from the dashboard) or the conductor (from its own session) "
    "starts the next project. A sub-orchestrator runs its own project only and never starts the next "
    "one. The per-project recovery prompt is for recovery only."
)


def render_chain_driver_model(indent: str) -> str:
    return textwrap.fill(CHAIN_DRIVER_MODEL, width=88, initial_indent=indent, subsequent_indent=indent)


LAUNCH_PROMPT_RULE = (
    "LAUNCH PROMPT: start every agent with the prompt the server issued for its job (the "
    "agent_prompt spawn_job returned), verbatim, as its first message; a hand-written work "
    "order may add to it, never replace it."
)

_TODO_AND_MISSION_CONSTRAINTS = (
    "- **Your TODO list is your authority.** The mission describes what needs to happen.\n"
    "  Your TODOs are the structured breakdown. Work them systematically.\n"
    "- **Missions** (yours and each worker's): goal / current state / steps / boundaries /\n"
    "  done-when; cite ids instead of restating background. Record a worker's scope change\n"
    "  with `update_job_mission`."
)


def _build_orchestrator_protocol_body(
    job_id: str,
    tenant_key: str,
    executor_id: str,
    wake_pattern: str,
    execution_mode: str,
    tool: str,
    is_chain_conductor: bool = False,
) -> str:
    is_subagent = is_subagent_render(execution_mode)
    if is_subagent:
        spawn_syntax = _SUBAGENT_SPAWN_BY_TOOL.get(tool, _SUBAGENT_SPAWN_GENERIC)
        phase1_launch_line = (
            f'   - "I will spawn each agent directly via {spawn_syntax} — no dashboard copy/paste needed."'
        )
        replacement_launch_line = (
            f"  → Launch the replacement directly via {spawn_syntax}; its first call is "
            "`get_job_mission(job_id=...)` so it binds to the new job record"
        )
        resting_wait_block = f"""**If your spawned subagents are running (nothing actionable right now):**
  → `set_agent_status(job_id="{job_id}", status="idle", reason="Monitoring — agents running")` (also after you pass the baton)"""
        unblock_relay_line = (
            f"  → The subagent reads your reply on its next get_thread_history poll — relaunch it via "
            f"{spawn_syntax} if it already exited (its first `get_job_mission` rebinds it to the job)"
        )
        verification_launch_block = """    - Launch the subagent now via your CLI; its VERY FIRST call MUST be
      `get_job_mission(job_id=<the job_id from step 1>)` so it binds to the record you just created."""
    else:
        phase1_launch_line = '   - "Copy agent prompts from the dashboard to start them."'
        replacement_launch_line = (
            "  → Tell user to start the new prompt in a new agent session (terminal, desktop, or web tab)"
        )
        resting_wait_block = f"""**If waiting for user to start agents (multi-terminal):**
  → `set_agent_status(job_id="{job_id}", status="idle", reason="Monitoring — waiting for agents to start")` (also after you pass the baton)"""
        unblock_relay_line = '  → Tell user: "Go to that agent\'s terminal and say: the orchestrator responded"'
        verification_launch_block = """    - Subagent mode: launch the subagent, and its VERY FIRST call MUST be
      `get_job_mission(job_id=<the job_id from step 1>)` so it binds to the record you just created.
    - Multi-terminal: tell the user "Verification agent spawned, start it from the dashboard.\""""

    if is_chain_conductor:
        git_commit_constraint = (
            _GIT_CONSTRAINT_CONDUCTOR_SUBAGENT if is_subagent else _GIT_CONSTRAINT_CONDUCTOR_MULTI_TERMINAL
        )
    elif is_subagent:
        git_commit_constraint = _GIT_CONSTRAINT_SUBAGENT
    else:
        git_commit_constraint = _GIT_CONSTRAINT_SELF_ADOPT

    git_warning_expectation = _GIT_WARNING_SUBAGENT if is_subagent else _GIT_WARNING_MULTI_TERMINAL

    giljo_cmd = giljo_invocation(tool)

    body = f"""These are your coordination operating procedures. Follow them from startup through closeout.

## Orchestrator Coordination Protocol (3 Phases)

### PHASE 1 — STARTUP (execute once, after get_job_mission)

**MANDATORY:** `get_job_mission(job_id="{job_id}")` starts EVERY implementation session, even with
prior context: it moves you `waiting` → `working` (skip it and the dashboard never sees you).
**PROTOCOL CACHE:** later fetches pass its `protocol_etag`; `protocol_unchanged=true` means reuse the copy you have.

1. Read `current_team_state` in this response (live-queried) and your pre-planned TODOs from
   staging. **DO NOT drop any items:** `todo_items` takes the FULL list; `todo_append` adds new ones.
2. Report to the user: agent names, statuses and phase order, your TODO list, and:
{phase1_launch_line}
   - "I will actively coordinate. Wake me when agents need attention or on status changes."
3. Begin Phase 2 immediately — do not wait for user input.

### PHASE 2 — ACTIVE COORDINATION (TODO-driven — work your list on every wake-up)

{wake_pattern}

**{LAUNCH_PROMPT_RULE}**

**THE COORDINATION LOOP (execute on EVERY wake-up or trigger):**
```
1. RECEIVE   → get_thread_history(thread_id=<your coordination thread>, as_participant="{executor_id}", unread_only=true, mark_read=true)
2. ASSESS    → get_workflow_status() — live agent statuses
3. PROCESS   → handle blockers, completions, requests
4. ADVANCE   → the next actionable TODO: advance it, or note why it is blocked
5. REPORT    → report_progress(todo_items=[...full list with updated statuses...])
6. DECIDE    → incomplete TODOs with work: loop; waiting on agents: tell the user; none: Phase 3
```
**TODOs:** `in_progress` when started, `completed` only when done AND verified. A step handed to
a person or a follow-up task is `skipped`, its text starting `HANDOFF <TSK-id>:`. Never mark done
what did not happen.

**COORDINATION ACTIONS (use as needed within the loop):**
**Unblock an agent:** answer from your `mission` with
  `post_to_thread(thread_id=<your coordination thread>, content="...", from_agent="{executor_id}", to_participant="<agent_id>", requires_action=true)`
{unblock_relay_line}
**Spawn a replacement agent:** `spawn_job(...)`, then
{replacement_launch_line}
**Broadcast to team:** the same `post_to_thread` without `to_participant`; `requires_action=true` only if ALL must act.
**Spawn verification agent** (tester/reviewer) once the deliverable agents complete, unless they produced only
  docs or analysis: `get_agent_result(job_id="<their_job_id>")` for each, a mission built from those
  REAL artifacts (never guessed), then **(1) spawn_job FIRST — MANDATORY, NOT mode-dependent:**
  `spawn_job(agent_name="tester", agent_display_name="tester", mission="...", project_id="...")`
  mints the job_id and dashboard record. **(2) THEN launch the work** with that job_id:
{verification_launch_block}
  **NEVER launch a tester/reviewer via Agent/Task/spawn_agent/@-syntax without a preceding spawn_job.**
**Findings, triaged by RISK:** mechanical and caused by this project → fix inline, re-run the same
  checks, ship it here (never defer your own mess). Out of scope → `create_task`, cite the ID in
  `decisions_made`. Protected paths, irreversible, license/security/billing → `create_task` naming the
  approval gate. Architectural or risky (contracts, auth, migrations, concurrency) → re-spawn the
  deliverable agent with a scoped fix mission, never inline.

**PROGRESS REPORTING (MANDATORY after every coordination action):**
  → `report_progress(job_id="{job_id}", todo_items=[...FULL list with updated statuses...])`
  → `report_progress(job_id="{job_id}", todo_append=[...new items only...])`
  → `todo_items` REPLACES the entire list; the dashboard shows it, so keep it current.

### RESTING STATES (between coordination loops)

{resting_wait_block}

**If you want periodic auto-check-in:**
  → Ask the user: "I can sleep and re-check every N minutes; this costs tokens." If yes:
    `set_agent_status(job_id="{job_id}", status="sleeping", wake_in_minutes=15, reason="Auto-monitoring")`.
    Then sleep for the specified interval, wake, run the loop, repeat; report_progress moves you back to "working".

**Blocked vs Idle vs Sleeping:** `blocked` = an error it cannot clear; `idle` = nothing to do now
("Monitoring"); `sleeping` = back in N minutes.

### PHASE 3 — CLOSEOUT (all agents complete or decommissioned)

**Pre-closeout:** every agent complete (`get_workflow_status(project_id="...")`; skip it when every
worker returned inline), every TODO `completed` or handed off (`skipped`), this project's
mechanical findings fixed. `complete_job` names any unread action-required post, so no extra inbox read.

**Git:** `git_unavailable: true` on `complete_job` means no git here; the job still closes: write
"git not available — commits omitted" in your summary. `git_warning` = git on, no commits found:
{git_warning_expectation}

**Closeout steps (order matters):**
1. Settle every non-closeout TODO via `report_progress()`: `completed` only if it happened, else `skipped` as a HANDOFF.
2. `complete_job(job_id="{job_id}", result={{"summary": "...", "artifacts": [...]}})` — YOUR job FIRST (your
   closeout TODO auto-completes). READ its `closeout_checklist`. Deferred findings needing the user:
   `request_approval(...)`; only the CloseoutModal ApprovalCard or `decide_approval(approval_id, option_id)` clears it.
3. File follow-ups with `create_task()` / `create_project()`; cite each in `decisions_made` as `OPEN <TSK-id>: ...`
4. `write_project_closeout(project_id="...", summary="...", key_outcomes=[...], decisions_made=[...], tags=[...], git_commits=[...])`
   — `tags`: 1-5 from {CLOSEOUT_TAG_LIST}.
5. Tell user: "Project complete. Use `{giljo_cmd}` to create follow-ups or look up existing project/task state."

**IMPORTANT:** complete your own job (step 2) BEFORE closing the project (step 4).
**`complete_job()` rejected?** Unread action-required posts: drain with the RECEIVE
`get_thread_history` call above, ACT on them, retry (there is no bypass flag). TODO items incomplete → review and update your TODO list, then retry.

## ORCHESTRATOR CONSTRAINTS
{git_commit_constraint}
- **Low on context?** Write a handover task (`create_task(task_type="HND", ...)`), then tell
  the user its serial so a fresh session can continue from it.
- **You operate with the user's delegated authority.** Decide and document in
  `decisions_made`. Escalate via `request_approval` only when the choice is
  irreversible, materially changes scope, or has no clear default.
{_TODO_AND_MISSION_CONSTRAINTS}

---
**Your Identifiers:** job_id `{job_id}` (progress, completion); agent_id `{executor_id}` (your
`from_agent` and `as_participant`). **UUID-ONLY ADDRESSING:** `to_participant` takes agent_id
UUIDs from current_team_state, NEVER display names like "orchestrator" or "implementer".
**MCP tools are NATIVE tool calls; never curl, HTTP, or SDK calls.**
"""
    if not is_chain_conductor:
        return body
    return _apply_conductor_body_trims(body)


_CH3_GENERIC_MCP_PREFERRED = r"""AGENT PROMPT — read this first: spawn_job returns an `agent_prompt` for every job. Launch
the agent with that text, verbatim, as its first message. NEVER write your own worker prompt: a
hand-written one does not call get_job_mission, so the job never starts and stays `waiting`.
A work order may add to the agent_prompt, never replace it. In every launch line below,
`<prompt>` IS that agent_prompt.

DELEGATE FIRST — you are an ORCHESTRATOR, not the implementer. Your default is to
SPAWN a dedicated agent for every job order and let it do the work; you coordinate.
Doing the implementation yourself is the LAST resort (the SELF-ADOPT rung below), not
the first move — reach for it ONLY when your harness genuinely has no way to spawn.

Run one agent per job order IN PARALLEL. spawn_job(...) ALWAYS comes first — it
mints the job_id + the dashboard audit record — then you launch the agent seeded
with the agent_prompt that call returned. The role and its model/effort
hints arrive in the get_job_mission agent_profile — nothing to look up, nothing
to install. Use whichever launch mechanism your session supports:

OPTION A — ONE TERMINAL PER AGENT (best: true parallelism, like Multi-Terminal).
If your TUI / session can open OS terminal windows, launch each agent as its own
terminal running YOUR harness. Detect your OS and use the matching launcher —
give each a distinct --title and tab color so the human can see the fleet:

  - Windows (Windows Terminal):
      wt -w 0 new-tab -d "<workdir>" --title "<title>" --tabColor "#<hex>" cmd /k <your-harness> --prompt "<prompt>"
    opencode (common) — exact form:
      wt -w 0 new-tab -d "<workdir>" --title "<title>" --tabColor "#<hex>" cmd /k opencode --prompt "<prompt>"
    Key: the cmd /k wrapper (NOT pwsh -NoExit) so opencode.cmd resolves from PATH.

  - macOS (Terminal):
      osascript -e 'tell app "Terminal" to do script "cd <workdir> && <your-harness> --prompt \"<prompt>\""'

  - Linux (emulator varies by desktop — use the one installed):
      gnome-terminal --working-directory="<workdir>" -- <your-harness> --prompt "<prompt>"
      (konsole: konsole --workdir "<workdir>" -e <your-harness> --prompt "<prompt>";  xterm: xterm -e <your-harness> --prompt "<prompt>")

  Replace <your-harness> with your CLI's own command and --prompt with its
  prompt-seeding flag: opencode uses --prompt; many CLIs take the prompt
  positionally (e.g. `<your-harness> "<prompt>"`) — use whatever launches YOUR
  harness with an initial prompt and STAYS open.

OPTION B — IN-PROCESS SUBAGENT. If your harness CANNOT open terminals but HAS a
subagent / spawn / delegate mechanism (a Task tool, an agent spawner, an
@-mention), use that: spawn_job(...) first, then hand the subagent the agent_prompt
that call returned, verbatim.

CROSS-AGENT COORDINATION IS MCP-ONLY (spawn_job / post_to_thread / get_thread_history)
— a subagent is reachable across job boundaries ONLY through the MCP hub; never
assume a native return value crosses a job. (A subagent MAY use its harness's own
child-agent feature for INTERNAL decomposition within its single job.)"""

_CH3_GENERIC_MCP_SELF_ADOPT = """VERIFY FIRST: does your harness have ANY spawn / subagent / delegate mechanism
(a Task tool, an agent spawner, an @-mention, a delegate command, or the ability to
open a terminal per OPTION A above)? If ANY of these exists, using it is MANDATORY —
go back to the preferred rung. SELF-ADOPT is the LAST resort, reached ONLY after you
have confirmed no spawn path exists at all.

Once confirmed harness-less, you MAY SELF-ADOPT the queued jobs: work them yourself,
sequentially, one at a time, in launch order, in THIS session — for each job:
get_job_mission(job_id) → do the work → commit the work (when git integration is enabled:
git add the specific files you changed; NEVER git add -A) → complete_job(job_id) → advance
to the next job ONLY after the current one is complete. A self-adopted job carries the
worker's commit duty — you skip committing ONLY for jobs you actually DELEGATED, never for
work you did yourself. This permission is GRANTED by your choice of subagent mode (it is the
mode's declared fallback, like link_projects turning a session into the conductor); it is
NOT an ambient default and never applies in multi_terminal mode. Never batch-start the queue
— finish and complete_job one job before adopting the next."""

_CH3_GENERIC_MCP_SELF_ADOPT_CHAT = """Your harness has NO subagent mechanism AND no code workspace (a chat-only
session). You MAY still SELF-ADOPT the PLANNING / PM jobs — get_job_mission(job_id)
→ work → complete_job(job_id) → next, in launch order, one at a time — but you
CANNOT self-adopt a CODE job here (there is no environment to execute it). There is
no commit step here: a planning/PM job produces nothing to commit, and the worker
commit duty a self-adopted CODE job would inherit needs a shell you do not have. This
permission is GRANTED by your choice of subagent mode; it is not an ambient
default and never applies in multi_terminal mode. For any code job, see the floor
below."""

_CH3_GENERIC_MCP_FLOOR_LINE = (
    "This project has code work that can't run in this session — re-stage it on a "
    "CLI workstation (Claude Code, Codex, or opencode) and it will run there."
)
