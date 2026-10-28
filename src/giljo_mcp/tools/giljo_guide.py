# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.branding import PRODUCT_NAME


_GUIDE_TEMPLATE = """\
# {product_name} -- how to drive the project/task tools

You are talking to the {product_name} dashboard over MCP. This guide is the routing +
judgment layer for the create/read/update tools. Call it once, then act. Parameter detail
lives in each tool's own description; this guide does not repeat it.

## 0. Operating principle -- server-authored artifacts are VERBATIM
When a tool response hands you a ready-made artifact to write or run -- a launcher script,
a command block, a file body marked "copy verbatim" -- write/run it BYTE-FOR-BYTE. Do NOT
reformat, re-quote or "tidy" it (e.g. turning a quoted argument string into array form, or
normalizing line endings): its quoting is load-bearing and the server already resolved it.

## 1. Project vs task -- pick the right create tool
**Name your product.** Both create tools take an optional `product_id`. Omit it and a
tenant with exactly one product gets the DEFAULT product, but a tenant with MORE THAN ONE
gets a structured `PRODUCT_AMBIGUOUS` rejection (with the product list) and nothing is
created; it never guesses. A staged orchestrator knows its product: PASS `product_id`. The
create response names where it landed (`product_id` + `product_name`); read it back. From a
repo, long-term: `giljo_setup(product_id=...)` once writes a per-repo binding into
CLAUDE.md/AGENTS.md so later sessions pass it automatically.
- **Task** (`create_task`): technical debt, a TODO, a bug, a small fix, a scope-creep punt.
  `task_type` is **`TSK`** (default) or **`HND`** (a session handover), nothing else. The
  serial comes from one shared counter, so a handover is `HND-9641`, not `HND-0001`.
- **Session handover** (`create_task(task_type="HND")`): written when YOUR session ends and a
  successor continues. The server REFUSES one whose description lacks
  `## Verify before trusting`, `## Waiting on the operator` and `## Cannot testify`, each with
  at least one line ("nothing" is valid), so the successor can check your claims. Find them
  with `list_tasks(task_type="HND")`.
- **Project** (`create_project`): actionable, multi-step dev work. Pass a `project_type`
  (FE/BE/INF/...), NEVER `TSK`; omit `series_number` (serials auto-assign upward on ONE
  tenant+product line shared with tasks). An unknown type is rejected with the valid list.
  Projects are created **inactive**; launching one makes it active (section 6).
- **Update**: `list_projects` to find it, then `update_project`.
- **A task turned out to be a project? PROMOTE it -- never rebuild it.**
  `promote_task_to_project(task_id)` converts it atomically (subtasks and roadmap card
  re-point; the task row is DELETED, so carry the returned `project_id`). The project lands on
  the task's own product, **inactive and UNTYPED**: tag it with
  `update_project(project_id, project_type='BE'|...)`.

## 2. Chains -- one effort split into ordered, dependent steps
Use a chain only when step b cannot start until step a ships.
**All steps share ONE numeric serial** ordered by a suffix (`BE-6018a -> BE-6018b -> INF-6018c`;
each keeps its own type).
Create step `a` WITHOUT `series_number` but WITH `suffix='a'`, read the assigned number, then
create `b`, `c`... with that explicit `series_number`; each description cites the previous
alias and carries the Edition Scope line, a testable Definition of Done, a reuse map, the
hand-off and what is out of scope.

**Run linked projects as a chain HEADLESS -- you become the conductor.** When the user asks
to RUN / LINK / JOIN / CHAIN two or more EXISTING projects into one back-to-back run, do NOT
stage them one at a time: `link_projects(project_ids=[...], execution_mode="subagent")`.
- Resolve names to UUIDs first with `list_projects`. `execution_mode` is REQUIRED and the
  USER's choice -- ask, never guess: `"subagent"` (each sub-orchestrator runs its workers in
  this session) or `"multi_terminal"` (one terminal per agent, coordinated over the Message
  Hub). Omitted, the tool declines with `EXECUTION_MODE_REQUIRED`. A chain needs >= 2 open projects.
- Invoking it TURNS YOUR SESSION INTO THE CONDUCTOR (it returns `conductor_agent_id`,
  `conductor_job_id` and a `next_action`). Bootstrap with
  `get_staging_instructions(job_id=<conductor_job_id>)`: stand up the Hub thread, author the
  chain mission, stage each member, then complete_job to end staging. THEN STOP -- report the
  plan, ASK the user which GO door they want (they say go here, or press "Implement Chain"),
  and wait for their explicit GO; do NOT drive yet. After the user says go, drive project by
  project on the `get_workflow_status` `ready_to_advance` gate to the series-summary finale.
- A chain is multi-PROJECT, single-user -- not a Team. `unlink_projects(run_id=...)` releases
  the members not yet run. The run record (`resolved_order`, `current_index`,
  `project_statuses`) is the crash-resume ground truth: a fresh session reads it and keeps
  driving; both doors write it through one service.
- **In `multi_terminal`, you may nudge -- but the Hub carries the message.** A native
  session-to-session nudge is allowed in addition to the Message Hub, never instead of it:
  post to the Hub first, treat the nudge as unacknowledged, and look the peer's address up
  again right before each send.

## 3. Edition Scope -- mandatory on every project
Every project description (and every commit it produces) states **`Edition Scope: CE | SaaS |
Both`**: CE = self-hosted core, SaaS = hosted/billing/multi-org, Both = ships to each.

## 4. Reads -- cheap-first routing
- Find a project by name/alias: `list_projects(summary_only=true)` (the id field is
  `project_id`). One project's description/mission: `get_context(product_id, project_id,
  categories=["project"])`. Many in detail: `list_projects(mode="planning")`; `mode="audit"`
  adds memory headlines, `mode="forensic"` is the heavy call. Prefer modes over numeric depth.
- "Have we solved X before?": `search_memory(query, tag?)` (keyword search of the 360
  memory). `get_context(["memory_360"])` is recent-N by recency; `list_threads` is Hub chat.
- Tasks: `list_tasks(mode="summary", filters={...})`; `task_type` `"TSK"` or `"HND"`.
  Roadmap: `get_roadmap`, `save_roadmap`, `remove_roadmap_items`. List paging, `counts` and
  `truncation.next_cursor` are explained in `list_projects`' own description; `hidden` is UI
  declutter only.
- `get_context` categories and their token costs are listed in its own description.
- **Serials:** **`TSK-nnnn` and `HND-nnnn` are both TASKS**; a typed alias (`BE-`, `FE-`,
  `INF-`, ...) is ALWAYS a project, and a bare serial (`0017`) is a project converted from a
  task, awaiting a type. The prefix is the only disambiguator.

## 5. Writes -- which tools, and the universal rules
- **Never pass `tenant_key`** -- the security layer injects it from auth.
- Creates need a product (section 1); updates (`update_project`, `update_task`,
  `update_project_mission`) address one row BY ID and never read product context. The list
  reads fall back to the default product when `product_id` is omitted.
- The dashboard updates live via WebSocket; do NOT fabricate a URL.
- **`update_project` status moves:** `active`/`inactive` start and pause; `parked` sets a
  project aside (resumable); `cancelled` abandons it; `completed` FINISHES a solo project and
  needs a closeout first (else `CLOSEOUT_BLOCKED`, or `force=true` to abandon without one);
  `superseded` REQUIRES `successor_project_id`. A chain member is finished by its conductor.
  `series_number` / `suffix` reposition a project inside a chain; `project_type` retags it.
- **Status vocabulary** (the only values the update tools accept):

  | Entity  | Values |
  |---------|--------|
  | project | `active` `inactive` `parked` `completed` `cancelled` `superseded` |
  | task    | `pending` `in_progress` `on_hold` `blocked` `completed` `cancelled` |
  | thread  | `open` `active` `resolved` `closed` |

## 6. Lifecycle (orchestrated work)
create project -> stage it -> **stop at the human gate** -> implement -> close out.
- `stage_project(project_id, mode)` -- `mode` is EXECUTION STYLE ONLY: 'subagent' (one
  orchestrator session drives its workers in-session) or 'multi_terminal' (a terminal per
  agent). Never ask which coding tool the user runs; the server detects it. The reply starts
  staging: get_staging_instructions, save the mission and worker assignments, complete_job to
  end staging, then STOP for the user's explicit approval to implement.
- `unstage_project(project_id)` -- undo staging before implementation starts (then
  `stage_project` again); to abandon, `update_project(project_id, status='cancelled')`.
- `launch_implementation(project_id, mission)` -- records the user's explicit go and opens
  the implementation gate (making an inactive project active). Gated by the account's
  Headless setting, OFF by default: then a human presses Implement in the dashboard and this
  call returns a structured refusal naming the setting. Idempotent.
- In subagent mode the orchestrator that staged in THIS session continues with
  `get_job_mission(job_id=<its orchestrator job>)` once the gate is open (the launch reply names
  it). `get_implementation_prompt(project_id)` is the prompt for a NEW session or a
  multi_terminal run; before the gate opens it returns `gate_not_passed` with the next step.

**Workers get their role from the server, not from your disk.** Every spawned agent's
`get_job_mission` carries `agent_identity` and an `agent_profile` (role, model/effort hints,
rules); there are no agent template files to install. `inherit` = same as the orchestrator.

**Wedged project? diagnose before you guess:** `diagnose_project_state(project_id)` is
READ-ONLY and names the stuck condition with a `suggested_actions` recovery step.

## 7. complete_job -- one tool, three phases (the response self-explains)
The server picks the phase; read the reply's `phase`, `message` and `next_action`.
- **staging_end**: staging is done; `staging_directive.action='STOP'`. Stop; implementation
  starts when the user goes. No memory or closeout here.
- **closeout**: an implementation orchestrator wrapping up. Its own closeout TODO auto-acks.
  The canonical closeout sequence is `complete_job` -> `write_project_closeout`, which writes
  the single `project_closeout` 360 entry itself, so a separate `write_memory_entry` for the
  completion is REDUNDANT (it double-writes); keep `write_memory_entry` for other records, such
  as a conductor's series-summary. A SOLO project then needs
  `update_project(status='completed')` (the archive lifecycle; refused with `CLOSEOUT_BLOCKED`
  without a closeout); a chain member does not.
- **deliverable**: a worker recording its result; the orchestrator reviews it, closes it with
  `finalize_job(job_id)`.
Closeout arguments (`git_commits`, the 16 `tags`, caps, `force`) are in
`write_project_closeout`'s own description. `spawn_job` details (two-phase spawn, `phase`,
`predecessor_job_id`, `inline_seed`) are in its description.

## 8. Agent Message Hub -- the persistent chat board (BBS)
A message board for agent<->agent<->user chat that outlives any one job. Tenant isolation is
automatic: never pass `tenant_key`; you cannot see or post to another tenant's threads.
Nine tools:
- `create_thread(subject=..., creator_id=<your agent_id>)` returns a shareable **`CHT-####`**
  id; pass `project_id` and `product_id` so it can be found later.
- `join_thread(thread_id, agent_id)` claims your identity (re-joining is a no-op).
- `post_to_thread(thread_id, content, from_agent=...)` broadcasts; `to_participant=<id>` DMs;
  `pass_baton_to` hands the turn with the post; `set_status` resolves or closes.
- `update_thread(thread_id, ...)` renames, retags or restatuses without posting.
- `get_my_turn(agent_id)` lists chats awaiting YOU (`wait_seconds=45` parks on it);
  `set_next_actor(thread_id, to=...)` hands the turn on.
- `list_threads(...)` finds chats by `CHT-####`, subject, participant or content.
- `get_thread_history(thread_id)` reads the timeline (read-only unless `mark_read=true`).
- `get_participant_liveness(thread_id)` shows who is still active before you reassign work.
Post with `loop_directive=true` to keep addressed agents checking until the thread is resolved.

**Hub etiquette (five rules):**
1. `join_thread` BEFORE anyone names you (the baton is refused for an unjoined id).
2. `from_agent` is YOUR id on every post; `to_participant` is one joined id, or omit it.
3. Hand work on explicitly: `pass_baton_to=<id>` or `requires_action=true` + `to_participant`.
4. Park on `get_my_turn(agent_id, wait_seconds=45)` only when you asked something or hold the baton.
5. End it: `set_status="resolved"` (answered) or `"closed"` -- once.

## 9. request_approval -- the human gate, and how it clears
`request_approval(job_id, project_id, reason, options)` parks a decision and flips you to
`awaiting_user`. Two doors clear it through one write: the ApprovalCard in the project's
CloseoutModal, or `decide_approval(approval_id, option_id)` after the user chose in your
terminal. `set_agent_status` and `report_progress` cannot clear it. With Headless OFF only the
dashboard can answer (`decide_in: "dashboard"`): wait, and do not ask in chat.

## 10. Product context and setup
`update_product_context` merge-writes structured product fields (split a large analysis
across calls, `emit_completion=true` on the last; `force=true` to overwrite);
`apply_context_tuning` writes reviewed proposals; `giljo_setup` installs the /giljo skill and
the marker block, naming your own coding tool in `platform`. Their parameters are in their
own descriptions. Every reply carries `_meta.skills_version`; when it is ahead of what is
installed, offer to re-run `giljo_setup`.
"""


def build_giljo_guide() -> dict[str, Any]:
    return {"guide": _GUIDE_TEMPLATE.replace("{product_name}", PRODUCT_NAME)}
