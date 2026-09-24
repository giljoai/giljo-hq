# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.platform_registry import Platform, giljo_invocation, task_list_phrase
from giljo_mcp.services.protocol_sections.orchestrator_body import render_capability_ladder


_PHASE1_STEP0_SHELL = r"""0. **ENVIRONMENT DETECTION**:
   Detect your shell environment before executing tasks:
   Call: `python -c "import os; print(os.environ.get('SHELL', os.environ.get('COMSPEC', 'unknown')))"`
   If `python` is not on PATH: fall back to `echo $SHELL` (POSIX) / `echo %COMSPEC%` (Windows).
   This detects the **actual shell** (bash, zsh, powershell, cmd), not just the OS.
   Adapt commands to the detected shell:
   - If shell contains "bash" or "zsh" (includes Git Bash on Windows):
     Sleep: `sleep N` | Clear: `clear` | Paths: use `/`
   - If shell contains "powershell" or "pwsh":
     Sleep: `Start-Sleep -Seconds N` | Clear: `cls` | Paths: use `\` or `/`
   - If shell contains "cmd":
     Sleep: `timeout /t N /nobreak >nul` | Clear: `cls` | Paths: use `\`
   - Default (unknown): use `sleep N` (works in most environments)

   **CONTEXT AWARENESS**: Your mission contains authoritative values including `project_path`.
   When creating files or referencing directories, use context-provided paths.
   Do NOT hardcode paths observed in your terminal environment."""


def _phase1_step0(preset: Platform | None) -> str:
    if preset is None or preset.has_shell:
        return _PHASE1_STEP0_SHELL
    return render_capability_ladder(
        preferred=(
            "0. **NO SHELL (chat session)**: this session has no shell or OS terminal. Do NOT run\n"
            "   the `python -c ...` shell probe, a shell `sleep`, or any OS command. Planning,\n"
            "   analysis, review, and PM work proceed normally here. For any task that must EXECUTE\n"
            "   code or shell commands, do that work in a session that HAS an execution environment\n"
            "   — never fabricate command output. Time waits: there is no `sleep`; just re-check\n"
            "   state the next time you act."
        ),
        fallback=(
            "Do the non-shell parts of your task here, then report the shell-dependent remainder to\n"
            "your orchestrator (a decision/blocker message) rather than guessing at command output."
        ),
        floor_user_line=(
            "This job needs a coding environment with a shell — run it in a session that has one "
            "(a terminal, desktop, or web coding tab)."
        ),
        preset_display=preset.display_label,
    )


def _build_conditional_blocks(
    git_integration_enabled: bool,
    execution_mode: str,
    tool: str,
) -> tuple[str, str]:
    git_commit_block = ""
    if git_integration_enabled:
        git_commit_block = """
### Git Commit (REQUIRED - Git Integration Enabled)
Before calling `complete_job()`, commit your work:
1. Stage your changes: `git add` relevant files (never use `git add -A`)
2. Write a descriptive commit message summarizing your work
3. Include the commit SHA AND its title (not the SHA alone) in your
   completion result, so the orchestrator has enough to build a titled
   git_commits entry at closeout:
   `complete_job(job_id, result={"summary": "...", "commits": ["<sha> <one-line commit title>"], "artifacts": [...]})`
"""

    giljo_block = ""
    if execution_mode == "multi_terminal":
        giljo_cmd = giljo_invocation(tool)
        giljo_block = f"""
### User Guidance (Multi-Terminal)
After completing your work, tell the user:
"My work is complete. If you discovered technical debt or follow-up work, or you want to
look up an existing project or task, ask me to use {giljo_cmd} (it routes both create and read)."
"""

    return git_commit_block, giljo_block


def _build_worker_protocol_body(
    job_id: str,
    tenant_key: str,
    executor_id: str,
    job_type: str,
    phase1_step4: str,
    git_commit_block: str,
    giljo_block: str,
    protocol_framing: str,
    preset: Platform | None = None,
    comm_thread_id: str | None = None,
    tool: str = "multi_terminal",
) -> str:
    phase1_step0 = _phase1_step0(preset)
    todo_phrase = task_list_phrase(tool)
    thread_ref = f'"{comm_thread_id}"' if comm_thread_id else '"<none>"'
    no_thread_banner = (
        ""
        if comm_thread_id
        else (
            "\n**NO COORDINATION THREAD BOUND:** this job has no project, so no Hub thread "
            "was resolved for it. Skip every `join_thread` / `get_thread_history` / "
            '`post_to_thread` call below (they show `"<none>"` for the missing thread id) and '
            'reach your orchestrator only via `set_agent_status(status="blocked", ...)`.\n'
        )
    )

    body = rf"""## Agent Lifecycle Protocol (5 Phases)

*Tool names below are bare; your MCP client may expose them under a prefix (e.g.
`mcp__<server>__get_job_mission`) — call them by the names your harness lists.*
{no_thread_banner}
### Phase 1: STARTUP (BEFORE ANY WORK)
{phase1_step0}

1. Call `get_job_mission(job_id="{job_id}")` - Get mission (auto-transitions to WORKING)
   - **PROTOCOL CACHE (saves ~15-50KB on a re-fetch):** the response includes a `protocol_etag`.
     Remember it. On any LATER `get_job_mission` this session (a reactivation, a context refresh),
     pass `protocol_etag=<that value>`. If the response comes back with `protocol_unchanged=true`,
     your `agent_identity` + `full_protocol` are unchanged (returned null by design) — reuse the
     copy you already have instead of re-reading them.
2. Call `join_thread(thread_id={thread_ref}, agent_id="{executor_id}")` - Join your project's
   coordination thread (collision-safe: re-joining an already-joined thread is a no-op)
3. Call `get_thread_history(thread_id={thread_ref}, as_participant="{executor_id}", unread_only=true, mark_read=true)` - Check for instructions
4. Review any messages and incorporate feedback BEFORE starting work

{phase1_step4}

### Phase 2: EXECUTION
Execute your assigned tasks (your {todo_phrase}, created in Phase 1):
- Maintain focus on mission objectives
- Update todos as you progress
- **MESSAGE CHECK**: Call `get_thread_history()` after completing each item on your {todo_phrase}
  - Full call: `get_thread_history(thread_id={thread_ref}, as_participant="{executor_id}", unread_only=true, mark_read=true)`
  - If any messages are returned: Process them BEFORE continuing
  - If none are returned: Safe to proceed

### Phase 3: PROGRESS REPORTING (After each milestone)
1. Call `get_thread_history()` - MANDATORY before reporting
   - Full call: `get_thread_history(thread_id={thread_ref}, as_participant="{executor_id}", unread_only=true, mark_read=true)`
2. Process ALL pending messages
3. Call `report_progress()` with your todo_items:

   report_progress(
       job_id="{job_id}",
       todo_items=[
           {{{{"content": "Task 1 description", "status": "completed"}}}},
           {{{{"content": "Task 2 description", "status": "in_progress"}}}},
           {{{{"content": "Task 3 description", "status": "pending"}}}}
       ]
   )

**Backend automatically calculates percent and step counts from your list.**
Status values: "pending", "in_progress", "completed"

**WARNING: todo_items is a FULL REPLACEMENT.** Always include ALL prior items with their
current statuses. Omitting completed items will be REJECTED by the server (regression guard).
Use todo_append to add genuinely new items discovered mid-work.

### CRITICAL: Sync your {todo_phrase} with MCP Progress

Every time you update a task's status on your {todo_phrase} (mark item complete or in_progress),
IMMEDIATELY call report_progress() with your updated todo_items list.

The todo_items array appears in the Plan/TODOs tab of the dashboard.
Do NOT skip this step - the backend cannot see your {todo_phrase} updates.

### BACKEND MONITORING ACTIVE
The backend monitors report_progress() calls. If todo_items is missing:
- You will receive a WARNING in the response
- Warnings are throttled (1 per 5 minutes per job)
- Dashboard cannot display your progress without todo_items

**MESSAGE HANDLING (CRITICAL):**
- ALWAYS use `get_thread_history(..., mark_read=true)` to drain your unread posts (it marks
  the returned posts read and advances your cursor)
- `get_thread_history(...)` WITHOUT `mark_read` is the read-only inspection — posts stay
  unread (use for debugging only)

### Phase 4: COMPLETION
Before calling `complete_job()`, you MUST verify:
1. All TODO items completed (your {todo_phrase} is fully marked completed)
2. All messages read (queue empty after `get_thread_history(..., mark_read=true)`)

**Follow-up work:** When you finish work and a follow-up is needed, create a task via `create_task` — or a project via `create_project` if it's multi-step — and cite the returned ID in `decisions_made` when you call `write_project_closeout`.

Final steps:
1. Call `get_thread_history()` - Final message check
   - Full call: `get_thread_history(thread_id={thread_ref}, as_participant="{executor_id}", unread_only=true, mark_read=true)`
2. Process any pending messages - ensure queue is empty
3. Call `complete_job()` - ONLY after TODOs are complete and queue is empty
   - Full call: `complete_job(job_id="{job_id}", result={{"summary": "...", "artifacts": [...]}})`

If you call `complete_job()` without meeting these requirements:
- System will REJECT your completion
- Response will list specific blockers (unread messages, incomplete TODOs)

{git_commit_block}{giljo_block}
### Phase 5: ERROR HANDLING & BLOCKED STATUS

**To mark yourself BLOCKED** (unclear requirements, waiting for clarification):
1. Call `set_agent_status(job_id="{job_id}", status="blocked", reason="BLOCKED: <reason>")`
   - Sets status to "blocked" and stores block_reason
2. Post to your coordination thread addressed to the orchestrator (use its agent_id UUID from YOUR TEAM table):
   - `post_to_thread(thread_id={thread_ref}, content="BLOCKER: <details>", from_agent="{executor_id}", to_participant="<orchestrator-agent-id-uuid>", requires_action=true)`
   - ALWAYS use the orchestrator's agent_id UUID, NEVER the display name "orchestrator"
3. STOP work and poll for response (use longer intervals while blocked — 15-20 seconds between polls, up to 5 attempts):
   - `get_thread_history(thread_id={thread_ref}, as_participant="{executor_id}", unread_only=true, mark_read=true)`

**To resume from BLOCKED**:
1. After receiving guidance, call `report_progress()` with your updated TODO list:
   - `report_progress(job_id="{job_id}", todo_items=[...])`
   - This automatically transitions your status from "blocked" back to "working"
2. Continue execution with Phase 2

**Use BLOCKED for**: Unclear requirements, missing context, waiting for decisions, unrecoverable errors (all errors use blocked status)

## If You Are Reactivated

If you receive context indicating you are resuming a previously completed job:
1. Call `get_job_mission(job_id="...")` to load your full prior context
2. Read any new messages via `get_thread_history(thread_id={thread_ref}, as_participant="{executor_id}", unread_only=true, mark_read=true)`
   — the reactivation reason surfaces on this cursor read
3. Continue work from your prior state — do not restart from scratch
4. When done, call `complete_job()` again with updated results

## Handover on Context Exhaustion

If you run out of context before completing, **DO NOT write 360 memory**.
Memory writes are orchestrator-only — both for normal completion and for handovers.
Your job is to send the orchestrator everything it needs to decide what happens next.

1. Post a HANDOVER message to the orchestrator (use the orchestrator's agent_id UUID
   listed in YOUR TEAM table at the top of your mission):
   - `post_to_thread(thread_id={thread_ref},`
     `content="HANDOVER: Context exhausted. COMPLETED: <what you finished>.`
     `IN-PROGRESS: <what was active and the stopping point>. NEXT-STEPS:`
     `<what a successor needs to do>. BLOCKERS: <any known blockers>.",`
     `from_agent="{executor_id}", to_participant="<orchestrator-agent-id-uuid>",`
     `requires_action=true)`
2. Set yourself BLOCKED so the orchestrator knows you're waiting:
   - `set_agent_status(job_id="{job_id}", status="blocked",`
     `reason="BLOCKED: context exhausted, handover sent to orchestrator")`
3. STOP. Do NOT call `complete_job()` and do NOT call `write_memory_entry()`.
   The orchestrator will decide whether to spawn a successor (preserving your
   job_id) or write a handover memory entry itself.

Workers may write `baseline`, `decision`, `architecture`, and `discovery` entries
when their mission explicitly assigns them. Workers MUST NOT write `project_completion`
entries — the tool will reject those with `ORCHESTRATOR_ONLY_ENTRY_TYPE`. To record
that, send a HANDOVER or progress message to your orchestrator with the content.

Concrete examples (one per category):
- Worker `baseline`: `write_memory_entry(entry_type="baseline", ...)` after seeding
  the architecture snapshot from a frozen reference doc.
- Worker `decision`: `write_memory_entry(entry_type="decision", ...)` to record
  "chose a caching layer over a separate audit table — rationale: latency budget".
- Worker `architecture`: `write_memory_entry(entry_type="architecture", ...)` to
  capture a new layered boundary (e.g. a queue introduced between two services).
- Worker `discovery`: `write_memory_entry(entry_type="discovery", ...)` for a
  surprising finding (e.g. "a startup-ordering gotcha causes a race during boot").
- Orchestrator deferred work: create a follow-up task via `create_task` (or a project via `create_project` for multi-step work) and cite the returned ID in `decisions_made` at closeout.

Use `discovery` for one-off findings worth remembering.
---
**Your Identifiers:**
- job_id (work order): `{job_id}` - Use for mission, progress, completion
- agent_id (executor): `{executor_id}` - Use for messages (from_agent and as_participant)

**MESSAGING RULE: UUID-ONLY ADDRESSING**
- ALWAYS use the agent_id UUID in `to_participant` (from YOUR TEAM table in mission header)
- NEVER use display names like "orchestrator" or "implementer" in `to_participant`
- Omit `to_participant` to broadcast to every participant on the thread
- Your `from_agent` is always your agent_id: `{executor_id}`

**Message Prefixes:**
- **BLOCKER:** - Urgent, needs immediate help (triggers blocked status)
- **PROGRESS:** - Milestone update to orchestrator
- **COMPLETE:** - Work finished notification
- **READY:** - Available for new work
- **REQUEST_CONTEXT:** - Need broader project context from orchestrator

**Requesting Broader Context:**
If your mission references undefined entities, has unclear dependencies, or ambiguous scope:
1. Post: `post_to_thread(thread_id={thread_ref}, content="REQUEST_CONTEXT: <specific need>", from_agent="{executor_id}", to_participant="<orchestrator-uuid>", requires_action=true)`
2. Be specific (e.g., "REQUEST_CONTEXT: What database schema is used for user auth?")
3. Wait for response via `get_thread_history(thread_id={thread_ref}, as_participant="{executor_id}", unread_only=true, mark_read=true)`
4. Do NOT guess at major ambiguities - ask first

**When to Check Messages:**
- Phase 1 (STARTUP): Before starting work
- Phase 2 (EXECUTION): After each item on your {todo_phrase}
- Phase 3 (PROGRESS): Before reporting progress
- Phase 4 (COMPLETION): Before calling complete_job()

**CRITICAL: MCP tools are NATIVE tool calls. Use them like Read/Write/Bash.**
**Do NOT use curl, HTTP, or SDK calls.**
"""  # noqa: S608 — prose protocol template, not SQL
    return protocol_framing + body
