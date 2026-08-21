# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""GiljoAI cross-tool guide -- the single discoverable "recipe" surface.

INF-6049a: this is the judgment layer that used to live across the per-platform
slash commands (gil_add / gil_get / gil_chain / gil_get_reference). The slash
fleet was collapsed to one thin ``/giljo`` command whose body is "call
``get_giljo_guide`` (bare) and follow it." The content here is consolidated
verbatim-in-spirit from those slash bodies -- it is NOT new policy.

Static, tenant-independent text: no DB, no tenant_key, no active product needed
to READ the guide (the recipes it describes do require an active product).
"""

from __future__ import annotations

from typing import Any


# Kept under ~1-2k tokens on purpose: a fresh agent (no CLAUDE.md, no skills)
# reads this once to become competent at the project/task tool surface.
_GUIDE = """\
# Giljo HQ -- how to drive the project/task tools

You are talking to the GiljoAI dashboard over MCP. This guide is the routing +
judgment layer for the create/read/update tools. Call it once, then act.

## 0. Operating principle -- server-authored artifacts are VERBATIM
When a tool response hands you a ready-made artifact to write or run -- a launcher
script, a command block, a file body marked "copy verbatim" -- write/run it
BYTE-FOR-BYTE. Do NOT reformat, re-quote, "tidy", or convert it to an idiomatic form
(e.g. turning a shell command's quoted argument string into array form, or
normalizing a launcher script's line endings): its quoting is load-bearing and
self-contained, and the server already resolved everything it knows. There is
nothing for you to fix -- changing it is the single most common way these flows
break.

## 1. Project vs task -- pick the right create tool

**First, name your product.** Both create tools take an optional `product_id`. Omit it
and the new task/project binds to whatever product is ACTIVE at that instant -- and the
active product is shared, mutable state: another session, or the user switching products
in the dashboard, changes it under you, and your next create silently follows. **If you
know which product you are working on -- and a staged orchestrator always does, it is in
your mission -- PASS `product_id`.** Then the binding is yours and no one can move it.
A `product_id` that is not one of your own products is refused and nothing is created;
it never quietly falls back to the active product. Either way the create response tells
you where it landed (`product_id` + `product_name`) -- read it back and you have caught
a wrong filing for free.

- **Task** (`create_task`): technical debt, a TODO, a bug, a small fix, a scope-creep
  punt. Every task is auto-tagged the reserved **`TSK`** type -- there is no task
  type to choose and `task_type` is accepted-but-ignored. The serial is
  auto-assigned (you do NOT pick the number).
- **Project** (`create_project`): an actionable, multi-step body of dev work. Pass a
  `project_type` (FE/BE/INF/IMP/...), NEVER `TSK` (task-only, excluded from
  `valid_types`). Numbering is automatic -- omit `series_number`; the serial
  auto-assigns continue-upward on ONE global (tenant+product) line shared by every
  project type AND tasks. Unknown `project_type` is rejected with the list of valid
  types in the error -- re-map and retry. Projects are created **inactive**; the user
  activates/launches from the dashboard.
- **Update**: to change an existing project, `list_projects` to find it, then
  `update_project` with the new values.
- **A task turned out to be a project? PROMOTE it -- never rebuild it.**
  `update_task(task_id, convert_to_project=true)` runs the same conversion as the
  dashboard wizard, in one atomic step: the project is created from the task, subtasks
  and any roadmap card re-point to it (same roadmap position), and **the task row is
  DELETED** -- that `task_id` stops resolving, so drop it and carry the returned
  `project_id`. Add `title` to name the project. Do NOT combine it with any other field
  (`status`, `priority`, ...): the task row is gone, so such a write would be discarded,
  and the call is refused instead. The promoted project is **inactive and UNTYPED** --
  tag it with `update_project(project_id, project_type='BE'|'FE'|...)`, then the user
  activates it. The promoted project lands on **the task's own product**, not on
  whichever product is currently active, and the response names it (`product_id` +
  `product_name`) so you can confirm where it went. Do NOT hand-build the equivalent
  (`create_project` + complete the task): that keeps the task, mints a different
  serial, and orphans the roadmap card.

## 2. Chains -- one effort split into ordered, dependent steps
Use a chain when one effort is genuinely multi-step with hard dependencies (step b
can't start until step a ships). NOT for independent parallel work.
- **All steps share ONE numeric serial** (e.g. `6018`) and are ordered by a suffix
  `a`, `b`, `c`, `d`... in run order. Each step keeps its OWN `project_type`, so a
  chain can read `BE-6018a -> BE-6018b -> INF-6018c`. The shared number means "these
  belong together"; the suffix means "run in this order."
- **Creation procedure (gets the shared serial right):**
  1. Create step `a` WITHOUT `series_number` but WITH `suffix='a'` -- let the shared
     counter assign the next free number.
  2. Read the assigned `series_number` from the response (or parse the
     `taxonomy_alias`, e.g. `BE-6018a`).
  3. Create the remaining steps with that EXPLICIT `series_number` and suffixes
     `b`, `c`, `d`...; each step's description references the previous step's alias.
- Each step's description is a real work order: a chain header (step n of total, run
  order, depends-on/blocks), the Edition Scope line (see below), a testable Definition
  of Done, a reuse map, the hand-off to the next step, and what's out of scope.

**Run linked projects as a chain HEADLESS -- you become the conductor.** Intent
routing: when the user asks to RUN / LINK / JOIN / CHAIN two or more EXISTING projects
into one autonomous back-to-back run (they paste project UUIDs or names), do NOT stage
them one at a time -- start a chain run:
  `start_chain_run(project_ids=[...], execution_mode="subagent")`
- Resolve any NAMES to UUIDs FIRST via `list_projects` (the tool takes `project_ids`,
  never names). `execution_mode` is REQUIRED -- the two values are `"subagent"` (one
  orchestrator session drives the workers; the normal headless choice) and
  `"multi_terminal"` (one terminal per agent). A chain needs >= 2
  distinct, non-terminal projects.
- The call returns `conductor_agent_id`, a `conductor_job_id`, and a `next_action`.
  Invoking it TURNS YOUR SESSION INTO THE CONDUCTOR for the whole run -- you drive it,
  you do not hand off to anyone.
- Bootstrap your conductor protocol with `get_staging_instructions(job_id=<the
  conductor_job_id>)`: it returns the chain-drive chapters (stand up the Hub thread,
  author the chain mission, stage each member, then complete_job to end staging). THEN
  STOP -- report the staged plan and the chain mission to the user and WAIT for their
  explicit GO; do NOT drive yet. After the user says go (or presses "Implement Chain"),
  proceed and drive the run project by project, advancing on the `get_workflow_status`
  `ready_to_advance` gate, through to the series-summary finale.
- A chain is multi-PROJECT, single-user -- it is NOT a Team.

## 3. Edition Scope -- mandatory on every project
Every project description (and every commit it produces) MUST state its edition
scope explicitly: **`Edition Scope: CE | SaaS | Both`**. CE = self-hosted core;
SaaS = hosted/billing/multi-org; Both = ships identically to each.

## 4. Reads -- cheap-first routing
- **Find a project by name/alias** -> `list_projects(summary_only=true)` (light:
  project_id, name, taxonomy_alias, status, dates). The id field is `project_id`,
  never `id`.
- **One project's description/mission** -> `get_context(product_id, project_id,
  categories=["project"])` (~300 tokens).
- **Many projects in detail** -> `list_projects(mode="planning")` (adds
  description/mission); `mode="audit"` adds memory headlines; `mode="forensic"` is
  the heavy full-memory archaeology call -- use only when truly needed. Prefer these
  named modes over numeric depth.
- **Search past work ("have we solved X before?")** -> `search_memory(query, tag?)`
  keyword-searches the 360 memory (summaries/outcomes/decisions/tags) and returns
  ranked headlines. Distinct from `get_context(["memory_360"])` (recent-N by recency,
  not search) and `search_threads` (Hub chat, not memory).
- **Tasks** -> `list_tasks(mode="summary", filters={...})`; `mode="full"` for bodies.
  Every task is `TSK`, so a non-TSK `task_type` filter returns nothing -- normally
  omit it. `hidden` is UI declutter only; agents see hidden and visible alike.
- **Serials -- the prefix tells task from project:** **`TSK-nnnn` is ALWAYS
  a task** (`create_task` forces the reserved `TSK` tag; every task renders `TSK-nnnn`).
  **A typed non-TSK alias (`BE-`, `FE-`, `INF-`, ...) is ALWAYS a project.** Converting a
  task to a project **strips the type** -- the new project is UNTYPED and renders a bare
  serial (e.g. `0017`) until the user tags it, so a bare-serial alias = a project
  converted from a task, awaiting a taxonomy. `create_project` rejects `TSK`, so a project
  is never `TSK`-typed. (A bare `TAG-nnnn` lookup still resolves across both tables by
  serial; the prefix is the disambiguator -- do NOT infer task-vs-project any other way.)

## 5. Writes -- which tools, and the universal rules
- **Writes:** `create_project`, `create_task`, `update_project`, `update_task`,
  `update_project_mission`. **Reads:** `list_projects`, `list_tasks`, `get_context`.
- **Never pass `tenant_key`** -- the security layer injects it from auth.
- **Creates need a product; updates do not.** `create_project` / `create_task` accept
  an explicit `product_id` (prefer it -- see section 1), and a create that omits it
  binds to the ACTIVE product. The update tools (`update_project`, `update_task`,
  `update_project_mission`) address one row BY ID inside your tenant and do not read
  the active product at all -- so switching products, or having none selected, never
  blocks an edit. The LIST reads (`list_projects`, `list_tasks`) do scope to the active
  product. If a read or a create reports "No active product", tell the user to activate
  one in the dashboard rather than retrying.
- On success, the dashboard updates live via WebSocket -- do NOT fabricate a URL.

## 6. Lifecycle (orchestrated work)
create project -> stage it -> **stop at the human gate** (the user reviews the
dashboard and presses Implement) -> implement -> close the project + write memory
at completion.

Drive it with two tools:
- `stage_project(project_id, mode)` -- mode is multi_terminal / claude / codex /
  gemini / antigravity. Returns the orchestrator staging prompt. When it returns,
  **STOP**: staging never auto-executes. Tell the user to review the staged plan in
  the dashboard and press Implement.
- `implement_project(project_id)` -- call this only AFTER the user has pressed
  Implement. If the gate has not cleared it returns a structured error
  (status='gate_not_passed') telling you the exact next action: either run
  stage_project first, or ask the user to press Implement in the dashboard. There is
  no bypass -- the human gate is intentional.

**Recovery -- when a project looks wedged, diagnose before you guess.** If a project
seems stuck (agents blocked/silent, nothing advancing, a gate won't clear, or you
can't tell why closeout isn't ready), call `diagnose_project_state(project_id)`
FIRST. It is READ-ONLY and reports the status, the execution_mode + staging/implement
gates, agent/job status counts, closeout readiness (`can_close` + blockers), and the
detected `stuck_conditions` (e.g. execution_mode_not_selected, no_agents_spawned,
all_agents_finished_project_still_open, blocked_agents, silent_agents,
awaiting_user_approval) each with a `suggested_actions` recovery step. Use its output
to pick the next move instead of guessing.

## 7. complete_job -- one tool, three phases (the server decides; the response self-explains)
`complete_job` is overloaded three ways, switched on hidden server-side phase. You do
NOT need to know which phase you are in -- the response tells you via its `phase`,
`message`, and `next_action` fields. The three meanings:
- **staging_end** (`phase='staging_end'`): a staging orchestrator finished staging.
  The server flips the project to `staging_complete` (lighting up the Implement button)
  and returns `staging_directive.action='STOP'`. STOP this session -- a human presses
  Implement to start a fresh implementation session. Do NOT write memory/closeout here.
- **closeout** (`phase='closeout'`): an implementation-phase orchestrator wrapping up.
  The self-referential closeout TODO (the one that says "call complete_job") AUTO-acks --
  no acknowledge flag exists or is needed. The canonical
  closeout sequence is `complete_job` -> `write_project_closeout` (registered tool names).
  `write_project_closeout` takes the `summary` / `key_outcomes` / `decisions_made` itself and
  writes the single `project_closeout` 360 entry as it finalizes the project -- so a separate
  `write_memory_entry` for the completion is REDUNDANT; do NOT add one (it double-writes the
  360). Keep `write_memory_entry` for OTHER, non-closeout 360 records (cross-session
  learnings); the chain conductor's series-summary is one such legitimate call, unaffected.
  On a SOLO project the closeout writes the 360 entry but deliberately does NOT change the
  project's own status, so there is a third step: `update_project(status='completed')`. That
  runs the whole archive lifecycle (deactivate, terminal status with the completion date
  stamped, spawned agents moved from `complete` to `closed`) -- the same thing the dashboard's
  Archive button does. A CHAIN MEMBER needs no third step: its closeout already flips the row
  and the conductor advances the run.
- **deliverable** (`phase='deliverable'`): a worker agent (implementer/tester/...) recording
  its result. No phase magic -- the orchestrator reviews and closes your job.

## 8. Agent Message Hub -- the persistent chat board (BBS)
A tenant-isolated message board for agent<->agent<->user chat that outlives any one job.
Use it for cross-session / cross-PC coordination and standalone topics not tied to a
project. Tenant isolation is automatic (never pass `tenant_key`); every read/write is
scoped to YOUR tenant -- you cannot see, search, or post to another tenant's threads.
Eight tools:
- **Start a chat:** `create_thread(subject=..., creator_id=<your agent_id>)` -> returns a
  shareable **`CHT-####` chat id**. Share that id so other agents can join. Pass
  `project_id` to anchor the chat to a project, or omit it for a standalone thread.
  Pass `product_id` to file the chat under a product -- that is the dimension
  `list_threads(product_id=...)` filters on below, so a chat created without it can
  never be found that way. Anchor to the product you are working under; omit only for
  a chat that genuinely belongs to no product.
- **Join:** `join_thread(thread_id, agent_id)` -- claim your identity on a chat so
  broadcast posts reach you (collision-safe; re-joining is a no-op).
- **Post:** `post_to_thread(thread_id, content, from_agent=...)` broadcasts to all
  participants; add `to_participant=<id>` to direct-message one. Posts are append-only.
  Pass `set_status="resolved"|"closed"` when the conversation is done. Add
  `pass_baton_to=<agent_id|user_id|'all'|'none'>` to hand the turn atomically with the
  post -- no separate `pass_baton` call needed.
- **The baton (`next_action_owner`):** `get_my_turn(agent_id)` lists the chats awaiting
  YOU; `pass_baton(thread_id, to=<agent_id|user_id|'all'|'none'>)` hands the turn on.
  AUTO-PASS: a directed action-request (`requires_action=true` + `to_participant`) hands
  the baton to that participant automatically unless you pass `pass_baton_to='none'`;
  broadcasts never move the baton unless `pass_baton_to` says so.
- **List / catch up:** `list_threads(...)` filters by status/owner/product/project;
  `get_thread_history(thread_id)` reads the full timeline (read-only -- it does NOT
  acknowledge anything).
- **Find a chat:** `search_threads(query)` matches by `CHT-####` serial, subject keyword,
  participant, or message content.
- **Loop on a chat:** to have addressed agents keep checking a chat until it is
  resolved/closed, post with `loop_directive=true` -- they loop/sleep on their normal
  wake interval until you set the thread `resolved`/`closed` (which stops them).

## 9. request_approval -- the HITL gate, and how it clears
`request_approval(job_id, project_id, reason, options)` creates a pending approval and flips
the calling agent to `status='awaiting_user'`. Use it at a gate that genuinely needs a human
choice (closeout with deferred findings, an ambiguous decision) -- `options` is a list of
`{id, label}` dicts presented to the user.
- **UI surface:** the dashboard shows a passive "needs input" pill (informational, NOT a
  clickable global banner). The decide buttons render inside the project's CloseoutModal via
  the ApprovalCard component -- users frequently miss this and respond verbally instead.
- **Clearing the gate:** ONLY `POST /api/approvals/{id}/decide` clears `awaiting_user` (the
  ApprovalCard button calls this). `set_agent_status` accepts only blocked/idle/sleeping, and
  `report_progress` does not auto-wake from `awaiting_user` -- neither can clear this gate. If
  the user responds verbally, guide them to open CloseoutModal and click the ApprovalCard
  option, or POST to the decide endpoint directly. The MCP server is passive here.
- **If your client supports it, you may be asked directly:** on a connection that negotiates
  MCP 2026-07-28 and declares the elicitation capability, `request_approval` ALSO returns the
  choice inline, and answering it resolves the gate through the same decide path. This never
  replaces the parked approval -- the row is created and you are flipped to `awaiting_user`
  first either way, so the dashboard remains able to clear it. On every other client the
  behaviour above is unchanged and the wait is yours to manage.
"""


def build_giljo_guide() -> dict[str, Any]:
    """Return the static cross-tool guide as a JSON-safe dict.

    No tenant context or DB access -- the guide is identical for every caller.
    """
    return {"guide": _GUIDE}
