# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.platform_registry import Platform, giljo_invocation, is_subagent_render, task_list_phrase
from giljo_mcp.services.protocol_sections.orchestrator_body import render_capability_ladder


_PHASE1_STEP0_SHELL = r"""0. **ENVIRONMENT DETECTION**: probe once: `python -c "import os; print(os.environ.get('SHELL', os.environ.get('COMSPEC', 'unknown')))"`
   (no `python`: `echo $SHELL` / `echo %COMSPEC%`), then use that shell's syntax: `sleep N`,
   `Start-Sleep -Seconds N` or `timeout /t N /nobreak >nul`. Paths: your mission's `project_path`, not your terminal's."""


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


_GIT_HANDOFF_LINE = 'list every file you changed in `complete_job(result={"artifacts": [...]})`'
_GIT_MISSION_WINS_LINE = "If your mission gives a git instruction, the mission wins."


def _build_conditional_blocks(
    git_integration_enabled: bool,
    execution_mode: str,
    tool: str,
) -> tuple[str, str]:
    git_commit_block = ""
    if git_integration_enabled and is_subagent_render(execution_mode):
        git_commit_block = f"""
### Git (subagent mode): do NOT commit
You run inside your orchestrator's session and share its working tree. Do not stage,
commit, or push. Before calling `complete_job()`, {_GIT_HANDOFF_LINE};
the orchestrator stages them by name and commits once.
{_GIT_MISSION_WINS_LINE}
"""
    elif git_integration_enabled:
        git_commit_block = f"""
### Git Commit (REQUIRED - Git Integration Enabled)
Before calling `complete_job()`, commit your work:
1. Stage your changes: `git add` relevant files (never use `git add -A`)
2. Write a descriptive commit message summarizing your work
3. Include the commit SHA AND its title (not the SHA alone) in your
   completion result, so the orchestrator has enough to build a titled
   git_commits entry at closeout:
   `complete_job(job_id, result={{"summary": "...", "commits": ["<sha> <one-line commit title>"], "artifacts": [...]}})`
{_GIT_MISSION_WINS_LINE}
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

*Tool names below are bare; your MCP client may expose them under a prefix — call them by
the names your harness lists.*
{no_thread_banner}
### Phase 1: STARTUP
{phase1_step0}

1. This response is your mission (fetching it moved you to WORKING). **PROTOCOL CACHE:** a LATER
   `get_job_mission` passes this `protocol_etag`; `protocol_unchanged=true` means reuse the copy you have.
2. The server has joined you to your coordination thread. Read it and act on any message
   BEFORE starting work (a read says you are not on it? `join_thread` once, same ids):
   `get_thread_history(thread_id={thread_ref}, as_participant="{executor_id}", unread_only=true, mark_read=true)`
{phase1_step4}

### Phase 2: EXECUTION
At the pauses of a long job (not between a few small items), drain your messages and act on them:
   `get_thread_history(thread_id={thread_ref}, as_participant="{executor_id}", unread_only=true, mark_read=true)`

### Phase 3: PROGRESS REPORTING
Report the FULL list (your ONE TODO list, the one you send to report_progress):
   `report_progress(job_id="{job_id}", todo_items=[{{"content": "Task 1 description", "status": "completed"}}, ...])`
- `todo_items` is a FULL REPLACEMENT: every item, current status, every time (a shorter list is
  rejected); `todo_append` adds new items.
- Status values: "pending", "in_progress", "completed"; "skipped" for a step handed to a person or
  a follow-up task, its text starting "HANDOFF <TSK-id>:". Never mark done what did not happen.
- The dashboard reads only this list.
  A {todo_phrase} of your own is optional and never replaces it: do not mirror into one.

### Phase 4: COMPLETION
1. Every TODO item `completed` or handed off (`skipped`).
2. `complete_job(job_id="{job_id}", result={{"summary": "...", "artifacts": [...]}})`
   - `complete_job` is your LAST call (refused, naming the blockers, while TODOs are open or
     action-required messages unread: drain with the Phase 2 call, act, retry). Never call `finalize_job`:
     your orchestrator reviews your result and finalizes it. If it needs rework, it messages you
     and resumes your job.
**Follow-up work:** file it (`create_task`, or `create_project` if multi-step) and give your
orchestrator the ID; its closeout cites it as `OPEN <TSK-id>: ...`.
{git_commit_block}{giljo_block}
### Phase 5: ERROR HANDLING
- **Blocked** (unclear scope, a decision, an error):
  `set_agent_status(job_id="{job_id}", status="blocked", reason="BLOCKED: <reason>")`, then
  `post_to_thread(thread_id={thread_ref}, content="BLOCKER: <details>", from_agent="{executor_id}", to_participant="<orchestrator-agent-id-uuid>", requires_action=true)`.
  STOP; poll the `get_thread_history` call above every 15-20 s (up to 5 times); your next
  `report_progress` resumes you.
- **Requesting Broader Context:** the same post with `content="REQUEST_CONTEXT: <specific need>"`,
  then wait for the reply on the thread; never guess at a major ambiguity.
- **Reactivated:** `get_job_mission` again, drain the thread (the reason is there), continue from
  your prior state, `complete_job` again.
- **Out of context:** post `HANDOVER: COMPLETED <...>. IN-PROGRESS <...>. NEXT-STEPS <...>. BLOCKERS <...>`
  to the orchestrator (requires_action=true), set yourself blocked, and STOP: no `complete_job`,
  no memory write.
- **360 memory:** other entry types only when your mission assigns them; `project_completion` is
  orchestrator-only.
---
**Your Identifiers:** job_id `{job_id}`; agent_id `{executor_id}` (your `from_agent` and
`as_participant`). Message prefixes: BLOCKER:, PROGRESS:, COMPLETE:, READY:, REQUEST_CONTEXT:.
MCP tools are NATIVE tool calls: never curl, HTTP, or SDK calls.
"""
    return protocol_framing + body
