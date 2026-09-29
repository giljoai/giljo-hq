# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.branding import MCP_ALIAS
from giljo_mcp.platform_registry import Platform, is_subagent_render
from giljo_mcp.prompts.default_agent_ladder import MISSING_AGENT_TEMPLATES_NOTICE

from giljo_mcp.services.protocol_sections.closing_jobs import _CLOSING_JOBS_REFERENCE

from giljo_mcp.services.protocol_sections.orchestrator_body import (
    _CH3_GENERIC_MCP_FLOOR_LINE,
    _CH3_GENERIC_MCP_PREFERRED,
    _CH3_GENERIC_MCP_SELF_ADOPT,
    _CH3_GENERIC_MCP_SELF_ADOPT_CHAT,
    render_capability_ladder,
)



_CH3_CODEX = (
    "agent_name → the agent_profile in that job's get_job_mission response",
    """Codex CLI Note:
  - spawn_agent(agent='gil-X') where X = agent_name (NOT display_name)
  - agent_name binds the MCP DB record to the job; the role arrives from the server
  - The server returns agent_name WITHOUT 'gil-' prefix — you MUST prepend it""",
    """── YOUR PLATFORM: CODEX CLI ────────────────────────────────────────────────
spawn_agent syntax (IMPLEMENTATION PHASE ONLY - not during staging):
  spawn_agent(agent='gil-{agent_name}', instructions='...')

CRITICAL: ALL GiljoAI agents use the 'gil-' prefix in Codex CLI.
The server returns agent_name WITHOUT the prefix. You MUST prepend 'gil-'.

WHERE THE ROLE COMES FROM: the server, not your disk. The thin prompt spawn_job
returned carries this agent's model/effort hints when they are set, and
get_job_mission returns its full agent_profile (role,
description, instructions, behavioural rules, success criteria). There is no
agent template file to install, look up, or keep in sync — so do NOT re-explain
the role in instructions=, and do NOT hunt for a catalogue entry.

Example:
  spawn_job(agent_name='implementer',
                  agent_display_name='implementer', ...)

  Later in implementation:
  spawn_agent(agent='gil-implementer', instructions='...')  # gil- prefix!

Built-in Codex roles shadow unprefixed names — always use gil- prefix. Never use
agent='worker', agent='implementer', agent='tester', or any unprefixed built-in
name, and never instruct a generic worker to "act as" a GiljoAI agent.
If no gil-* agent resolves, do NOT stop: spawn Codex's DEFAULT subagent for that
job and state once:
  """
    + MISSING_AGENT_TEMPLATES_NOTICE
    + """
The instructions= parameter should contain ONLY:
  - The job_id
  - The MCP call: get_job_mission(job_id="...")
The agent_profile in that response handles everything else.

DO NOT invoke spawn_agent() during staging - this is planning reference only
""",
)

_CH3_CLAUDE = (
    "agent_name → the agent_profile in that job's get_job_mission response",
    """Claude Code CLI Note:
  - Task(subagent_type="general-purpose") for every agent: Claude Code's generic worker
  - agent_name binds the DB record to the job; the role arrives from the server
  - The Task instructions open with the agent's name and job_id, then get_job_mission""",
    """── YOUR PLATFORM: CLAUDE CODE CLI ─────────────────────────────────────────
Task tool syntax (IMPLEMENTATION PHASE ONLY - not during staging):
  Task(subagent_type="general-purpose",
       instructions="You are {agent_name} (job_id: {job_id}). First action: get_job_mission(job_id='{job_id}').")

WHERE THE ROLE COMES FROM: the server, not your disk. get_job_mission returns the
agent's full agent_profile (role, instructions, model/effort hints). There is no
agent file to install or look up: spawn Claude Code's generic worker and let it
fetch its own mission. agent_name only labels the job record.

Example:
  spawn_job(agent_name='implementer',
                  agent_display_name='implementer', ...)

  Later in implementation:
  Task(subagent_type="general-purpose",
       instructions="You are implementer (job_id: <job_id>). First action: get_job_mission(job_id='<job_id>').")

DO NOT invoke Task() during staging - this is planning reference only
""",
)

_CH3_GENERIC = (
    "agent_name → the agent_profile in that job's get_job_mission response",
    """Generic MCP Note:
  - Agent profiles are served by the MCP server, never installed as local files
  - Any MCP-connected coding tool can consume them — no per-tool export exists
  - agent_name is the key used across DB records and job orders""",
    """── YOUR PLATFORM: ANY MCP-CONNECTED AGENT ─────────────────────────────────
Each session is one job order. The user (or you, on behalf of the user) opens
a session, the operator pastes the thin prompt for that job_id, and the agent
in that session calls get_job_mission() to load its work. One job per
session — different sessions can run different CLI tools (Claude, Codex,
opencode) and still coordinate, because coordination is MCP-only.

CROSS-AGENT COORDINATION (MCP-ONLY):
  - spawn_job(...)          — request a NEW job order (a new terminal/agent)
  - post_to_thread(...)     — talk to a peer agent on your coordination thread
  - get_thread_history(...) — read your own inbox
  Never use a CLI's native subagent feature to spawn or talk to ANOTHER agent's
  job — those processes are invisible across terminals. Agents MAY use their
  CLI's own subagent feature for INTERNAL decomposition within their own job
  (a worker delegating a sub-step to a child process inside its own terminal),
  but cross-job coordination is MCP only.

PHASE HANDOFF: If a successor needs to read a previous agent's output, pass
predecessor_job_id=<prior_job_id> when calling spawn_job. The server reads the
predecessor's completion record and renders the appropriate context preamble
into the successor's mission. The id is the existing job_id returned by the
prior spawn_job — no new id type, just reuse what you already have.

MESSAGING: Always use agent_id UUIDs in to_participant (from spawn_job response).
Orchestrator's staging session ends when it calls complete_job() on its own
orchestrator job (CE-0026); a fresh execution is spawned when the user clicks
"Implement" in the dashboard.
""",
)

_CH3_SPAWN_BLOCKS: dict[str, tuple[str, str, str]] = {
    "codex": _CH3_CODEX,
    "claude-code": _CH3_CLAUDE,
}


def _ch3_generic_mcp_triple(preset: Platform | None) -> tuple[str, str, str]:
    role_source, platform_note, _ = _CH3_GENERIC
    shell_less = preset is not None and not preset.has_shell
    preset_display = preset.display_label if preset is not None else "Generic MCP"
    fallback = _CH3_GENERIC_MCP_SELF_ADOPT_CHAT if shell_less else _CH3_GENERIC_MCP_SELF_ADOPT
    ladder = render_capability_ladder(
        _CH3_GENERIC_MCP_PREFERRED,
        fallback,
        _CH3_GENERIC_MCP_FLOOR_LINE,
        preset_display,
    )
    execution_mode_block = (
        "── YOUR PLATFORM: ANY MCP-CONNECTED AGENT (generic_mcp) ─────────────────────\n"
        "Harness-agnostic mode: each session is one job order and coordination is\n"
        "MCP-only. Follow the rung that matches what your harness can do:\n\n"
        f"{ladder}\n"
    )
    return role_source, platform_note, execution_mode_block


def _build_ch3_spawning_rules(tool: str = "multi_terminal", preset: Platform | None = None) -> str:
    if tool in _CH3_SPAWN_BLOCKS:
        role_source, platform_note, execution_mode_block = _CH3_SPAWN_BLOCKS[tool]
    elif is_subagent_render(tool):
        role_source, platform_note, execution_mode_block = _ch3_generic_mcp_triple(preset)
    else:
        role_source, platform_note, execution_mode_block = _CH3_GENERIC

    note_mode_tail = (
        ""
        if is_subagent_render(tool)
        else " Multi-terminal mode gates on\nphase via the dashboard Play buttons; subagent modes do not."
    )

    return f"""════════════════════════════════════════════════════════════════════════════
                    CH3: AGENT SPAWNING RULES
════════════════════════════════════════════════════════════════════════════

{execution_mode_block}

PARAMETER REQUIREMENTS:

── agent_name (CRITICAL) ───────────────────────────────────────────────────
Use an agent_name EXACTLY as it appears in the agent_templates list in this
response — copy the agent_name field verbatim. It often equals the display_name
(e.g. 'implementer'); some templates differ. NEVER invent a name that is not in
the list. Role source: {role_source}.

── agent_display_name ──────────────────────────────────────────────────────
UI label only — implementer | tester | analyzer | documenter | reviewer.

── mission ─────────────────────────────────────────────────────────────────
Focused agent-specific instructions, 200-500 tokens target.

── phase (optional, ordering metadata) ────────────────────────────────────
Same phase number = parallel siblings. Higher phase number = waits on lower
phases. Pair with predecessor_job_id when a successor needs prior output
(server renders the preamble in multi_terminal mode; subagent modes splice
inline).

⚠ SUBAGENT-MODE NOTE: In Claude Code / Codex subagent execution
modes the server does NOT block higher-phase jobs from starting before
lower-phase jobs finish. The `phase` value is informational ordering
metadata — the orchestrator is responsible for spawning agents in phase
order and waiting on each phase before invoking the next (via Task() /
spawn_agent() / @-syntax invocation order).{note_mode_tail}

⚠ predecessor_job_id is REQUIRED for phase > 1 when the successor consumes
a prior agent's output. Empty string is rejected (ValidationError). Pass
the predecessor's job_id, not its agent_id.

{platform_note}

VERIFICATION AGENT DEFERRAL: tester/reviewer are NOT spawned in staging. In implementation,
after deliverable agents complete: call get_agent_result(job_id) for each, build the
verification mission from REAL artifacts (files, commits, APIs), then spawn_job. Skip
verification entirely for doc-only / analysis-only projects. The full implementation
sequence is spawn_job (mint the job_id + dashboard record) BEFORE launching the agent — in
EVERY mode, including subagent mode — never Agent/Task/@-syntax without a preceding spawn_job.

VALIDATE BEFORE SPAWNING: agent_name exists in agent_templates, project_id
correct, mission scoped to this agent. Recommended max 2-5 agents, 8 display_names.
"""


def _build_ch4_error_handling() -> str:
    return """════════════════════════════════════════════════════════════════════════════
                       CH4: ERROR HANDLING
════════════════════════════════════════════════════════════════════════════

COMMON ERRORS:

── MCP Connection Lost ─────────────────────────────────────────────────────
Tools not responding / timeouts. Abort staging; tell the user inline (staging-
phase set_agent_status is server-locked, 403 STAGING_LOCK, so the inline ask
IS the notification). Do NOT continue spawning agents.

── Invalid Agent Name ──────────────────────────────────────────────────────
spawn_job "agent not found" → re-check agent_name against agent_templates;
exact match, not display_name; mind case.

── Spawn Failure ───────────────────────────────────────────────────────────
spawn_job fails → tell the USER inline, do NOT continue; partial spawns create
incomplete teams. set_agent_status is locked during staging.

── Mission Too Large ───────────────────────────────────────────────────────
Mission >10K tokens → condense, reference vision docs instead of embedding.
Target <5K.

── Agent Templates Empty ──────────────────────────────────────────────────
agent_templates list empty → this product has no agents assigned. Work with
your harness default; do not block. Tell the user they can assign agents to
this product on the Agents screen.

── STATUS TRANSITIONS ──────────────────────────────────────────────────────

Staging phase (orchestrator only, project.staging_status != 'staging_complete'):
  waiting →[get_job_mission]→ working   working →[report_progress]→ working
  working →[complete_job]→ complete
  ⚠ set_agent_status is SERVER-LOCKED for the orchestrator during staging
    (403 STAGING_LOCK). Use the inline-ask + report_progress pattern instead —
    see "If Requirements Are Unclear" in your identity prompt.

Implementation phase (all agents, post-staging-complete):
  waiting →[get_job_mission]→ working   working →[report_progress]→ working
  working →[complete_job]→ complete     (a worker's last call; it never finalizes)
  complete →[finalize_job, orchestrator only, after review]→ closed
  working →[set_agent_status("blocked")]→ blocked
  working →[set_agent_status("idle")]→ idle
  working →[set_agent_status("sleeping")]→ sleeping
  idle / sleeping / blocked →[report_progress or any active MCP]→ working
  complete →[message received]→ blocked (auto, HO0827b)
  blocked →[resume_or_dismiss_job(action="resume" | "dismiss")]→ working | complete

Note: spawned non-orchestrator agents bypass the staging lock entirely.

GENERAL ERROR PROTOCOL:
1. Log error with context (agent_id, job_id).
2. Persist error state:
   - Implementation phase OR not the orchestrator → set_agent_status("blocked", reason).
   - Staging phase AND you are the orchestrator → tell the USER inline; set_agent_status
     is locked (403 STAGING_LOCK) until staging completes.
3. Do NOT continue workflow after critical errors. Wait for user intervention.

Severity: CRITICAL (MCP/DB lost) → abort. HIGH (spawn/agent-name) → stop and report.
MEDIUM (mission size) → log and continue. LOW (context hints) → continue.
"""


_REACTIVATION_SPAWN_BLOCKS: dict[str, str] = {
    "codex": """Reactivation Spawn — Codex CLI:
  spawn_agent(agent='gil-{role}', instructions='You are resuming a reactivated Giljo job. Call get_job_mission(job_id="{job_id}") immediately to load your mission and prior context.')
  Do NOT call spawn_job again — the job already exists.""",
    "multi_terminal": """Reactivation Spawn — Multi-Terminal:
  Tell the user: "Open a new session with your AI and paste this prompt for the {role} agent"
  Include in the prompt: "You are resuming job_id={job_id}. Call get_job_mission(job_id='{job_id}') to load your full context."
  Do NOT call spawn_job again — the job already exists.""",
    "claude-code": f"""Reactivation Spawn — Claude Code:
  Task(subagent_type="general-purpose", instructions='You are {{agent_name}}, resuming a reactivated Giljo job (job_id: {{job_id}}). First action: call mcp__{MCP_ALIAS}__get_job_mission(job_id="{{job_id}}") to load your mission and prior context.')
  Do NOT call spawn_job again — the job already exists.""",
}

_REACTIVATION_GENERIC = """Reactivation Spawn — your harness's own mechanism (subagent floor):
  Re-spawn the {role} agent using whatever spawn / delegate mechanism your harness provides
  (a Task tool, an agent spawner, an @-mention, a delegate command), seeded with:
  "You are resuming a reactivated Giljo job. Call get_job_mission(job_id='{job_id}') immediately
  to load your mission and prior context."
  If ANY spawn mechanism exists in your harness, using it is MANDATORY — do NOT ask the human to
  open a session. Only if your harness has NO spawn mechanism at all: SELF-ADOPT the {role} role and
  resume the job yourself in THIS session (get_job_mission → do the work → complete_job).
  Do NOT call spawn_job again — the job already exists."""


def _build_reactivation_spawn_block(tool: str) -> str:
    block = _REACTIVATION_SPAWN_BLOCKS.get(tool)
    if block is not None:
        return block
    if is_subagent_render(tool):
        return _REACTIVATION_GENERIC
    return _REACTIVATION_SPAWN_BLOCKS["multi_terminal"]


def _build_ch5_reference(
    project_id: str, orchestrator_id: str, tool: str = "multi_terminal", git_integration_enabled: bool = False
) -> str:
    return f"""════════════════════════════════════════════════════════════════════════════
                CH5: REFERENCE (Implementation Phase Only)
════════════════════════════════════════════════════════════════════════════

⚠️  NOTE: This chapter is for IMPLEMENTATION PHASE reference only.
   If you are in STAGING PHASE, you do NOT need this information.
   This content is provided so you can plan your execution strategy.

────────────────────────────────────────────────────────────────────────────

IMPLEMENTATION PHASE MONITORING:

When you (or a fresh orchestrator instance) enters implementation phase:

1. Retrieve execution plan via get_job_mission(job_id)
2. Follow coordination strategy you defined in Step 7
3. Coordinate handoffs between dependent agents
4. After dispatching agents: set_agent_status(job_id, status="idle", reason="Agents dispatched, monitoring")
5. If user wants auto-monitoring: set_agent_status(job_id, status="sleeping", wake_in_minutes=15)
   Warn user this increases token consumption. Sleep locally, then wake and run coordination loop.

COORDINATION PATTERNS:

Sequential Pattern:
  Spawn agent A → Wait for completion →
  Send handoff message (using agent_id UUID) → Spawn agent B → Repeat

Parallel Pattern:
  Spawn all agents → Check progress when user requests or when auto-monitoring →
  Coordinate as agents finish → Track completion states

Hybrid Pattern:
  Spawn parallel batch 1 → Wait for batch 1 complete →
  Send handoff messages (using agent_id UUIDs) → Spawn batch 2 → Repeat

MESSAGING RULE: UUID-ONLY ADDRESSING
- ALWAYS use agent_id UUIDs in post_to_thread(to_participant=...)
- Each spawn_job() returns agent_id - save these for messaging
- Omit to_participant for a broadcast to the whole thread
- NEVER use display names (e.g., "implementer") in to_participant

MANDATORY: Before calling complete_job():
- Ensure all agent TODO items are completed
- Call get_thread_history() on your coordination thread and process all pending messages
System rejects completion attempts with unread messages or incomplete TODOs.

────────────────────────────────────────────────────────────────────────────

WRITING 360 MEMORY (HARD CAPS — server-enforced):

When you write 360 memory entries via write_project_closeout()
or write_memory_entry(), the server enforces hard caps. Writes exceeding
these are REJECTED with structured errors — there is no silent truncation.

Rationale: future-you (or a fresh-session orchestrator) reads these.
Fat entries crowd out signal and burn tokens at staging. Tight entries
scale.

── HARD CAPS (server-enforced) ─────────────────────────────────────────────
- summary:        <= 1500 chars (2-3 sentence headline)
- key_outcomes:   <= 5 items x <= 250 chars each
- decisions_made: <= 5 items x <= 250 chars each
- deliverables:   <= 3 items x <= 100 chars each (drop-cap; field deprecated)
- tags:           <= 8 items, each from CONTROLLED_TAG_VOCABULARY

── CONTROLLED TAG VOCABULARY (16) ──────────────────────────────────────────
Change type (8): feature, bug-fix, refactor, perf, security, docs, test, chore
Domain    (7):  frontend, backend, database, api, infrastructure, ui-ux, integration
Operational(1): migration

Pick 1-3 from change-type AND 1-3 from domain. Use 'migration' for schema
changes. Anything outside this list is rejected. For deferred follow-ups,
create a task via create_task instead of tagging the memory entry.

DELIBERATELY EXCLUDED (do NOT request additions in passing):
- saas / ce (edition routing belongs in release metadata)
- deprecation / breaking-change / regression (collapse into refactor / bug-fix)
- hotfix / rollback (collapse into bug-fix; urgency is write-time signal)
- version strings, sprint codes (burnable cardinality)

── REJECTION ERROR SHAPE ───────────────────────────────────────────────────
When a write is rejected, you receive a structured error:
  {{
        "error":       "validation_failed",
    "field":       "summary",
    "actual_size": 1843,
    "max_size":    1500,
    "guidance":    "Trim to 2-3 sentence headline of what changed and why.
                    Detail belongs in commit messages."
  }}
For tag failures the payload also carries `invalid_tag` and `allowed`
(the full sorted vocabulary) so you do not need a second round-trip.
Read the guidance and re-trim. Do NOT retry with the same payload.

── WORKED EXAMPLES ─────────────────────────────────────────────────────────
GOOD (passes validator):
  summary:        "Fixed 360 memory write TypeError on optional commit
                   fields. Pydantic GitCommitEntry validator now coerces
                   None to 0 at the schema boundary."
  key_outcomes:   ["Validator coerces None->0", "3 regression tests added",
                   "Verified end-to-end via the MCP boundary test"]
  decisions_made: ["Used schema-boundary coercion vs runtime guards",
                   "Kept legacy entries unchanged"]
  deliverables:   []   <- empty is fine; field is deprecated
  tags:           ["bug-fix", "backend", "test"]

BAD (rejected — summary 1,200 chars, 6 outcomes, junk tags):
  summary:        "Today I worked on fixing the bug in the write_memory_entry
                   tool which had been causing TypeErrors for several days
                   and required investigating the call chain through ..."
                   [continues for 2000+ more chars] -> REJECTED summary>1500
  key_outcomes:   [...6 items...]                  -> REJECTED outcomes>5
  tags:           ["fixed", "added", "files",
                   "commits", "saas"]              -> REJECTED unknown tags

ORCHESTRATOR CLOSEOUT PAYLOAD GUIDANCE:
At closeout your own 360 entry must satisfy these caps. Pick tags from
the controlled vocabulary that reflect the project's nature -- e.g.
['refactor', 'perf', 'backend'] for a perf project; ['feature', 'frontend']
for a UI feature; ['migration', 'database'] for a schema change. Do NOT
embed sprint names, version numbers, or edition labels in tags.

────────────────────────────────────────────────────────────────────────────

COMPLETION PROTOCOL (After ALL agents finish their work):
{
        ""
        if not git_integration_enabled
        else '''
── STEP 0: Git Commit (Git Integration Enabled) ───────────────────────────
Before calling write_project_closeout: verify the project_path is a git
repository AND all changes are committed.

First, check whether the project_path is a git repo:
  cd <project_path> && git rev-parse --is-inside-work-tree

If the command succeeds (prints "true"), proceed:
  1. Run `git status` to review pending changes
  2. Stage deliverables: `git add` relevant files (never `git add -A`)
  3. Commit with a descriptive message: `git commit -m "<summary of project work>"`
  4. Record a TITLED git_commits entry (SHA alone is rejected): `git log --format='%H%x09%s%x09%an' -1`

If the command FAILS (project_path is not a git repo), STOP and ASK the user:
  "Git integration is enabled in your settings, but this project path
  (<project_path>) is not a git repository. Would you like me to run
  `git init` here so future closeouts can capture commit history, OR
  proceed without git for this project?"

  - User says "init it": run `git init && git add . && git commit -m "<msg>"`,
    then proceed with the SHA in git_commits.
  - User says "skip git for this project" (or similar): pass an empty list
    `git_commits=[]` to write_project_closeout. The server will
    accept it with a git_warning in the response (logged for visibility);
    the closeout succeeds.

Do NOT silently skip git on your own — ask the user. It is their machine,
their folder, their decision.
────────────────────────────────────────────────────────────────────────────
'''
    }
── STEP 1: Mark Complete ───────────────────────────────────────────────────
Call: complete_job(
          job_id='{orchestrator_id}',
          result={{"summary": "...", "artifacts": [...]}}
      )

IMPORTANT: Complete your own orchestrator job FIRST, before closing the project.
The server requires all agents (including orchestrator) to be complete before
project closeout.

── STEP 2: Close Project & Write 360 Memory ────────────────────────────────
Call: write_project_closeout(
          project_id='{project_id}',
          summary='2-3 paragraph mission accomplishment overview',
          key_outcomes=['Achievement 1', 'Achievement 2', ...],
          decisions_made=['Decision 1 + rationale', ...],
          tags=['<1-5 from the 16-tag controlled vocabulary above>']{
        ''',
          git_commits=[...]'''
        if git_integration_enabled
        else ""
    }
      )

REQUIRED: supply 1-5 tags from the 16-tag controlled vocabulary documented
above. The server validates them against CONTROLLED_TAG_VOCABULARY and
rejects unknown tags with a structured error (invalid_tag + allowed enum).
Omitting tags persists the entry with an empty tag list -- there is no
auto-extraction from prose.
{
        ""
        if git_integration_enabled
        else '''
Git integration is OFF for this product (user toggle in Connect Settings).
Do NOT pass git_commits — omit the parameter entirely.
Do NOT run `git log` or `git status`. The closeout will succeed without commit history.
'''
    }
CRITICAL: Auto-generate content from your knowledge.
          Never ask user to fill placeholders.

This atomically closes the project and writes 360 memory to the product timeline.

── STEP 3: User Guidance ──────────────────────────────────────────────────
Tell user: "Project complete. Use `/giljo` to create follow-ups or look up existing project/task state."

────────────────────────────────────────────────────────────────────────────

AGENT REACTIVATION PROTOCOL:

When a downstream agent reports an issue requiring rework from an already-completed
upstream agent, follow this sequence:

── STEP 1: Post a direct message to the completed agent's coordination thread ──
Call: post_to_thread(thread_id=<your coordination thread>, to_participant="<completed-agent-id>",
      content="REWORK_REQUIRED: <specific issue>", from_agent="{orchestrator_id}", requires_action=true)
This auto-blocks the completed agent (server-side).

── STEP 2: Reactivate the job ─────────────────────────────────────────────
Call: resume_or_dismiss_job(job_id="<completed-agent-job-id>", action="resume")
Transitions the agent from blocked→working and increments reactivation_count.

── STEP 3: Launch a fresh local agent for the same role ───────────────────
The original terminal/subagent may be gone — that is expected.
{_build_reactivation_spawn_block(tool)}

── STEP 4: Fresh agent resumes from server state ──────────────────────────
The fresh agent calls get_job_mission(job_id="...") and receives the full
durable state: mission, history, todos, results, outstanding messages.
It continues work from where the original left off.

Key principle: Local subagent processes are disposable. Giljo jobs are durable.
Reactivation targets the job_id, not the terminal session.

WHEN NOT TO REACTIVATE:
- Completed agent's work is fine and the issue is in a different agent → fix there
- Post-completion message is purely informational (no action needed)
  → call resume_or_dismiss_job(job_id="...", action="dismiss") to return agent to 'complete'
- Agent was decommissioned (failed/replaced) → spawn a new job instead

HANDLING POST-COMPLETION MESSAGES:

When a completed agent receives a message and gets auto-blocked:
1. Check get_thread_history(as_participant="<agent_id>") on the coordination thread for that agent's pending messages
2. Read the message content
3. If informational (another agent sharing results, no action needed):
   → Call resume_or_dismiss_job(job_id="...", action="dismiss") — agent returns to 'complete'
4. If it requires rework:
   → Follow the Reactivation Protocol above (Steps 1-4)

{_CLOSING_JOBS_REFERENCE}

────────────────────────────────────────────────────────────────────────────

END OF IMPLEMENTATION PHASE REFERENCE
"""


def _build_ch6_auto_checkin(interval: int = 10, *, for_conductor: bool = False) -> str:
    if for_conductor:
        return f"""════════════════════════════════════════════════════════════════════════════
          CH6: CHECK-IN CADENCE — CHAIN CONDUCTOR
════════════════════════════════════════════════════════════════════════════

You are the project-less conductor: you own no project_id, so your check-in
cadence is the ACCOUNT-LEVEL default, seeded here as {interval} minutes.
Every get_workflow_status(project_id=<P_i>) you make on the project you are
driving also returns checkin_cadence_minutes — treat that as the live value
(the developer can change it in Settings at any time; the live value wins
over this seed and over anything you remember from an earlier cycle).

Apply it to the chain-drive wait (STEP B of the AUTO-CONTINUE LOOP):

  ▸ WAKE-CAPABLE HARNESS — you can hold an MCP tool call open for ~45s
    (verified: Claude Code CLI). Between advance-gate polls, park on
    get_my_turn(agent_id="<your agent_id>", wait_seconds=45) instead of
    sleeping — it returns the moment a Hub message or baton lands for you.
    (No wait_seconds = answers at once = polling, not parked.) Still call
    get_workflow_status(project_id=<P_i>) at least every M minutes:
    ready_to_advance flips server-side WITHOUT a Hub post, so the wake
    signal alone will never tell you a project finished.
  ▸ NOT WAKE-CAPABLE — chat surfaces (claude.ai / chatgpt.com) can NEVER
    hold the call open; polling is their primary path, permanently. Sleep M
    minutes between polls, exactly as the chain-drive chapter's
    background-sleep instructions describe.

Status honesty: set_agent_status(status="sleeping", wake_on_signal=true)
while parked on the wake call; set_agent_status(status="sleeping",
wake_in_minutes=M) on a timed sleep. Neither re-invokes you — your own loop
(the wake call returning, or your sleep completing) is what wakes you.

────────────────────────────────────────────────────────────────────────────
"""
    return f"""════════════════════════════════════════════════════════════════════════════
          CH6: CHECK-IN PROTOCOL — MANDATORY EXECUTION
════════════════════════════════════════════════════════════════════════════

This is your coordination loop for when you have dispatched all specialist
agents and have no immediate coordination work remaining. Execute it every
cycle. Do NOT ask the user for confirmation.

FIRST, PICK YOUR WAIT MECHANISM (once per session):

  ▸ WAKE-CAPABLE HARNESS — you can hold an MCP tool call open for ~45s
    (verified: Claude Code CLI). Use PATH A. If unsure, try ONE
    get_my_turn(wait_seconds=45) call: a normal return (even wake_reason
    "timeout") means wake-capable; if the harness kills it, use PATH B.
  ▸ NOT WAKE-CAPABLE — chat surfaces (claude.ai / chatgpt.com) can NEVER
    hold the call open; polling is their primary path, permanently. Use
    PATH B (timed sleep).

╔══════════════════════════════════════════════════════════════════════════╗
║ THE LIVE-CADENCE RULE (BOTH PATHS)                                       ║
║                                                                          ║
║ The check-in cadence M is an account-level setting the developer can     ║
║ change AT ANY TIME (Settings → Notifications), and a per-project value   ║
║ may override it. Read M fresh from                                       ║
║ get_workflow_status(project_id=...) → checkin_cadence_minutes at the     ║
║ START of every cycle. Any number you remember from earlier (including    ║
║ the first-cycle seed of {interval} minutes) is NOT authoritative — the   ║
║ ONLY authoritative value is the one you just read.                       ║
╚══════════════════════════════════════════════════════════════════════════╝

PATH A — WAKE LOOP (wake-capable harness):
  1. set_agent_status(status="sleeping", wake_on_signal=true,
     reason="Waiting for Hub activity") — the dashboard then shows you as
     waiting for a wake signal rather than on a timed sleep.
  2. Call get_my_turn(agent_id="<your agent_id>", wait_seconds=45). It parks
     server-side (zero tokens while parked) and returns the moment a Hub
     message or baton lands for you. wait_seconds is what makes it PARK:
     omit it and the same tool answers at once.
  3. On woken=true: handle the delivered work — get_thread_history() on
     your coordination thread, resolve "blocked" agents, relay messages,
     spawn next-phase work — then report_progress() and re-enter step 2.
  4. On wake_reason="timeout": re-call it immediately. Keep count: once ~M
     minutes of consecutive timeouts have passed, run one full coordination
     pass anyway — get_workflow_status(project_id=...) + get_thread_history()
     + report_progress() — because agent STATUS changes (an agent going
     blocked or silent without posting) do NOT fire the wake signal.
  5. On wake_reason="waiter_limit": fall back to PATH B for this cycle.
  6. All agents complete → proceed to Closeout (Phase 3).

PATH B — TIMED SLEEP LOOP (everything else):
  1. Read M via the LIVE-CADENCE RULE. Compute the sleep duration AT THIS
     MOMENT: seconds = M * 60 — compute it yourself each cycle; never bake
     a fixed literal. (e.g. M=10 → 600, M=30 → 1800)
  2. Call set_agent_status(status="sleeping",
       wake_in_minutes=M,
       reason=f"Auto check-in: sleeping for {{M}} minutes")
  3. EXECUTE THE SLEEP COMMAND (IMMEDIATELY, NO CONFIRMATION):
     * PowerShell (Windows): Start-Sleep -Seconds <seconds>
     * Bash/Zsh (macOS/Linux): sleep <seconds>
     This blocks your terminal for M minutes to prevent unnecessary
     token consumption while agents work via the passive MCP server.

     ⚠ CLAUDE CODE NOTE: The Bash tool blocks `sleep N` when N ≥ 2 as the
     first command in the invocation. Use the `sleep 1 N` workaround —
     `sleep` sums numeric args, and the harness only inspects the first
     arg ("1", under threshold). Example: `sleep 1 <seconds> && echo woke`
     will sleep ~<seconds>s and pass. Applies to bash invocations only;
     `Start-Sleep -Seconds <seconds>` via PowerShell is unaffected.
  4. WAKE UP AND COORDINATE (also where an interrupted sleep resumes):
     a) get_thread_history() on your coordination thread — read all agent
        reports and developer messages
     b) Resolve any "blocked" agents, relay messages, spawn next-phase work
     c) report_progress() — update the project TODO list and status
  5. Agents still working → back to step 1 (re-read the live cadence).
     All agents complete → proceed to Closeout (Phase 3).

────────────────────────────────────────────────────────────────────────────
"""
