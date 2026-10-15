# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import textwrap

from giljo_mcp.services.next_action import STAGING_COMPLETE
from giljo_mcp.services.protocol_sections.chain_nudge import suborch_nudge
from giljo_mcp.services.protocol_sections.orchestrator_body import find_chain_mission_block, render_chain_driver_model


def _build_ch_sub_orchestrator(
    *,
    run_id: str,
    position: int,
    n_projects: int,
    execution_mode: str | None,
    chain_mission: str | None = None,
    phase: str | None = None,
    project_id: str | None = None,
    staging_status: str | None = None,
) -> str:
    mode = execution_mode or "multi_terminal"
    _section, impl_nudge = suborch_nudge(mode)

    if phase == "implementation":
        if staging_status == STAGING_COMPLETE:
            staging_record = """2.-4. STAGING -- ALREADY COMPLETE (server record, staging_status: staging_complete).
   Your project mission and agent team are on record; do not stage again. If a
   staging-end complete_job was refused, that is expected here: continue."""
        else:
            staging_record = f"""2.-4. STAGING -- the server has not recorded this project's staging as complete
   (staging_status: {staging_status or "unknown"}). Check get_workflow_status(project_id) for your
   mission and agent team before you implement; stage what is missing first."""
        staging_steps = f"""{staging_record}
   The Hub thread is get_context(categories=["chain"]) -> hub_thread_id. Your chain-mission
   contract slice is not re-shipped here -- fetch the full chain mission via
   get_context(categories=["chain"]) if you need cross-project context.
{_escalation()}{impl_nudge}"""
        return _render_ch_sub_orchestrator(
            run_id=run_id, position=position, n_projects=n_projects, mode=mode, staging_steps=staging_steps
        )

    own_block = find_chain_mission_block(chain_mission, position, project_id) if chain_mission else None
    if own_block is not None:
        contract_block = (
            "   The conductor wrote your contract into the CHAIN MISSION. YOUR project's\n"
            "   slice (consumes / produces / must leave) is inlined below; author your\n"
            "   project mission from it plus your own context. For cross-project awareness\n"
            "   (the other projects' contracts) fetch the FULL chain mission via\n"
            '   get_context(categories=["chain"]).\n\n'
            f"   ---- YOUR CHAIN-MISSION SLICE (P_{position}, live) ----\n"
            f"{own_block}\n"
            "   ------------------------------"
        )
    elif chain_mission:
        contract_block = (
            "   The conductor wrote your contract into the CHAIN MISSION, but it has no contract\n"
            f"   block for this project (no P_{position} / P{position} header and no header naming\n"
            "   your project id). The FULL chain mission follows; find your project's part in\n"
            "   it and author your project mission from that plus your own context.\n\n"
            "   ---- FULL CHAIN MISSION (live) ----\n"
            f"{chain_mission}\n"
            "   ------------------------------"
        )
    else:
        contract_block = (
            "   The conductor wrote your contract into the CHAIN MISSION. Fetch it LIVE\n"
            "   with get_context(categories=[\"chain\"]) -- the 'chain' category resolves\n"
            "   YOUR active run and returns the current chain mission; lift YOUR project's\n"
            "   slice (consumes / produces / must leave) and author your project mission\n"
            "   from that plus your own context."
        )

    staging_steps = f"""2. READ YOUR CONTRACT -- Read the CHAIN MISSION (it carries your project's contract)
   and your own project + product context via get_context. Then AUTHOR YOUR OWN
   project mission with update_project_mission from that contract plus your context.
   The conductor did NOT write your project mission; you do.
{contract_block}

3. STAGE -- Write your project mission (update_project_mission), then choose and
   spawn your agents (spawn_job), exactly like a normal solo orchestrator staging.
   NOTE (workers-inert): workers you spawn_job during staging are INERT until you
   complete_job (staging-end) THEN get_job_mission; do NOT launch them before that
   gate. A chain worker that calls get_job_mission earlier is told to RE-POLL (never
   "click Implement in the dashboard" -- chain mode has no human gate), so it
   auto-activates the instant you end staging. Launch your workers in the
   IMPLEMENTATION phase (step 6), after staging-end.

4. END STAGING + POST -- call complete_job (staging-end). Find the Hub thread:
   get_context(categories=["chain"]) -> hub_thread_id; post a "staging-complete" note there so the
   conductor and the user can follow your run. The Hub is effectively LOG-ONLY: posting
   pushes no reply, so if you ever need a conductor decision, POLL the Hub yourself with
   get_thread_history / get_my_turn -- do not wait for a pushed answer.
{_escalation()}{impl_nudge}"""
    return _render_ch_sub_orchestrator(
        run_id=run_id, position=position, n_projects=n_projects, mode=mode, staging_steps=staging_steps
    )


CHAIN_ESCALATION_PATH = (
    "ESCALATION -- on a blocker or a decision you cannot make alone, post it to the Hub thread "
    "AND state it in this session, then POLL the thread yourself (get_thread_history / "
    "get_my_turn). Whoever drives the chain answers: the conductor on the Hub when one runs, "
    "the user on the Hub or here. There is no Implement click to wait for."
)


def _escalation() -> str:
    return textwrap.fill(CHAIN_ESCALATION_PATH, width=88, initial_indent="   ", subsequent_indent="   ")


def _render_ch_sub_orchestrator(*, run_id: str, position: int, n_projects: int, mode: str, staging_steps: str) -> str:
    nudge_section, _brief = suborch_nudge(mode)
    return f"""════════════════════════════════════════════════════════════════════════════
       CH_SUB_ORCHESTRATOR: COMBINED CHAIN FLOW (YOU ARE NOT THE CONDUCTOR)
════════════════════════════════════════════════════════════════════════════

1. IDENTITY -- You are the sub-orchestrator for project {position} of {n_projects}
   in a sequential chain (run_id: {run_id}). You run a COMBINED staging+implementation
   flow -- there is NO separate human Implement click for you. (Execution mode = {mode},
   resolved at staging.)
{render_chain_driver_model("   ")}
   SCOPE IS HANDED -- do NOT hunt for work.
   Where the solo protocol below tells you to scan for a project to continue, or a
   duplicate to merge, IGNORE it: you adopt no new project and merge none. This chapter
   wins over any contradicting solo default.
   TOOLSEARCH BOOTSTRAP (Claude Code): the generic orchestrator bootstrap query OMITS
   the Hub tools you are REQUIRED to use below. ADD join_thread, post_to_thread,
   get_thread_history (alongside list_threads) to your FIRST ToolSearch query, so you
   load them in ONE round-trip instead of paying a second ToolSearch mid-staging.
{nudge_section}
{staging_steps}

5. CONTINUE TO IMPLEMENTATION (no gate, no wait) -- There is NO per-project gate and you
   do NOT call any launch tool (you do not have one and must not). Being started (by the
   user or the conductor) already released you.
   After staging-end, call get_job_mission ONCE, WITHOUT your boot
   protocol_etag: the implementation protocol differs from this staging one, so the full
   block always comes back and you need all of it. Keep the NEW protocol_etag it returns
   for any later refetch. It returns your implementation protocol immediately and flips
   you to working. Do NOT wait for a human, do NOT wait on the
   dashboard, and do NOT sleep-poll a gate: a single get_job_mission carries you straight
   into implementation.

6. IMPLEMENT -- drive your agents to completion, exactly like solo implementation.

7. CLOSE OUT + REPORT -- call complete_job(...) FIRST (this closes your orchestrator
   execution so the closeout readiness gate passes), THEN write_project_closeout(...)
   (commit SHA). This order matches the solo PHASE 3 closeout and the server-enforced
   gate -- the INVERSE raises COMPLETION_BLOCKED (your execution is still open when the
   readiness check runs) and stalls every chain advance. write_project_closeout is the
   chain's ADVANCE signal: when it RETURNS it has stamped the server gate
   (ready_to_advance / project_closeout_at) -- never skip it or the chain stalls.
   ONLY AFTER write_project_closeout RETURNS, post DONE to the Hub thread, as the LAST
   thing you do, then STOP: you never start the next project. Do NOT announce "closed out" /
   "clear to advance" BEFORE that return: the chain advances on the SERVER gate, not your
   message, so a DONE posted while
   the gate is still false races your own closeout and misleads a conductor that trusts
   the Hub. The Hub post is human-facing courtesy; write_project_closeout is the real
   signal, and the two must agree (post only once the gate is set).
────────────────────────────────────────────────────────────────────────────
"""
