# Giljo HQ: Tools Reference

*Last updated: 2026-09-02*

## Overview

Giljo HQ, a GiljoAI product, registers **49 tools**. Two of them —
`launch_implementation` and `decide_approval` — respect your tenant's approval mode, so
they may not be served to every session; see Settings. Several older tool names have
been retired and are no longer registered — only the final names below are. Every tool requires a
valid API key passed as a Bearer token. Tenant isolation is enforced server-side; agents
cannot cross tenant boundaries.

Tool names match the exact MCP registrations at the time of the date above. The MCP
registry itself is roster-locked by
`tests/unit/test_be6042d_mcp_tool_registry_surface.py`: no tool can be added, renamed,
dropped, or change a parameter or scope without CI turning red. That lock compares the
live registry against a baseline held inside the test, **not** against this page, so the
counts and entries below are maintained by hand.

### Scopes

Every tool carries one of three permission scopes:

| Scope | Meaning | Count |
|-------|---------|-------|
| `mcp:read` | Read-only — fetches data, never mutates state. | 13 |
| `mcp:write` | Mutating writes performed by a human/dashboard-driven flow. | 10 |
| `mcp:agent` | Agent-lifecycle operations used by orchestrators and specialist agents. | 26 |
| **Total** | | **49** |

Tools are organized by functional category below; each entry lists its scope.

---

## Discovery & Health

### health_check `mcp:read`

**Purpose:** Check MCP server health and connectivity. Tenant-independent.

**Parameters:** None.

---

### get_giljo_guide `mcp:read`

**Purpose:** Return the GiljoAI cross-tool guide — the routing/judgment layer for the
project and task tools: project-vs-task selection, the chain convention (shared
`series_number` + a/b/c suffixes), the mandatory Edition Scope, read-vs-write routing,
and the staging → human-gate → implement lifecycle. A fresh agent should call this once
before creating or reading projects and tasks.

**Parameters:** None.

---

## Project Management

### create_project `mcp:write`

**Purpose:** Create a new project, bound by default to the active product. `project_type`
plus `series_number` form a taxonomy serial such as `FE-0001`; the `suffix` enables
chain steps (a/b/c). Unknown `project_type` values are rejected with the list of valid
types. The project is created inactive; activate it from the dashboard. The response
names the product the project landed on.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | Yes | Project name. |
| description | str | Yes | Human-written project description (user requirements). Must state `**Edition Scope:**`. |
| project_type | str | No | Taxonomy type abbreviation (e.g. `FE`, `BE`, `INF`). Must match a configured type; the reserved `TSK` type is task-only and never valid here. |
| series_number | int | No | Sequential number within the type series (0 = auto-assign). |
| suffix | str | No | Chain-step suffix (e.g. `a`, `b`, `c`) sharing one `series_number`. |
| bootstrap_template_vars | dict | No | Optional template variables for project bootstrap. Consumed only for `CTX` project types; ignored otherwise. |
| product_id | str | No | Product UUID to bind the project to. Omit to use the active product — but the active product is shared, mutable state, so pass this explicitly when you know your product: another session, or the user switching products in the dashboard, changes the active product mid-session and an omitted `product_id` follows that change. |

---

### update_project `mcp:write`

**Purpose:** Update project metadata (name, description, status, type, series
positioning). Omitted fields remain unchanged.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the project to update. |
| name | str | No | New project name. |
| description | str | No | New description. |
| status | str | No | New lifecycle status. Setting `completed` on a solo project runs the full archive lifecycle (deactivation, terminal-state selection from early_termination, completed_at stamping, agent closure) — the same sequence as the dashboard's Archive button. |
| project_type | str | No | New taxonomy type abbreviation. |
| series_number | int | No | New series number. |
| suffix | str | No | New chain-step suffix. |

---

### list_projects `mcp:read`

**Purpose:** List projects for the active product with server-side filtering, search,
and pagination. By default returns only active-lifecycle projects (excludes
completed/cancelled) in summary form. Prefer `mode` (`triage`/`planning`/`audit`/
`forensic`) over numeric `depth`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| status | str | No | `""` | Filter by status. Single (`"active"`) or comma-separated. When set, `include_completed` is ignored. |
| project_type | str | No | `""` | Filter by taxonomy type, single or comma-separated (`"BE,FE"`). |
| taxonomy_alias_prefix | str | No | `""` | Prefix-match against taxonomy alias (e.g. `"BE-50"`). |
| created_after / created_before | str | No | `""` | ISO-8601 bounds on creation time. |
| completed_after / completed_before | str | No | `""` | ISO-8601 bounds on completion time. |
| include_completed | bool | No | `false` | Include archived (completed/cancelled/terminated/deleted) projects. Ignored when `status` is set. |
| include_superseded | bool | No | `false` | Include superseded projects (work replaced by a successor). Hidden by default even under `include_completed=true`; an explicit `status="superseded"` also surfaces them. |
| hidden | str | No | `""` | Tri-state: `"true"` only hidden, `"false"` exclude hidden, `""` no filter. |
| mode | str | No | `""` | **Preferred.** `triage` / `planning` / `audit` / `forensic`. Overrides `depth` and `summary_only`. |
| memory_limit | int | No | `5` | Caps trailing 360-memory entries per project in audit mode (max 50). |
| summary_only | bool | No | `true` | Back-compat. Ignored when `mode` is supplied. |
| depth | int | No | `0` | Back-compat numeric detail 0-3. Prefer `mode`. |
| status_filter | str | No | `""` | Legacy. Prefer `status`. `"all"` implies `include_completed=true`. A genuine conflict with `status` (different effective meaning) is refused, naming both values. |
| query | str | No | `""` | Case-insensitive substring search against name, id, description, `project_alias`, and `taxonomy_alias` (e.g. `"oauth"`, `"BE-1042"`). Max 200 characters. Empty = no search. |
| limit | int | No | `50` | Max rows to return (max `500`). `0` = use the default. A value above the max is **rejected**, not silently clamped. A response cut by this bound sets `truncated=true`; read `counts.matched` for how many rows the filters actually match. |
| cursor | str | No | `""` | Opaque continuation token from a previous response's `truncation.next_cursor`. Pass it back **with the same filters** to keep walking; a filter change mid-walk is refused rather than silently answered from the wrong set. Keep walking until a response comes back `truncated=false` — every project is then returned exactly once. Changing `limit` or `mode` mid-walk is fine. |

**Modes:** `triage` (id/name/status/type/dates — pick a project) · `planning`
(+ description, mission, agent counts) · `audit` (+ memory headlines + agent summaries)
· `forensic` (+ full memory bodies, agent results, message history).

**Response shape:** every response carries a `counts` block — `matched` (rows your
filters match, board-wide) and, when walking with a cursor, `remaining` (still ahead of
your cursor). A response cut by `limit` sets `truncated=true` with a `truncation` block
naming the reason and the fix (raise `limit`, narrow filters, or pass `cursor`). When a
type/status filter comes back empty because matching projects exist but are hidden by
the default view, the response says so and names the exact filter to pass to reveal
them — it never reads as "none exist."

---

### update_project_mission `mcp:agent`

**Purpose:** Save the orchestrator's mission plan to the database. The `description`
holds user requirements (input); `mission` holds the orchestrator's plan (output).
Triggers a `project:mission_updated` WebSocket event.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the project to update. |
| mission | str | Yes | Orchestrator's execution plan. |

---

### diagnose_project_state `mcp:read`

**Purpose:** Read-only orchestrator self-healing diagnostic. Reports a project's
lifecycle status, gates, agent counts, closeout readiness, and any stuck conditions,
with suggested next actions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the project to diagnose. |

---

## Project Lifecycle (staging → implement)

### stage_project `mcp:agent`

**Purpose:** Drive the staging endpoint for a project and return the orchestrator launch
prompt (orchestrator/agent ids, prompt, token estimate) for the chosen execution mode.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the project to stage. |
| mode | str | No | Execution mode (ADR-010). 2 canonical values: `multi_terminal` (default, one terminal per agent) / `subagent` (one orchestrator session drives the workers). Plus 2 short per-CLI hint aliases — `claude`, `codex` — each collapsing to `subagent` plus a harness hint for the staging prose flavor. |

---

### get_staging_instructions `mcp:agent`

**Purpose:** Fetch the orchestrator's staging directives — project description
(user requirements), prioritized context fields, and an `agent_templates` list for
discovering specialists. Called by the orchestrator at project start. Reclassified
from `mcp:read` to `mcp:agent` (BE-6167): its self-close path can write
`project.status=COMPLETED`, a terminal orchestration mutation a read-scoped token
must not reach.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The orchestrator's own job ID. |
| harness | str | No | Optional session harness preset: `web_sandbox`\|`desktop_app`\|`chat` (omit for a terminal-capable CLI). |

---

### get_implementation_prompt `mcp:agent`

**Purpose:** Fetch the prompt that starts implementation on a project that is staged and
has been approved to start. This RETURNS a prompt; it does not run anything. Two things
must already be true: the project finished staging, and a human approved the start (the
dashboard's Implement button, or `launch_implementation`). If they are not, you get a
structured refusal naming the exact next step — there is no bypass, the approval is
deliberate. (Renamed from `implement_project`, which never implemented anything.)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | The project to fetch the implementation prompt for. |

---

### launch_implementation `mcp:agent`

**Purpose:** Release the implementation-phase gate for a staged project from the CLI
(the CLI door of the two-door implement gate). Idempotent; stamps
`implementation_launched_at`. Kept out of the orchestrator auto-tool bundle so an agent
cannot self-unlock.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the staged project to release. |

---

### link_projects `mcp:agent`

**Purpose:** Link two or more existing projects into one ordered run under a shared goal, from a headless agent — the MCP equivalent of the dashboard "Run Sequential" button. Validates the projects (each must exist for the tenant, be chainable, and form a group of >= 2 distinct members), creates the durable `sequence_run`, and the calling session drives it. Advancement is automatic: a member finished through either door is recorded and the next becomes ready server-side, visible on `get_workflow_status(project_id).ready_to_advance`. Bad input returns a structured `{success:false, error:CODE}` rejection (`PROJECT_NOT_FOUND` / `PROJECT_NOT_CHAINABLE` / `RESOLVED_ORDER_MISMATCH` / `CHAIN_TOO_SMALL`).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_ids | list[str] | Yes | The projects to link, as ids, in the order they should run (>= 2 distinct). Capped at the server's MAX_SEQUENCE_PROJECTS. |
| execution_mode | str | No | How the work runs: `subagent` (this session drives the worker agents itself — the usual choice) or `multi_terminal` (a separate terminal per agent). The legacy per-CLI tokens are still accepted as aliases and fold onto `subagent`. |
| mission | str | No | The shared goal for the whole group. Optional — pass it now, or write it later once the work is planned. |
| ordered | list[str] | No | Only if the run order differs from `project_ids`: the same ids, rearranged. |

---

### unlink_projects `mcp:agent`

**Purpose:** Abandon a linked group part-way — the projects that have not run yet are released and the group stops; ones already finished stay finished. Byte-identical to the dashboard's Terminate control (both reach `SequenceRunService.release(mode="cancel")`).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| run_id | str | Yes | The id of the linked group, returned by `link_projects`. |

---

### start_chain_run — RETIRED, NO LONGER REGISTERED

**Purpose:** Retired in favour of `link_projects` / `unlink_projects`. This name is no
longer registered and returns "tool not found"; it is listed here as a pointer for
anyone holding an older prompt. The `mark_reviewed` action is no longer on the agent
surface — the dashboard review pane keeps its REST door, and a headlessly finished
member is recorded automatically.

---

### write_project_closeout `mcp:agent`

**Purpose:** Close a project and write a 360 Memory entry with a sequential history
entry, called by the orchestrator at completion. All agents must be
complete/closed/decommissioned first. Triggers a `product_memory_updated` WebSocket event.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the project to close. |
| summary | str | Yes | Narrative summary of what was accomplished. |
| key_outcomes | list[str] | Yes | Concrete outcomes delivered. |
| decisions_made | list[str] | Yes | Architectural/design decisions made (cite any deferred task/project IDs). |
| git_commits | list[dict] | No | Commit records associated with the project. |
| tags | list[str] | No | Classification tags. |
| force | bool | No | Force-close: auto-decommission remaining agents before closing. Use only when a prior `CLOSEOUT_BLOCKED` response says so (e.g. a leftover "waiting" orchestrator after work ran outside a staged session). Refused while the calling orchestrator itself is still active; a specialist still in flight — including one marked "silent" — is decommissioned (recorded as failed/replaced/abandoned). Do not use it to retire an agent whose work you accepted — `complete_job` then `finalize_job` that agent instead. Default `false`. |

---

## Tasks

### create_task `mcp:write`

**Purpose:** Create a task (a single-step deferral / technical debt item), bound by
default to the active product. Every task is tagged `TSK` (a `taxonomy_alias` like
`TSK-0067`, auto-assigned from the counter shared with projects) — `task_type` is
accepted for backward compatibility only and has no effect.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| title | str | Yes | Task title. |
| description | str | Yes | Detailed task description. |
| priority | str | No | `low` / `medium` / `high` / `critical`. Default `medium`. |
| task_type | str | No | Ignored — kept for backward compatibility. Every task is auto-tagged `TSK`; no other type is ever assigned. |
| assigned_to | str | No | Agent or user to assign the task to. |
| product_id | str | No | Product UUID to bind the task to. Omit to use the active product — but the active product is shared, mutable state, so pass this explicitly when you know your product: another session, or the user switching products in the dashboard, changes the active product mid-session and an omitted `product_id` follows that change. A `product_id` that does not belong to your account is rejected outright; it never silently falls back to the active product. |

---

### update_task `mcp:write`

**Purpose:** Update task metadata (title, description, status, priority, due date,
hidden flag), or promote the task to a project. Omitted fields remain unchanged; the
task type is immutable. To **complete** a task, set `status=completed` (this stamps
`completed_at`); pass `completion_notes` to append an audit-trail entry as it completes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | str | Yes | ID of the task to update. |
| title | str | No | New title. Alongside `convert_to_project=true`, names the new project instead. |
| description | str | No | New description. |
| status | str | No | `pending` / `in_progress` / `completed` / `blocked` / `cancelled`. |
| priority | str | No | `low` / `medium` / `high` / `critical`. |
| task_type | str | No | Ignored — the task type is immutable (`TSK`). Any value passed is not written. |
| due_date | str | No | ISO-8601 due date. |
| hidden | str | No | UI declutter flag. |
| completion_notes | str | No | Note appended to the audit trail when `status=completed` (folds in the retired `complete_task` tool); a no-op otherwise. |
| convert_to_project | bool | No | Promote this task to a project in one atomic step — the same conversion the dashboard's task-to-project wizard runs. A project is created from the task, any subtasks and roadmap card re-point to it at the same roadmap position, and **the task row is deleted** (its `task_id` stops resolving). The new project is **inactive and untyped** — tag it afterward with `update_project(project_id, project_type=...)`. It lands on the task's own product, not whichever product is active, and the response names that product. Only `title` may be combined with this flag (to name the new project); any other field combined with it is refused and changes nothing, since the task row is gone before it could apply. Default `false`. |

---

### list_tasks `mcp:read`

**Purpose:** List tasks for the active product with projection modes, search, and
pagination. Agents see hidden and non-hidden rows alike by default.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| mode | str | No | `""` | `index` (leanest — the list-and-sort row, typically 35-40% smaller than `summary`, depending on title length) / `summary` / `full`. `""` defaults to `summary` unless `summary_only` says otherwise. When passed explicitly, `mode` wins over `summary_only`. |
| status | str | No | `""` | Filter by exact status (e.g. `"pending"`); an unrecognized value is refused, naming the valid ones, rather than silently matching nothing. |
| priority | str | No | `""` | Filter by priority (`low`/`medium`/`high`/`critical`); same refuse-on-typo behavior as `status`. |
| task_type | str | No | `""` | Only `"TSK"` matches — every task carries that type. Any other value is refused rather than silently returned empty. |
| due_before | str | No | `""` | ISO-8601 upper bound on due date. |
| hidden | str | No | `""` | Tri-state: `"true"`/`"false"`/`""`. An unrecognized value is refused, naming the accepted ones. |
| summary_only | bool | No | `false` | Alias for `mode="summary"`. Ignored when `mode` is also passed explicitly. |
| memory_limit | int | No | `0` | Truncates description length in `full` mode. |
| query | str | No | `""` | Case-insensitive substring search against title, description, and `taxonomy_alias` (e.g. `"oauth"`, `"TSK-9438"`). Empty = no search filter. |
| limit | int | No | `50` | Max tasks to return (max `500`). `0` = use the default. The response always states whether it was cut, independent of this value. |
| cursor | str | No | `""` | Opaque continuation token from a previous response's `truncation.next_cursor`. Pass it back **with the same filters**; a filter change mid-walk is refused. Keep walking until `truncated=false` — every task is then returned exactly once. Changing `limit` or `mode` mid-walk is fine. |

**Response shape:** every response carries board-wide totals (how many tasks are done,
how many are still open, and the date range they span) plus `counts.matched` for the
caller's own filters, so an agent can judge board size before deciding whether to page
through it.

---

## Roadmap

### save_roadmap `mcp:write`

**Purpose:** Save the roadmap — the ranked list of what to build next. YOU do the
ranking; the server only validates and stores it. Items you send are written, replacing
any earlier entry for the same project or task. Defaults to your default product; pass
`product_id` for a specific one. (Renamed from `update_roadmap_metadata`.)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| items | list[dict] | Yes | Roadmap items to upsert. Each: `{item_type: 'project'\|'task', project_id OR task_id, sort_order (0-100000), risk?: 'low'\|'med'\|'high', complexity?: 'light'\|'med'\|'heavy', blocked?: bool, blocked_reason?: str (<=500 chars)}`. `project_id` / `task_id` accept either the row id or its taxonomy alias (`BE-0001`, `IMP-0086`), so no lookup call is needed. A rejection names every bad row at once, as a 422, never a DB 500. |
| summary | str | No | Roadmap narrative summary (the AI insight banner copy). Empty string leaves it unchanged. |
| remove | list[dict] | No | Items to drop from the roadmap. Each: `{item_type, project_id\|task_id}`. Idempotent; removes the roadmap entry only, never the project/task. |
| patch_fields | bool | No | Patch only the fields each item carries; omitted fields keep their stored value, explicitly empty ones are cleared. `blocked` and `blocked_reason` patch together. Default false. |
| product_id | str | No | Product UUID to persist the roadmap for. Omit to use your default product — but pass it when you know it: the default is shared, mutable state another session can move mid-session. |

---

### get_roadmap `mcp:read`

**Purpose:** Read the current roadmap for the active product. Returns items sorted by
`sort_order` ascending with status and blocked state.

**Parameters:** None.

---

## Agent Jobs & Lifecycle

### spawn_job `mcp:agent`

**Purpose:** Create a specialist agent job during orchestrator staging. Returns a
`job_id` and a thin prompt (~10 lines); the agent then calls `get_job_mission()` to
fetch the full mission.

The thin prompt ends with a **`## HARNESS` block** for the harness assigned to that
agent's template (Claude Code, Codex, OpenCode, or a generic fallback): the launch line
to start the agent in a fresh session, plus a model hint and an effort hint when the
template sets them to anything other than `inherit`. Hints are prose for the harness --
`inherit` means "the same as the orchestrator", and a harness that cannot honour a value
ignores it. There is no agent file to install or look up.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| agent_display_name | str | Yes | Human-readable agent name shown in the dashboard. |
| agent_name | str | Yes | Internal agent identifier matching a template. |
| project_id | str | Yes | ID of the parent project. |
| mission | str | No | The specific task this agent must accomplish. |
| phase | int | No | Execution phase number for ordering. |
| predecessor_job_id | str | No | Job that must complete before this one starts. |

---

### get_job_mission `mcp:agent`

**Purpose:** Fetch the agent-specific mission and context. The agent's first action
after `spawn_job`. Returns the targeted mission, not the full project vision. Idempotent.

The response carries an **`agent_profile`** block in every execution mode: the agent's
name, role, description, assigned harness, model and effort hints, instructions,
behavioural rules, and success criteria. That block is the agent's role -- read it and
start. Nothing needs to be installed on your machine, and there is no agent template file
to look for.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The job ID from the spawn prompt. |
| protocol_etag | str | No | The `protocol_etag` returned by a prior `get_job_mission` call. When supplied and unchanged, the static identity+protocol block is omitted. |
| harness | str | No | Optional session harness preset: `web_sandbox`\|`desktop_app`\|`chat` (omit for a terminal-capable CLI). |
| section | str | No | Truncation recovery: a section name from a prior response's `protocol_toc`; the response then carries only that slice of `full_protocol`. Default `""` returns the full mission response. |

---

### update_job_mission `mcp:agent`

**Purpose:** Update an agent's mission/execution plan during staging, enabling a
fresh-session orchestrator to retrieve its plan later via `get_job_mission()`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The agent's own job ID. |
| mission | str | Yes | Updated mission or execution plan. |

---

### report_progress `mcp:agent`

**Purpose:** Report incremental progress via TODO items; the backend auto-calculates
percent and step counts and auto-wakes idle/sleeping/blocked agents to `working`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The agent's job ID. |
| todo_items | list[dict] | No | Full replacement TODO list. Each item: `{content: str, status: 'pending'\|'in_progress'\|'completed'}`. Include ALL items — completed + in_progress + pending — never a partial list. |
| todo_append | list[dict] | No | New items to append without replacing the stored list. Same item format as `todo_items`. Use this to add work discovered mid-task without overwriting what is already there. |
| replace | bool | No | Required (`true`) when `todo_items` is SHORTER than the stored list — otherwise the call is rejected rather than silently dropping items. Default `false`. |

---

### complete_job `mcp:agent`

**Purpose:** Mark a job completed with a structured result. Rejected if unread messages
or incomplete TODOs remain. Phase-aware: a staging orchestrator gets a
`staging_directive.action='STOP'` (do NOT call closeout from the staging session);
an implementation orchestrator and deliverable agents close normally.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The agent's job ID. |
| result | dict | Yes | Structured result (`summary`, `artifacts`, `commits`). |
| acknowledge_closeout_todo | bool | No | Auto-completes the closeout-describing TODO. Default `false`. |
| acknowledge_messages_on_complete | bool | No | Drains unread messages before the gate check. Default `false`. |

---

### finalize_job `mcp:agent`

**Purpose:** Accept a finished agent's work and seal the job — the last step, after you
have reviewed what it produced. Only the orchestrator does this, and only after
`complete_job`. A sealed job is not woken again by new messages. If the job is not in an
acceptable state, this returns a structured error naming the outstanding requirement.
(Renamed from `close_job`, which read as cancel-or-finish ambiguous.)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The job ID to seal. |

---

### resume_or_dismiss_job `mcp:agent`

**Purpose:** A finished job that receives a message needing action is put on hold. Use
this to say what happens next: `resume` picks the work back up (then `report_progress`
with `todo_append` to add new steps — do not overwrite completed ones), or `dismiss`
acknowledges the message and leaves the job finished, when it was only for information.
Only works while the job is on hold — the `blocked` status auto-set when a directed,
action-required Hub post lands on a completed agent. (Renamed from
`resolve_reactivation`; merges the former `reactivate_job` + `dismiss_reactivation`
tools, BE-6225e.)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The on-hold job's ID. |
| action | str | Yes | `resume` (→ working) or `dismiss` (→ complete). |
| reason | str | No | Why work is resuming / no action was taken. |

---

### set_agent_status `mcp:agent`

**Purpose:** Set a resting/blocked status (`blocked`, `idle`, `sleeping`). All three
auto-wake when `report_progress()` is called. Cannot produce `awaiting_user` (only
`request_approval` can). Server-locked during staging for the orchestrator.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The agent's job ID. |
| status | str | Yes | `blocked`, `idle`, or `sleeping`. |
| reason | str | No | Human-readable explanation. |
| wake_in_minutes | int | No | For `sleeping`: minutes until a timed wake. |
| wake_on_signal | bool | No | For `sleeping`: pass `true` when you are parked on `get_my_turn(wait_seconds=...)` rather than a timed sleep, so the dashboard shows "Waiting for wake" instead of a countdown. Mutually exclusive with `wake_in_minutes` (`wake_on_signal` wins). Default `false`. |

---

### get_agent_result `mcp:agent`

**Purpose:** Fetch the completion result of a finished agent job — the structured result
stored when the agent called `complete_job`. Use to read what a predecessor accomplished.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The job ID of the completed agent. |

---

### get_workflow_status `mcp:agent`

**Purpose:** Monitor workflow progress across all project agents. Returns counts by
status (active/completed/blocked/closed/silent/decommissioned/pending) and a
`progress_percent` (0-100).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the project to monitor. |
| exclude_job_id | str | No | Job ID to exclude (typically the orchestrator's own). |

---

### request_approval `mcp:agent`

**Purpose:** Request a user decision before continuing. Atomically creates a
`user_approvals` row and flips the calling agent to `awaiting_user`. The agent's
`complete_job` is refused until a user resolves the approval via the dashboard or
`POST /api/approvals/{id}/decide`. At most one `pending` approval per execution.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | Calling agent's `job_id`. |
| project_id | str | Yes | Project the approval belongs to. |
| reason | str | Yes | Plain-English explanation shown to the user (max 2000 chars). |
| options | list[dict] | Yes | `{id, label}` option dicts (1-10 items, unique ids). |
| context | dict | No | Optional structured payload (max 16 KB serialized). |

---

### decide_approval `mcp:agent`

**Purpose:** Answer a pending user approval from the harness — clears `awaiting_user` for
the orchestrator that called `request_approval`. Relay the pending question's reason and
options to the user in your terminal, then call this with the option id they chose.
Routes through the SAME service write the dashboard's decide button uses; there is no
separate write path. Available by default; a tenant that has switched Settings to HITL
mode is refused here and decides from the dashboard instead. Behind the default
human-in-the-loop fence, so a dashboard/JWT session is only served this tool when its
tenant has enabled headless launch.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| approval_id | str | Yes | The pending approval's id (UUID). |
| option_id | str | Yes | The id of the option the user chose (must match one of `approval.options`). |

---

## Agent Message Hub

> **Note:** the legacy Direct Messaging bus tools (`send_message`, `receive_messages`,
> `get_messages`) were RETIRED in BE-9012d. Agent-to-agent coordination now runs entirely
> on the Agent Message Hub below — `post_to_thread` (directed via `to_participant`, or a
> broadcast) replaces `send_message`, and `get_thread_history` with
> `as_participant` + `unread_only` + `mark_read` is the drain-read that replaces
> `receive_messages` (omit `mark_read` for the read-only inspection `get_messages` gave). (threads)

The Hub is a side-effect-free message board (distinct from direct messaging, which is
coupled to job lifecycle). Threads carry a `CHT-####` chat id and a baton indicating
whose turn it is to act.

### create_thread `mcp:agent`

**Purpose:** Create a persistent message-board thread and get back its `CHT-####` id.
The creator is registered as the first participant holding the baton.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| subject | str | No | Thread subject. |
| severity | str | No | Thread severity. |
| product_id | str | No | Associated product. |
| project_id | str | No | Associated project. |
| creator_id | str | No | Creator agent id. |
| creator_display_name | str | No | Creator display name. |
| sequence_run_id | str | No | Chain conductors only — the run UUID this thread is the coordination hub for. Stamping it is what lets every sub-orchestrator find this hub via `get_context(categories=['chain'])`, with no subject-line convention required. |

---

### join_thread `mcp:agent`

**Purpose:** Join a thread by `thread_id`, declaring/claiming your `agent_id`.
Collision-safe — a re-join is a no-op.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| thread_id | str | Yes | The thread to join. |
| agent_id | str | Yes | Your agent id. |
| display_name | str | No | Your display name. |
| role | str | No | Your role in the thread. |

---

### post_to_thread `mcp:agent`

**Purpose:** Post an (append-only) message to a thread. Broadcasts to all participants
by default, or direct-messages one via `to_participant`. Can optionally `set_status`
(open/active/resolved/closed).

Every post must declare its author: pass `from_agent` (posting as an agent) **or**
`as_user=true` (posting in the human user's voice). The two are mutually exclusive, and
a post that declares neither is refused with `FROM_AGENT_REQUIRED` before anything is
written — attribution never falls back to the human user.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| thread_id | str | Yes | The thread to post to. |
| content | str | Yes | Message body. |
| from_agent | str | Yes* | Your agent role/id. Required unless `as_user=true`. |
| as_user | bool | Yes* | Post as the authenticated human user. Required unless `from_agent` is set; the two cannot be combined. |
| to_participant | str | No | Direct-message a single participant. |
| set_status | str | No | `open` / `active` / `resolved` / `closed`. |
| requires_action | bool | No | Whether a recipient must act. |
| loop_directive | bool | No | Loop-control directive — recipients loop/sleep on their normal wake interval until the thread is set `resolved`/`closed`. |
| loop_interval_minutes | int | No | Auto-check-in cadence in minutes for the loop directive (0-1440), surfaced on `get_my_turn`/`get_thread_history` poll responses so the agent self-schedules its wake. `0` = unset (agent uses its own default). Only meaningful with `loop_directive=true`. |
| pass_baton_to | str | No | Atomically hand the baton with this post: an `agent_id` \| `user_id` \| `all` \| `none`. An explicit value always wins; `none` posts without moving the baton. When omitted, a directed action-request (`requires_action=true` + `to_participant`) auto-passes the baton to that participant; every other post leaves the baton untouched. |
| my_status | str | No | What you are doing right now, shown on your status dot in the Hub: one of `working` \| `waiting` \| `blocked` \| `idle` \| `sleeping` \| `complete`. Only useful for a headless/external agent that joined via `join_thread` — a platform-run agent already reports status automatically, and that always wins over this. Omit to leave your current status unchanged. |
| rename_to | str | No | Rename the thread with this post. Empty leaves it unchanged. Refused on a project-bound thread (it takes its name from that project) — and a refused rename posts nothing, because the rename is applied before the post. |

---

### get_my_turn `mcp:read`

**Purpose:** The baton query — list the conversations waiting on YOU: threads where you
hold the turn (`next_action_owner == your agent_id`), plus anything addressed to `all`.

Pass `wait_seconds` to WAIT for the next one instead of returning immediately. The call
comes back the moment a directed action-request or a baton lands for you, or empty if
nothing does, and costs nothing while it waits — **waiting beats sleeping and re-asking**.
Without `wait_seconds` it answers instantly, which means you are polling, not parked.
Chat surfaces that cannot hold a call open should leave `wait_seconds` at 0 and ask again
on their own schedule. (This absorbed the retired `await_my_turn` tool, whose
`timeout_seconds` is now `wait_seconds`.)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| agent_id | str | Yes | Your agent id. |
| wait_seconds | int | No | `0` (default) answers immediately. Above `0`, wait up to this many seconds for something to arrive (capped at 55 by the server). This is how often you re-ask, not how fast a wake arrives — delivery is under a second either way. |

---

### get_participant_liveness `mcp:read`

**Purpose:** Who on this thread is still there. Returns each participant with when
they were last seen and a coarse state — active, quiet, gone, or unknown for someone
who has joined but not yet acted. Use it before deciding whether to keep waiting on an
agent, reassign its work, or escalate past an orchestrator that has gone quiet.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| thread_id | str | Yes | The thread UUID. |

---

### set_next_actor `mcp:agent`

**Purpose:** Set who acts next on a chat — an `agent_id`, a `user_id`, `all` (anyone may
act) or `none` (CLEARS it; nobody is waiting). Whoever you name finds it via
`get_my_turn`. **Note the difference from `post_to_thread`'s `pass_baton_to` parameter:**
there, `none` means LEAVE the current actor alone; here it CLEARS them. Clearing is the
one thing only this tool can do. (Renamed from `pass_baton`.)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| thread_id | str | Yes | The thread UUID. |
| to | str | Yes | Who acts next: an `agent_id`, a `user_id`, `all`, or `none`. `none` CLEARS the next actor — the one thing only this tool can do; `post_to_thread`'s own `none` leaves the current actor unchanged. |
| from_agent | str | No | Your agent id — who is handing over. Pass it so the recipient's alert names you, not only the thread. Omit only when handing over as the human user. |

---

### list_threads `mcp:read`

**Purpose:** Find chats. Newest first. Pass `query` to SEARCH by chat id, subject,
participant or message text; pass any of `status` / `owner` / `product_id` / `project_id`
to filter; pass nothing to list them all. Filters and query combine. (This absorbed the
retired `search_threads` tool.)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| status | str | No | Filter by thread status. |
| owner | str | No | Filter by `next_action_owner`. |
| product_id | str | No | Filter by product. |
| project_id | str | No | Filter by project. |
| query | str | No | Search text: a `CHT-####` chat id, a word from the subject, a participant, or message text. |

---

### update_thread `mcp:agent`

**Purpose:** Rename a thread, set its status, and/or retag its product and projects. This
is the ONLY way to give an old, pre-existing thread a product — there is no bulk
migration. Omit a field to leave it untouched. A rename is refused on a project-bound
thread (it takes its name from that project).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| thread_id | str | Yes | The thread UUID to update. |
| subject | str | No | New subject. Omit to leave unchanged. |
| status | str | No | New status. Omit to leave unchanged. |
| product_id | str | No | Product UUID to retag the thread with. Omit to leave unchanged. |
| clear_product | bool | No | Explicitly null the thread's product back to product-less. Default `false`. |
| project_ids | list[str] | No | Full-replace the thread's project tags (0-50 UUIDs). Omit to leave tags untouched; pass `[]` to clear all. A thread may tag zero, one, or many projects. |

---

### get_thread_history `mcp:read`

**Purpose:** Read a thread's message timeline, oldest-first. READ-ONLY by default
(does not acknowledge). A plain read returns only a bounded recent tail (200
messages) so polling a long thread stays cheap — pass `tail=0` for the entire
timeline. `after_message_id` / `since` / `tail=N` give an incremental fetch (their
delta is never truncated by the default tail). `as_participant` unlocks a
server-persistent, per-participant cursor: `unread_only` returns only posts since
your last `mark_read` on the thread; `mark_read` is a WRITE — it acknowledges the
returned posts and advances that cursor; `directed_only` returns only posts
delivered to you (DM or broadcast); `action_required_only` returns only posts
flagged `requires_action`. The four cursor params require `as_participant`;
`mark_read` on a thread you never `join_thread`'d is refused.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| thread_id | str | Yes | The thread to read. |
| after_message_id | str | No | Incremental cursor: return only messages after this message id. Omit for the bounded default. |
| since | str | No | Incremental: ISO-8601 timestamp; return only messages created after it. Omit for the bounded default. |
| tail | int | No | How many recent messages to return. Omit for the default bounded poll (last 200); `0` for the full timeline; `1`-`500` for the last N. Not applied to an `after_message_id`/`since`/`unread_only` read (those already return their own delta). |
| as_participant | str | No | Your participant_id — required to use `unread_only`/`mark_read`/`directed_only`/`action_required_only` (the server-persistent cursor is per participant). Omit for a plain read. |
| unread_only | bool | No | Return only posts since your last `mark_read` on this thread. Requires `as_participant`. |
| mark_read | bool | No | Acknowledge the returned posts and advance your persistent read cursor. Requires `as_participant` (join first). This is a WRITE. |
| directed_only | bool | No | Return only posts delivered to you (DMs + broadcasts you received; excludes a DM aimed at someone else). Requires `as_participant`. |
| action_required_only | bool | No | Return only posts flagged `requires_action`. Requires `as_participant`. |

---

## Context & Memory

### get_context `mcp:read`

**Purpose:** Unified context fetcher. Retrieves product/project context by category with
depth control; multiple categories in one call replace nine individual context tools.
Categories: `product_core`, `vision_documents`, `tech_stack`, `architecture`, `testing`,
`memory_360`, `git_history`, `agent_templates`, `project`, `self_identity`, `tasks`,
`todos`, `chain`, `threads`. `threads` returns the account's recent Hub conversation
threads (read-only — it never writes or marks anything read) using the same fixed cap
on every call, not tunable via `depth_config`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| product_id | str | Yes | ID of the product to fetch context for. |
| project_id | str | No | Project for project-scoped context. |
| agent_name | str | No | Agent name for the `self_identity` category. |
| job_id | str | No | Agent job UUID (required for the `todos` category). |
| categories | list[str] | Yes | One or more category strings (list explicitly; `"all"` not accepted). |
| depth_config | dict | No | Per-category depth overrides. |
| output_format | str | No | `structured` (default) or `flat`. |

---

### search_memory `mcp:read`

**Purpose:** Keyword-search the 360 memory (accumulated project closeouts/handovers) to answer "have we solved X before?". Case-insensitive substring/full-text match over each entry's `summary`, `key_outcomes`, `decisions_made`, `project_name` and `tags`, with an optional exact-`tag` filter. Tenant + active-product scoped (never pass `tenant_key`; an active product is required, same contract as `list_projects`). Returns relevance-ranked headlines `[{sequence, project_id, project_alias, project_name, summary, tags, type, score}]`. An empty query or no match returns an empty result, not an error. Distinct from `get_context(['memory_360'])` (recent-N by recency, not search) and `list_threads(query=)` (Hub chat, not memory).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | str | Yes | Case-insensitive keyword/substring to search for (max 2000 chars). |
| tag | str | No | Optional exact tag filter (controlled vocabulary, e.g. `bug-fix`). |
| limit | int | No | Max headlines to return (default 10, max 50). |

---

### write_memory_entry `mcp:agent`

**Purpose:** Write a 360 memory entry for project completion or agent handover. Appends
to the product's `sequential_history`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the project being recorded. |
| summary | str | Yes | Brief 2-3 sentence headline of what was accomplished or handed over. **Send this argument LAST in your call** — anything ordered after a long free-text argument like this one can be silently absorbed into it and never arrive as its own argument. |
| key_outcomes | list[str] | Yes | Concrete outcomes delivered. |
| decisions_made | list[str] | Yes | Architectural/design decisions made (cite any deferred task/project IDs). |
| entry_type | str | No | `baseline` (foundation context) / `decision` (a choice with rationale) / `architecture` (structural notes) / `discovery` (surprising finding worth remembering) — any specialist agent may write these. `project_completion` (closeout) and `session_handover` (orchestrator-to-orchestrator across sessions) are **orchestrator-only**; a specialist passing either is refused with `ORCHESTRATOR_ONLY_ENTRY_TYPE`. `handover_closeout` is a legacy alias kept for back-compat. Default `project_completion`. |
| author_job_id | str | No | Job ID of the authoring agent (usually the orchestrator's `job_id`). |
| git_commits | list[dict] | No | Commit records. Every entry must carry a non-empty commit title — a titleless entry is refused with `GIT_COMMIT_TITLE_REQUIRED`. Pass `{sha, message, author?, pr_url?}` dicts (preferred), or tab-delimited porcelain strings (`git log --format='%H%x09%s%x09%an' <base>..HEAD`). |
| tags | list[str] | No | Max 8 tags, each from the server-enforced 16-tag vocabulary: change-type (`feature`/`bug-fix`/`refactor`/`perf`/`security`/`docs`/`test`/`chore`), domain (`frontend`/`backend`/`database`/`api`/`infrastructure`/`ui-ux`/`integration`), operational (`migration`). |
| acknowledge_closeout_todo | bool | No | Auto-completes your own self-referential closeout TODOs (e.g. "Write series summary") before the closeout-readiness gate evaluates, resolving the chicken-and-egg where the TODO this write satisfies would otherwise block the write. Non-closeout TODOs still block. Default `false`. |

---

## Vision & Product Context

### create_product `mcp:write`

**Purpose:** Create a new product (BE-9201 agent-side bootstrap — the MCP twin of the
dashboard's product-create form). Establishes the product row only, INACTIVE; populate
tech/architecture/testing afterwards via `update_product_context`, and write a vision
document via `create_vision_document`. The user activates the product from the
dashboard. Fails if a product with the same name already exists.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | Yes | Product name (unique per tenant). |
| description | str | No | Product description. |
| project_path | str | No | Absolute path of the user's local codebase folder the agent is operating from. Omit if the agent has no filesystem access inside the repository. |
| core_features | str | No | Key product features. |
| brand_guidelines | str | No | Brand & design guidelines for frontend agents. |
| target_platforms | list[str] | No | Subset of: `windows`, `linux`, `macos`, `android`, `ios`, `web`, `all`. Defaults to `all`. |

---

### create_vision_document `mcp:write`

**Purpose:** Write an agent-authored markdown vision document onto an EXISTING product
(BE-9201 — the MCP twin of the dashboard's vision-document upload). The document gets
the identical ingest as a UI upload (inline storage, auto-chunking, auto-consolidation)
and appears in the dashboard exactly like an uploaded file. Content is size-capped at
the same limit as the UI upload. After creating the document, call `get_vision_document`
then `update_product_context` (including `vision_summaries` + `consolidated_vision`)
to populate the product card.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| product_id | str | Yes | ID of the product to attach the document to. |
| content | str | Yes | Full markdown vision document text. |
| document_name | str | No | Filename shown in the UI (e.g. `Product Vision.md`). Defaults to `Agent Vision.md`; `.md` is appended when the extension is missing. |

---

### get_vision_document `mcp:read`

**Purpose:** Retrieve a product's vision document with extraction instructions. Call
WITHOUT `chunk` first for metadata (`total_chunks`, `extraction_instructions`), then
fetch `chunk=1` through `chunk=total_chunks` — these reads are independent and
side-effect free, so request them in PARALLEL, in any order. Read ALL chunks before
calling `update_product_context`. (Renamed from `get_vision_doc`, to match
`create_vision_document`.)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| product_id | str | Yes | ID of the product whose vision document to retrieve. |
| chunk | int | No | Chunk index to fetch. Omit on the first call for metadata. |

---

### update_product_context `mcp:write`

**Purpose:** Write structured product fields extracted from vision-document analysis.
Merge-write: only provided fields are updated; child table rows (tech stack,
architecture, test config) are created on first write. Safe to call in stages — split
a large analysis across several calls and set `emit_completion=true` on the last one.
Every response reports `vision_analysis_complete`, `missing_for_completion`, and
`fields_skipped`, so you never have to infer what landed.

The tech/architecture/quality/testing prose is grouped into four typed dicts
(BE-9118); unknown sub-keys inside a group are rejected at the tool boundary.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| product_id | str | Yes | ID of the product to update. |
| product_name / product_description | str | No | Product identity fields. |
| core_features | str | No | Key product features. |
| project_path | str | No | Absolute path of the user's local codebase folder you are operating from. Omit if you have no filesystem access inside the user's repository — never guess. Like `product_name`, it is user-owned and skipped when already set. |
| tech_stack | dict | No | Group: `programming_languages`, `frontend_frameworks`, `backend_frameworks`, `databases`, `infrastructure`, `target_platforms` (list from: `windows`, `linux`, `macos`, `android`, `ios`, `web`, `all`). |
| architecture | dict | No | Group: `architecture_pattern`, `design_patterns`, `api_style`, `architecture_notes`, `coding_conventions`, `brand_guidelines`. |
| quality | dict | No | Group: `quality_standards`. |
| testing | dict | No | Group: `testing_strategy`, `testing_frameworks`, `test_coverage_target` (int 0-100). |
| vision_summaries | list[dict] | No | Per-document AI summaries (`doc_id`, `light`, `medium`). |
| consolidated_vision | dict | No | Product-level aggregate summary (`light`, `medium`). |
| force | bool | No | Override merge guards. |
| emit_completion | bool | No | Set `true` on your final staged call. Re-checks the completion state and signals the dashboard even when this call writes no new fields. Default `false`. |

---

### apply_context_tuning `mcp:write`

**Purpose:** Apply reviewed product-context tuning directly to product fields, after
comparing current product context against recent project history. Call after analyzing
the tuning comparison — approved proposals are written immediately (no separate
dashboard review step). Renamed from `propose_product_context_update` (BE-6225c): it
applies, it does not propose.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| product_id | str | Yes | ID of the product to tune. |
| proposals | list[dict] | Yes | Typed proposals (BE-9118): each requires `section` and `drift_detected`; optional `proposed_value` (str/dict/list, capped), `confidence` (`high`/`medium`/`low`), `current_summary`, `evidence`, `reasoning`. |
| overall_summary | str | No | Narrative summary of the tuning analysis. |
| force | bool | No | Override guards. |

---

## Setup & Templates

### giljo_setup `mcp:write`

**Purpose:** First-time setup. Installs the `/giljo` command/skill, writes the Giljo HQ
marker block (primer plus product binding) into your harness file (`CLAUDE.md` /
`AGENTS.md`), and records acknowledgement of the bundled `SKILLS_VERSION`. Run once after
connecting, and again whenever your skills are outdated.

It does **not** install agent templates. Every spawned agent receives its full profile
from the server in `get_job_mission`'s `agent_profile`, so nothing has to live in your
agents directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| platform | str | No | `claude_code`, `codex_cli`, `opencode`, `generic`. Default auto-detects. |
| harness | str | No | Optional session harness preset: `web_sandbox`\|`desktop_app`\|`chat` (omit for a terminal-capable CLI). |
| product_id | str | No | Product UUID to bind this repository to. The returned instructions then include writing a marker block into `CLAUDE.md` and `AGENTS.md`, so later calls from this repo never hit a product-ambiguity rejection. Omit on a tenant with zero or several products; the response says what to do next. |
| scope | str | No | **Retired.** There is no install scope any more; passing any value is refused with a structured rejection that names the replacement. Omit it. |

> **Agent templates:** read their content via
> `get_context(categories=['agent_templates'])`. Spawned agents do not need them --
> each one receives its own profile from `get_job_mission`. To hand a profile to an
> agent you run yourself, use the Template Manager's per-agent menu and choose
> **Download profile (.md)**, which serves
> `GET /api/v1/templates/{template_id}/profile.md` as plain Markdown. (The standalone
> `list_agent_templates` MCP tool was retired in BE-6225a.)

---

## Tool Count Summary

| Category | Scope mix | Tools |
|----------|-----------|-------|
| Discovery & Health | 2 read | health_check, get_giljo_guide |
| Project Management | 2 write · 2 read · 1 agent | create_project, update_project, list_projects, update_project_mission, diagnose_project_state |
| Project Lifecycle | 7 agent | stage_project, get_staging_instructions, get_implementation_prompt, launch_implementation, link_projects, unlink_projects, write_project_closeout |
| Tasks | 2 write · 1 read | create_task, update_task, list_tasks |
| Roadmap | 1 write · 1 read | save_roadmap, get_roadmap |
| Agent Jobs & Lifecycle | 12 agent | spawn_job, get_job_mission, update_job_mission, report_progress, complete_job, finalize_job, resume_or_dismiss_job, set_agent_status, get_agent_result, get_workflow_status, request_approval, decide_approval |
| Agent Message Hub | 5 agent · 5 read | create_thread, join_thread, post_to_thread, set_next_actor, update_thread, get_my_turn, get_participant_liveness, list_threads, get_thread_history |
| Context & Memory | 2 read · 1 agent | get_context, search_memory, write_memory_entry |
| Vision & Product Context | 1 read · 4 write | create_product, create_vision_document, get_vision_document, update_product_context, apply_context_tuning |
| Setup | 1 write | giljo_setup |
| **Total** | **13 read · 10 write · 26 agent** | **49** |
