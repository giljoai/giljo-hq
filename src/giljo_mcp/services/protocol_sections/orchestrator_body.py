# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import re

from giljo_mcp.platform_registry import giljo_invocation, is_subagent_render


logger = logging.getLogger(__name__)


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
    "CH_SUB_ORCHESTRATOR step 5 above is your AUTHORITATIVE implementation entry: after\n"
    "staging-end you call `get_job_mission` ONCE (without your boot `protocol_etag`) and it flips\n"
    "you waiting→working and returns this implementation protocol. There is NO human Implement\n"
    "click, you do NOT wait for the user to start agents, and you do NOT return to the\n"
    "dashboard — the solo multi_terminal startup that says otherwise does NOT apply to a chain\n"
    "member. On entry: read `current_team_state` from this response (live-queried) and your\n"
    "pre-planned coordination TODOs (written during staging — do NOT drop any items), then\n"
    "begin PHASE 2 immediately.\n\n"
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


_CHAIN_MISSION_PI_HEADER = re.compile(r"(?m)^#{1,6}\s*P_(\d+)\b")


def slice_chain_mission_for_position(chain_mission: str, position: int) -> str:
    if not chain_mission:
        return chain_mission
    headers = list(_CHAIN_MISSION_PI_HEADER.finditer(chain_mission))
    if not headers:
        return chain_mission
    for idx, match in enumerate(headers):
        if int(match.group(1)) == position:
            start = match.start()
            end = headers[idx + 1].start() if idx + 1 < len(headers) else len(chain_mission)
            return chain_mission[start:end].rstrip()
    logger.warning(
        "chain_mission has P_i headers but none for position %d; shipping the whole mission (tolerance).",
        position,
    )
    return chain_mission


_GIT_CONSTRAINT_SELF_ADOPT = """- **Git commit requirement does NOT apply *while you are delegating*.** When you SPAWN a
  worker, IT commits its work and you coordinate — you do not commit on its behalf. But a job
  you SELF-ADOPT (implement yourself in this session) carries that worker's commit duty: commit
  its work (git add the specific files; NEVER git add -A) before complete_job, exactly as the
  worker protocol requires."""
_GIT_CONSTRAINT_CONDUCTOR = (
    "- **Git commit requirement does NOT apply.** You only delegate — each project's own workers commit their work."
)


def _apply_conductor_body_trims(body: str) -> str:
    body = _apply_anchor_slice(
        body, _WORKER_SPAWN_BLOCK_START, _PROGRESS_REPORTING_ANCHOR, _CONDUCTOR_COORDINATION_NOTE
    )
    return _apply_anchor_slice(body, _PHASE3_CLOSEOUT_START, _ORCHESTRATOR_CONSTRAINTS_ANCHOR, _CONDUCTOR_CLOSEOUT_NOTE)


LAUNCH_PROMPT_RULE = (
    "LAUNCH PROMPT: start every agent with the prompt the server issued for its job (the "
    "agent_prompt spawn_job returned), verbatim, as its first message; a hand-written work "
    "order may add to it, never replace it."
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
  → `set_agent_status(job_id="{job_id}", status="idle", reason="Monitoring — agents running")`
  → Dashboard shows "Monitoring" — user knows you're available but not burning tokens; same when you handed the baton on"""
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
  → `set_agent_status(job_id="{job_id}", status="idle", reason="Monitoring — waiting for agents to start")`
  → Dashboard shows "Monitoring" — user knows you're available but not burning tokens; same when you handed the baton on"""
        unblock_relay_line = '  → Tell user: "Go to that agent\'s terminal and say: the orchestrator responded"'
        verification_launch_block = """    - Subagent mode: launch the subagent, and its VERY FIRST call MUST be
      `get_job_mission(job_id=<the job_id from step 1>)` so it binds to the record you just created.
    - Multi-terminal: tell the user "Verification agent spawned, start it from the dashboard.\""""

    git_commit_constraint = _GIT_CONSTRAINT_CONDUCTOR if is_chain_conductor else _GIT_CONSTRAINT_SELF_ADOPT

    giljo_cmd = giljo_invocation(tool)

    body = f"""These are your coordination operating procedures. Follow them from startup through closeout.

## Orchestrator Coordination Protocol (3 Phases)

### PHASE 1 — STARTUP (execute once, after get_job_mission)

**MANDATORY:** You MUST call `get_job_mission(job_id="{job_id}")` at the start of every
implementation session, even if you already have context from a prior phase. This call
transitions your status from `waiting` to `working` on the server — it is a deterministic
state signal, not just a data fetch. Skipping it leaves you invisible on the dashboard.

**PROTOCOL CACHE (saves ~15-50KB on a re-fetch):** the response includes a `protocol_etag`.
Remember it. On any LATER `get_job_mission` this session — an implementation-phase refresh, a
reactivation, or (best-effort) a staging session whose context continues into implementation —
pass `protocol_etag=<that value>`. If the response has `protocol_unchanged=true`, your
`agent_identity` + `full_protocol` are unchanged (returned null by design) — reuse the copy you
already have instead of re-reading them.

**Tool names below are bare** (e.g. `get_workflow_status`, `complete_job`); your MCP client may
expose them under a prefix (e.g. `mcp__<server>__<tool>`) — call them by the names your harness
lists.

1. Read the `current_team_state` field from this response — it is live-queried, not stale.
2. Read your pre-planned coordination TODOs (written during staging, waiting for you).
   **DO NOT drop any items.** To update statuses, use `todo_items` with the FULL list (all items, updated statuses).
   To add genuinely NEW tasks discovered mid-implementation, use `todo_append`.
3. Report to user:
   - Agent names, statuses, and phase order (from `current_team_state`)
   - Your TODO list with current status of each item
{phase1_launch_line}
   - "I will actively coordinate. Wake me when agents need attention or on status changes."
4. Begin Phase 2 immediately — do not wait for user input.

### PHASE 2 — ACTIVE COORDINATION (TODO-driven — work your list on every wake-up)

{wake_pattern}

**{LAUNCH_PROMPT_RULE}**

**THE COORDINATION LOOP (execute on EVERY wake-up or trigger):**

Every time you are activated — whether by user interaction, a sleep timer, a subagent
completing, an unblock event, or any other trigger — execute this loop:

```
1. RECEIVE   → get_thread_history(thread_id=<your coordination thread>, as_participant="{executor_id}", unread_only=true, mark_read=true) — drain your message queue
2. ASSESS    → get_workflow_status() — get live agent statuses
3. PROCESS   → Handle any messages (blockers, completions, requests)
4. ADVANCE   → Look at your TODO list. Find the next actionable item.
               Can you advance it? Do so. Is it blocked? Note why.
5. REPORT    → report_progress(todo_items=[...full list with updated statuses...])
               (use todo_append ONLY for genuinely NEW tasks, not status updates)
6. DECIDE    → Are there still incomplete TODOs?
               YES with actionable work → continue loop from step 1
               YES but waiting on agents → tell user what you're waiting for
               NO → proceed to Phase 3 (CLOSEOUT)
```

**TODO ITEM LIFECYCLE:**
- Mark items `in_progress` when you start working them
- Mark items `completed` when the coordination action is done AND verified
- A "spawn agents" TODO is completed when agents are spawned and confirmed working
- An "unblock agent X" TODO is completed when you sent guidance AND agent resumed
- A "verify deliverables" TODO is completed when you confirmed artifacts exist

**COORDINATION ACTIONS (use as needed within the loop):**

**Unblock an agent:**
  → Read blocker message content
  → Consult your `mission` field for relevant context
  → `post_to_thread(thread_id=<your coordination thread>, content="...", from_agent="{executor_id}", to_participant="<agent_id>", requires_action=true)`
{unblock_relay_line}
  → Update the relevant TODO item

**Spawn a replacement agent:**
  → `spawn_job(...)`
{replacement_launch_line}
  → New agent reads predecessor context via `get_job_mission`
  → Update the relevant TODO item

**Broadcast to team:**
  → `post_to_thread(thread_id=<your coordination thread>, content="...", from_agent="{executor_id}", requires_action=false)` — omit `to_participant` for a broadcast; everyone on the thread sees it.
  → Broadcasts are informational by default (requires_action=false). Set requires_action=true only if ALL recipients must act.

**Spawn verification agent (after all deliverable agents complete):**
  → For each completed deliverable agent: `get_agent_result(job_id="<their_job_id>")`
  → Build a precise tester/reviewer mission from the REAL results (files_changed, commits, summary)
  → **(1) spawn_job FIRST — MANDATORY, NOT mode-dependent.** Call
    `spawn_job(agent_name="tester", agent_display_name="tester", mission="...", project_id="...")`
    BEFORE launching anything. This mints the MCP job_id and the dashboard record (TODOs, recorded
    verdict, audit trail). There is no path that skips this step — subagent mode does NOT exempt you.
  → **(2) THEN launch the work** using the job_id returned by step 1:
{verification_launch_block}
  → **NEVER launch a tester/reviewer via Agent/Task/spawn_agent/@-syntax without a preceding spawn_job.**
    Doing so loses the job_id, the TODOs, the recorded verdict, and the dashboard audit trail — the agent
    runs invisibly and unauditable. Mode does NOT change this. spawn_job is always step 1.
  → Update the relevant TODO item

**Implementation-phase verification spawning:**

- **WHEN to spawn verification:** After deliverable agents (implementer, analyzer, documenter) complete
  AND the project produced code or testable artifacts. If all agents produced only documentation or
  analysis (no changed code, no new APIs, no migrations), skip verification entirely — there is
  nothing for a tester/reviewer to run.
- **HOW to build the verification mission:** Call `get_agent_result(job_id=<deliverable_job_id>)` for
  every completed deliverable agent. Anchor the tester/reviewer mission in REAL artifacts: exact file
  paths, commit hashes, API names, and behavior changes from those results. Never write a speculative
  mission ("the implementer probably added X") — if the result is absent, note it as unknown and scope
  verification to what is confirmed.
- **HOW to handle non-blocking findings (triage by RISK, not file count):**
  - *Mechanical AND caused by this project* — drop a stranded field, delete vestigial code orphaned by this commit, rename a symbol this project introduced, fix a regex/constant that drifted as a side effect. → Fix inline regardless of file count, re-run the same verification (the project's test runner + linter + the CI you push to), ship the fix in THIS project. Do NOT defer your own mess.
  - *Out-of-scope finding* — pre-existing default-branch bug not introduced by this project, unrelated cleanup the reviewer noticed in passing. → `create_task` and cite the ID in `decisions_made`. Audit purity matters.
  - *Needs user approval* — the product's declared protected paths (repo-root config files, license/docs directories, install/startup scripts, or similar); irreversible actions; license/security/billing changes. → `create_task` with the approval gate stated in the description.
  - *Architectural, multi-file logic, or risky* — anything that re-shapes a contract, spans a major structural boundary, touches concurrency/auth/migrations, or that the reviewer flagged as needing design discussion. → Re-spawn the deliverable agent with a scoped fix mission citing the exact finding. Do NOT fix inline.

**PROGRESS REPORTING (MANDATORY after every coordination action):**
  → To update statuses: `report_progress(job_id="{job_id}", todo_items=[...FULL list with updated statuses...])`
  → To add NEW tasks: `report_progress(job_id="{job_id}", todo_append=[...new items only...])`
  → **CRITICAL:** `todo_items` REPLACES the entire list — always include ALL items (completed + in_progress + pending), never a partial list
  → The dashboard displays your TODO list — keep it current

### RESTING STATES (between coordination loops)

After completing a coordination loop with no actionable work remaining:

{resting_wait_block}

**If you want periodic auto-check-in:**
  → Ask the user: "Would you like me to periodically check on agents? I can sleep and re-check every N minutes. Note: this increases token consumption."
  → If yes: `set_agent_status(job_id="{job_id}", status="sleeping", wake_in_minutes=15, reason="Auto-monitoring")`
  → Then sleep for the specified interval, wake, run the coordination loop, repeat
  → report_progress after waking transitions you back to "working"

**Blocked vs Idle vs Sleeping:**
  - `blocked` = I need human help to continue (shows "Blocked")
  - `idle` = I'm done dispatching, nothing to do right now (shows "Monitoring")
  - `sleeping` = I'll check back in N minutes automatically (shows "Sleeping")

### PHASE 3 — CLOSEOUT (all agents complete or decommissioned)

**Pre-closeout verification:**
1. `get_workflow_status(project_id="...")` — confirm all agents are complete
2. `get_thread_history(thread_id=<your coordination thread>, as_participant="{executor_id}", unread_only=true, mark_read=true)` — drain final messages
3. Review your TODO list — ALL items must be `completed`
   If any are not, either complete them or explain why they were dropped

**Deferred findings:**
Apply the Phase 2 triage rule ("HOW to handle non-blocking findings"). Mechanical findings caused by this project MUST be fixed before closeout — they are not deferral candidates. Only out-of-scope, protected-zone, or architectural findings are legitimate deferrals: file them via `create_task` (or `create_project` if multi-step) and cite the returned ID in `decisions_made` when you call `write_project_closeout`.

**Closeout works without git:**
Git commit collection is best-effort. When the server cannot resolve commits (non-git environment,
missing binary, bare repo), the `complete_job()` response will include `git_unavailable: true` and
a human-readable `git_unavailable_reason` explaining why. The job still closes cleanly; the commit
list will be empty or contain only agent-supplied hashes. When this happens, include the phrase
"git not available — commits omitted" in your closeout summary so the audit trail is honest. The
`git_warning` field covers a separate case: git integration enabled but the agent produced no
commits. This is expected for a PURE coordinator (you only spawned workers — THEY committed) or a
documentation-only agent, and needs no action THERE. But if you SELF-ADOPTED any job (did the
implementation yourself in this session), a no-commits warning is a RED FLAG that your own work is
uncommitted: go back, commit the changed files (git add the specific files; NEVER git add -A) and
re-verify before closeout.

**Closeout steps (order matters):**
> Chain conductor exception: if you are the CONDUCTOR of a sequential multi-project chain with projects still incomplete, do NOT self-complete here — follow CH_CHAIN_DRIVE and ADVANCE to the next project (`launch_implementation`) instead. complete_job is valid only after the final project closes out.
1. Mark any remaining non-closeout TODO items as `completed` via `report_progress()` (a TODO describing the closeout itself does NOT need to be marked completed first — see step 2)
2. `complete_job(job_id="{job_id}", result={{"summary": "...", "artifacts": [...]}})` — mark YOUR orchestrator job complete FIRST
   → The gate auto-completes any TODO that describes the closeout itself (classified structurally when the TODO was written) — no flag exists or is needed, and there is no chicken-and-egg: you never mark your closeout TODO done before calling closeout. Non-closeout incomplete TODOs still block. The unread-messages gate is independent — it blocks only on genuine action-required posts; drain them with `get_thread_history()` on your coordination thread first.
   → READ the `closeout_checklist` in the response
   → When the closeout has deferred findings, call `request_approval(...)` — your execution status will be flipped to `awaiting_user` automatically, and `complete_job` will refuse until the user decides. UI note: the decide buttons render INSIDE the project's CloseoutModal (ApprovalCard component); the top-level dashboard only shows a passive "Needs decision" pill, not a clickable banner. Users frequently respond verbally instead — if they do, the gate does NOT auto-clear. `set_agent_status` only accepts blocked/idle/sleeping (it cannot transition out of `awaiting_user`); `report_progress` does not auto-wake from `awaiting_user` either. The ONLY way to clear the gate is `POST /api/approvals/{{id}}/decide` (which the ApprovalCard calls). On verbal approval, guide the user to open the project's CloseoutModal and click the ApprovalCard option, or to call the decide endpoint directly. Otherwise proceed with best judgment.
3. Create follow-up tasks/projects for deferred findings via `create_task()` or `create_project()` and cite the returned IDs in `decisions_made`
4. `write_project_closeout(project_id="...", summary="...", key_outcomes=[...], decisions_made=[...], tags=[...], git_commits=[...])` — final close. `tags` is REQUIRED-IN-SPIRIT: supply 1-5 from the 16-tag CONTROLLED_TAG_VOCABULARY (see Chapter 5). Unknown tags are rejected.
5. Tell user: "Project complete. Use `{giljo_cmd}` to create follow-ups or look up existing project/task state."

**IMPORTANT:** You MUST complete your own job (step 2) BEFORE closing the project (step 4). The server requires all agents including the orchestrator to be complete before project closeout.

**If `complete_job()` is rejected:** Read the error. Common causes:
- Unread messages remain → run get_thread_history(thread_id=<your coordination thread>, as_participant="{executor_id}", unread_only=true, mark_read=true) and ACT on the posts — only genuine action-required posts block this gate, and acting on them (then retrying) is the ONLY way through; there is no bypass flag
- TODO items incomplete �� review and update your TODO list, then retry

## ORCHESTRATOR CONSTRAINTS
{git_commit_constraint}
- **Low on context?** Write a handover task (`create_task(task_type="HND", ...)`), then tell
  the user its serial so a fresh session can continue from it.
- **You operate with the user's delegated authority.** Decide and document in
  `decisions_made`. Escalate via `request_approval` only when the choice is
  irreversible, materially changes scope, or has no clear default.
- **Your TODO list is your authority.** The mission describes what needs to happen.
  Your TODOs are the structured breakdown. Work them systematically.

---
**Your Identifiers:**
- job_id (work order): `{job_id}` — Use for progress, completion
- agent_id (executor): `{executor_id}` — Use for messages (from_agent on post_to_thread, as_participant on get_thread_history)

**MESSAGING RULE: UUID-ONLY ADDRESSING**
- ALWAYS use agent_id UUIDs in `to_participant` (from current_team_state)
- NEVER use display names like "orchestrator" or "implementer" in `to_participant`
- Your `from_agent` is always: `{executor_id}`

**CRITICAL: MCP tools are NATIVE tool calls. Use them like Read/Write/Bash.**
**Do NOT use curl, HTTP, or SDK calls.**
"""  # noqa: S608 — prose protocol template, not SQL
    if not is_chain_conductor:
        return body
    return _apply_conductor_body_trims(body)


_CH3_GENERIC_MCP_PREFERRED = r"""DELEGATE FIRST — you are an ORCHESTRATOR, not the implementer. Your default is to
SPAWN a dedicated agent for every job order and let it do the work; you coordinate.
Doing the implementation yourself is the LAST resort (the SELF-ADOPT rung below), not
the first move — reach for it ONLY when your harness genuinely has no way to spawn.

Run one agent per job order IN PARALLEL. spawn_job(...) ALWAYS comes first — it
mints the job_id + the dashboard audit record — then you launch the agent seeded
with the thin prompt get_job_mission(job_id='...'). The role and its model/effort
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
@-mention), use that: spawn_job(...) first, then hand the subagent the thin
get_job_mission(job_id='...') prompt.

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
