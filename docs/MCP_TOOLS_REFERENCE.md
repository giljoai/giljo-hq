# Giljo HQ: Tools Reference

*Last updated: 2026-07-16*

## Overview

Giljo HQ, a GiljoAI product, exposes **46 tools** to connected AI coding tools. Every tool requires a
valid API key passed as a Bearer token. Tenant isolation is enforced server-side;
agents cannot cross tenant boundaries.

Tool names match the exact MCP registrations. The tool surface — including the exact
tool set, every parameter name, and every tool's scope — is drift-guarded by the
roster-lock test suite (`tests/unit/test_be6042d_mcp_tool_registry_surface.py`): any
add, rename, drop, param change, or scope change turns CI red until the lock is
updated deliberately. That test is the source of truth for the counts and scopes
below.

### Scopes

Every tool carries one of three permission scopes:

| Scope | Meaning | Count |
|-------|---------|-------|
| `mcp:read` | Read-only — fetches data, never mutates state. | 13 |
| `mcp:write` | Mutating writes performed by a human/dashboard-driven flow. | 10 |
| `mcp:agent` | Agent-lifecycle operations used by orchestrators and specialist agents. | 23 |
| **Total** | | **46** |

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

**Purpose:** Create a new project bound to the active product. `project_type` plus
`series_number` form a taxonomy serial such as `FE-0001`; the `suffix` enables chain
steps (a/b/c). Unknown `project_type` values are rejected with the list of valid types.
The project is created inactive; activate it from the dashboard.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | Yes | Project name. |
| description | str | Yes | Human-written project description (user requirements). Must state `**Edition Scope:**`. |
| project_type | str | No | Taxonomy type abbreviation (e.g. `FE`, `BE`, `INF`). Must match a configured type. |
| series_number | int | No | Sequential number within the type series (0 = auto-assign). |
| suffix | str | No | Chain-step suffix (e.g. `a`, `b`, `c`) sharing one `series_number`. |
| bootstrap_template_vars | dict | No | Optional template variables for project bootstrap. |

---

### update_project `mcp:write`

**Purpose:** Update project metadata (name, description, status, type, series
positioning). Omitted fields remain unchanged.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the project to update. |
| name | str | No | New project name. |
| description | str | No | New description. |
| status | str | No | New lifecycle status. |
| project_type | str | No | New taxonomy type abbreviation. |
| series_number | int | No | New series number. |
| suffix | str | No | New chain-step suffix. |

---

### list_projects `mcp:read`

**Purpose:** List projects for the active product with server-side filtering. By default
returns only active-lifecycle projects (excludes completed/cancelled) in summary form.
Prefer `mode` (`triage`/`planning`/`audit`/`forensic`) over numeric `depth`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| status | str | No | `""` | Filter by status. Single (`"active"`) or comma-separated. When set, `include_completed` is ignored. |
| project_type | str | No | `""` | Filter by taxonomy type, single or comma-separated (`"BE,FE"`). |
| taxonomy_alias_prefix | str | No | `""` | Prefix-match against taxonomy alias (e.g. `"BE-50"`). |
| created_after / created_before | str | No | `""` | ISO-8601 bounds on creation time. |
| completed_after / completed_before | str | No | `""` | ISO-8601 bounds on completion time. |
| include_completed | bool | No | `false` | Include archived (completed/cancelled) projects. Ignored when `status` is set. |
| hidden | str | No | `""` | Tri-state: `"true"` only hidden, `"false"` exclude hidden, `""` no filter. |
| mode | str | No | `""` | **Preferred.** `triage` / `planning` / `audit` / `forensic`. Overrides `depth` and `summary_only`. |
| memory_limit | int | No | `5` | Caps trailing 360-memory entries per project in audit mode (max 50). |
| summary_only | bool | No | `true` | Back-compat. Ignored when `mode` is supplied. |
| depth | int | No | `0` | Back-compat numeric detail 0-3. Prefer `mode`. |
| status_filter | str | No | `""` | Legacy. Prefer `status`. `"all"` implies `include_completed=true`. |

**Modes:** `triage` (id/name/status/type/dates — pick a project) · `planning`
(+ description, mission, agent counts) · `audit` (+ memory headlines + agent summaries)
· `forensic` (+ full memory bodies, agent results, message history).

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
| mode | str | No | Execution mode (ADR-010). 2 canonical values: `multi_terminal` (default, one terminal per agent) / `subagent` (one orchestrator session drives the workers). Plus 4 short per-CLI hint aliases — `claude`, `codex`, `gemini`, `antigravity` — each collapsing to `subagent` plus a harness hint for the staging prose flavor. |

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

### implement_project `mcp:agent`

**Purpose:** Return the implementation prompt for an already-staged project after the
user presses Implement. Returns a structured rejection (`action_required`) if the human
implement gate has not been passed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | ID of the staged project. |

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

### start_chain_run `mcp:agent`

**Purpose:** Start a chain run (linked multi-project sequential run) from a headless/CLI agent — the MCP equivalent of the dashboard "Run Sequential" button. Validates the projects (each must exist for the tenant, be chainable, and form a chain of >= 2 distinct members), creates the durable `sequence_run`, and mints the dedicated project-less chain conductor that drives all N projects in order (reuses the same engine as the REST path). On success returns the run plus `conductor_agent_id` / `conductor_job_id` and a `next_action` to call `get_staging_instructions(job_id=conductor_job_id)`. Bad input returns a structured `{success:false, error:CODE}` rejection (`PROJECT_NOT_FOUND` / `PROJECT_NOT_CHAINABLE` / `RESOLVED_ORDER_MISMATCH` / `CHAIN_TOO_SMALL`).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_ids | list[str] | Yes | Projects to link into the chain (>= 2 distinct), in run order. Capped at the server's MAX_SEQUENCE_PROJECTS. |
| execution_mode | str | Yes | Uniform execution mode for every project (ADR-010). 2 canonical values: `subagent` (one orchestrator session drives the workers — the normal headless choice) / `multi_terminal` (one terminal per agent). The 5 legacy per-CLI tokens (`claude_code_cli`, `codex_cli`, `gemini_cli`, `antigravity_cli`, `generic_mcp`) are still accepted as aliases and fold onto `subagent` (`platform_registry.ACCEPTED_EXECUTION_MODES`). |
| resolved_order | list[str] | No | Explicit run order — a permutation of `project_ids`. Defaults to the `project_ids` order. |
| review_policy | str | No | `per_card` (default, pause for review between projects) or `auto_close`. |
| chain_mission | str | No | Optional initial cross-project chain plan; the conductor normally authors this during staging. |

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

---

## Tasks

### create_task `mcp:write`

**Purpose:** Create a task (a single-step deferral / technical debt item) bound to the
active product. When `task_type` is set, a `series_number` is auto-assigned from the
counter shared with projects, yielding a `taxonomy_alias` like `BE-5067`; both are
inherited on task→project conversion.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| title | str | Yes | Task title. |
| description | str | Yes | Detailed task description. |
| priority | str | No | `low` / `medium` / `high` / `critical`. Default `medium`. |
| task_type | str | No | Taxonomy type abbreviation (e.g. `BE`, `FE`, `INF`). |
| assigned_to | str | No | Agent or user to assign the task to. |

---

### update_task `mcp:write`

**Purpose:** Update task metadata (title, description, status, priority, due date,
hidden flag). Omitted fields remain unchanged; the task type is immutable. To
**complete** a task, set `status=completed` (this stamps `completed_at`); pass
`completion_notes` to append an audit-trail entry as it completes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | str | Yes | ID of the task to update. |
| title | str | No | New title. |
| description | str | No | New description. |
| status | str | No | `pending` / `in_progress` / `completed` / `blocked` / `cancelled`. |
| priority | str | No | `low` / `medium` / `high` / `critical`. |
| task_type | str | No | Taxonomy type abbreviation. |
| due_date | str | No | ISO-8601 due date. |
| hidden | str | No | UI declutter flag. |
| completion_notes | str | No | Note appended to the audit trail when `status=completed` (folds in the retired `complete_task` tool); a no-op otherwise. |

---

### list_tasks `mcp:read`

**Purpose:** List tasks for the active product with projection modes and optional
filters. Agents see hidden and non-hidden rows alike by default.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| mode | str | No | `summary` or `full`. |
| status | str | No | Filter by status. |
| priority | str | No | Filter by priority. |
| task_type | str | No | Filter by taxonomy type. |
| due_before | str | No | ISO-8601 upper bound on due date. |
| hidden | str | No | Tri-state hidden filter. |
| summary_only | bool | No | Back-compat projection toggle. |
| memory_limit | int | No | Caps returned rows. |

---

## Roadmap

### update_roadmap_metadata `mcp:write`

**Purpose:** Persist a roadmap for the active product via bulk upsert of items
(project/task references with `sort_order`, risk, complexity, blocked state). De-dupes
and can remove items in the same call.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| items | list[dict] | Yes | Roadmap items to upsert. |
| summary | str | No | Roadmap narrative summary. |
| remove | list[dict] | No | Items to drop from the roadmap. |

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
| todo_items | list[dict] | No | Full replacement TODO list (`title`, `done`). |
| todo_append | list[dict] | No | Items to append without overwriting completed steps. |

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

### close_job `mcp:agent`

**Purpose:** Mark a completed agent job as `closed` (final acceptance). Transitions
`complete → closed`; the job will not auto-reactivate on new messages.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The job ID to close. |

---

### resolve_reactivation `mcp:agent`

**Purpose:** Exit a `blocked` job after a follow-up post. `action="resume"` returns it to
`working` (continue the work — use `report_progress` with `todo_append` afterward);
`action="dismiss"` returns it to `complete` (acknowledge an informational post without
resuming). Only works when status is `blocked` (auto-set when a directed,
action-required Hub post lands on a completed agent). Merges the former
`reactivate_job` + `dismiss_reactivation` tools into one (BE-6225e).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | str | Yes | The blocked job's ID. |
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
| wake_in_minutes | int | No | For `sleeping`: minutes until wake. |

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

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| thread_id | str | Yes | The thread to post to. |
| content | str | Yes | Message body. |
| from_agent | str | No | Sender id. |
| to_participant | str | No | Direct-message a single participant. |
| set_status | str | No | `open` / `active` / `resolved` / `closed`. |
| requires_action | bool | No | Whether a recipient must act. |
| loop_directive | bool | No | Loop-control directive. |

---

### get_my_turn `mcp:read`

**Purpose:** The baton query — list threads where it is your turn
(`next_action_owner == your agent_id`, plus threads addressed to `all`).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| agent_id | str | Yes | Your agent id. |

---

### pass_baton `mcp:agent`

**Purpose:** Set who acts next on a thread — an `agent_id`, `user_id`, `all`, or `none`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| thread_id | str | Yes | The thread. |
| to | str | Yes | Next actor (`agent_id` / `user_id` / `all` / `none`). |

---

### list_threads `mcp:read`

**Purpose:** List message-board threads with optional filters (status, owner, product,
project). Newest first.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| status | str | No | Filter by thread status. |
| owner | str | No | Filter by `next_action_owner`. |
| product_id | str | No | Filter by product. |
| project_id | str | No | Filter by project. |

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

### search_threads `mcp:read`

**Purpose:** Search threads by `CHT` serial, subject keyword, participant, or message
content. Tenant-scoped, newest first.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | str | Yes | Search query. |

---

## Context & Memory

### get_context `mcp:read`

**Purpose:** Unified context fetcher. Retrieves product/project context by category with
depth control; multiple categories in one call replace nine individual context tools.
Categories: `product_core`, `vision_documents`, `tech_stack`, `architecture`, `testing`,
`memory_360`, `git_history`, `agent_templates`, `project`, `self_identity`, `tasks`,
`todos`.

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

**Purpose:** Keyword-search the 360 memory (accumulated project closeouts/handovers) to answer "have we solved X before?". Case-insensitive substring/full-text match over each entry's `summary`, `key_outcomes`, `decisions_made`, `project_name` and `tags`, with an optional exact-`tag` filter. Tenant + active-product scoped (never pass `tenant_key`; an active product is required, same contract as `list_projects`). Returns relevance-ranked headlines `[{sequence, project_id, project_alias, project_name, summary, tags, type, score}]`. An empty query or no match returns an empty result, not an error. Distinct from `get_context(['memory_360'])` (recent-N by recency, not search) and `search_threads` (Hub chat, not memory).

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
| summary | str | Yes | Narrative summary of the work done. |
| key_outcomes | list[str] | Yes | Concrete outcomes delivered. |
| decisions_made | list[str] | Yes | Architectural/design decisions made. |
| entry_type | str | No | Type of entry. Default `project_completion`. |
| author_job_id | str | No | Job ID of the agent writing the entry. |
| git_commits | list[dict] | No | Commit records. |
| tags | list[str] | No | Classification tags. |

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
the same limit as the UI upload. After creating the document, call `get_vision_doc`
then `update_product_context` (including `vision_summaries` + `consolidated_vision`)
to populate the product card.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| product_id | str | Yes | ID of the product to attach the document to. |
| content | str | Yes | Full markdown vision document text. |
| document_name | str | No | Filename shown in the UI (e.g. `Product Vision.md`). Defaults to `Agent Vision.md`; `.md` is appended when the extension is missing. |

---

### get_vision_doc `mcp:read`

**Purpose:** Retrieve a product's vision document with extraction instructions. Call
without `chunk` first for metadata (`total_chunks`, `extraction_instructions`), then
fetch each chunk one at a time. Read all chunks before calling `update_product_context`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| product_id | str | Yes | ID of the product whose vision document to retrieve. |
| chunk | int | No | Chunk index to fetch. Omit on first call for metadata. |

---

### update_product_context `mcp:write`

**Purpose:** Write structured product fields extracted from vision-document analysis.
Merge-write: only provided fields are updated; child table rows (tech stack,
architecture, test config) are created on first write.

The tech/architecture/quality/testing prose is grouped into four typed dicts
(BE-9118); unknown sub-keys inside a group are rejected at the tool boundary.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| product_id | str | Yes | ID of the product to update. |
| product_name / product_description | str | No | Product identity fields. |
| core_features | str | No | Key product features. |
| tech_stack | dict | No | Group: `programming_languages`, `frontend_frameworks`, `backend_frameworks`, `databases`, `infrastructure`, `target_platforms` (list from: `windows`, `linux`, `macos`, `android`, `ios`, `web`, `all`). |
| architecture | dict | No | Group: `architecture_pattern`, `design_patterns`, `api_style`, `architecture_notes`, `coding_conventions`, `brand_guidelines`. |
| quality | dict | No | Group: `quality_standards`. |
| testing | dict | No | Group: `testing_strategy`, `testing_frameworks`, `test_coverage_target` (int 0-100). |
| vision_summaries | list[dict] | No | Per-document AI summaries (`doc_id`, `light`, `medium`). |
| consolidated_vision | dict | No | Product-level aggregate summary (`light`, `medium`). |
| force | bool | No | Override merge guards. |

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

**Purpose:** First-time setup. Downloads the combined ZIP with the `/giljo`
command/skill and agent templates, installs them, and records acknowledgement of the
bundled `SKILLS_VERSION`. Run once after connecting.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| platform | str | No | `claude_code`, `codex_cli`, `gemini_cli`, `antigravity_cli`, `generic`. Default auto-detects. |
| harness | str | No | Optional session harness preset: `web_sandbox`\|`desktop_app`\|`chat` (omit for a terminal-capable CLI). |

> **Agent templates:** install them via `giljo_setup` ("Agents only" scope) and read
> their content via `get_context(categories=['agent_templates'])`. (The standalone
> `list_agent_templates` MCP tool was retired in BE-6225a; the REST download path
> remains for non-tool callers.)

---

## Tool Count Summary

| Category | Scope mix | Tools |
|----------|-----------|-------|
| Discovery & Health | 2× read | health_check, get_giljo_guide |
| Project Management | 2 write · 2 read · 1 agent | create_project, update_project, list_projects, update_project_mission, diagnose_project_state |
| Project Lifecycle | 6× agent | stage_project, get_staging_instructions, implement_project, launch_implementation, start_chain_run, write_project_closeout |
| Tasks | 2 write · 1 read | create_task, update_task, list_tasks |
| Roadmap | 1 write · 1 read | update_roadmap_metadata, get_roadmap |
| Agent Jobs & Lifecycle | 11× agent | spawn_job, get_job_mission, update_job_mission, report_progress, complete_job, close_job, resolve_reactivation, set_agent_status, get_agent_result, get_workflow_status, request_approval |
| Agent Message Hub | 4 agent · 4 read | create_thread, join_thread, post_to_thread, pass_baton, get_my_turn, list_threads, get_thread_history, search_threads |
| Context & Memory | 2 read · 1 agent | get_context, search_memory, write_memory_entry |
| Vision & Product Context | 1 read · 4 write | create_product, create_vision_document, get_vision_doc, update_product_context, apply_context_tuning |
| Setup | 1 write | giljo_setup |
| **Total** | **13 read · 10 write · 23 agent** | **46** |
