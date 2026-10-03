# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections.chain_nudge import suborch_nudge
from giljo_mcp.services.protocol_sections.orchestrator_body import slice_chain_mission_for_position


def _build_ch_sub_orchestrator(
    *,
    run_id: str,
    position: int,
    n_projects: int,
    execution_mode: str | None,
    chain_mission: str | None = None,
    phase: str | None = None,
) -> str:
    mode = execution_mode or "multi_terminal"
    _section, impl_nudge = suborch_nudge(mode)

    if phase == "implementation":
        staging_steps = f"""2.-4. STAGING -- ALREADY COMPLETE. You authored your project mission, spawned your
   inert agent team, ended staging (complete_job), and posted a staging-complete note
   to the Hub thread (get_context(categories=["chain"]) -> hub_thread_id finds it). Your chain-mission
   contract slice is not re-shipped here -- fetch the full chain mission via
   get_context(categories=["chain"]) if you need cross-project context. ESCALATION unchanged: the CONDUCTOR
   is your escalation path, NOT the user -- post blockers to the Hub thread and POLL
   it yourself (get_thread_history / get_my_turn) for the answer; do NOT stop to ask
   the user directly and do NOT return to the dashboard.{impl_nudge}"""
        return _render_ch_sub_orchestrator(
            run_id=run_id, position=position, n_projects=n_projects, mode=mode, staging_steps=staging_steps
        )

    if chain_mission is not None:
        sliced = slice_chain_mission_for_position(chain_mission, position)
        contract_block = (
            "   The conductor wrote your contract into the CHAIN MISSION. YOUR project's\n"
            "   slice (consumes / produces / must leave) is inlined below; author your\n"
            "   project mission from it plus your own context. For cross-project awareness\n"
            "   (the other projects' contracts) fetch the FULL chain mission via\n"
            '   get_context(categories=["chain"]).\n\n'
            f"   ---- YOUR CHAIN-MISSION SLICE (P_{position}, live) ----\n"
            f"{sliced}\n"
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
   ESCALATION -- the CONDUCTOR is your escalation path, NOT the user. On a blocker or a
   decision you cannot make alone, POST it to this Hub thread for the conductor; do NOT
   stop to ask the user directly and do NOT return to the dashboard. (The conductor is
   the escalation SINK and polls the Hub for exactly this.){impl_nudge}"""
    return _render_ch_sub_orchestrator(
        run_id=run_id, position=position, n_projects=n_projects, mode=mode, staging_steps=staging_steps
    )


def _render_ch_sub_orchestrator(*, run_id: str, position: int, n_projects: int, mode: str, staging_steps: str) -> str:
    nudge_section, _brief = suborch_nudge(mode)
    return f"""════════════════════════════════════════════════════════════════════════════
       CH_SUB_ORCHESTRATOR: COMBINED CHAIN FLOW (YOU ARE NOT THE CONDUCTOR)
════════════════════════════════════════════════════════════════════════════

1. IDENTITY -- You are the sub-orchestrator for project {position} of {n_projects}
   in a sequential chain (run_id: {run_id}). You own ONLY this project. You run a
   COMBINED staging+implementation flow -- there is NO separate human Implement click
   for you. (Execution mode = {mode}, resolved at staging.)
   SCOPE IS HANDED -- the conductor assigned you this ONE project; do NOT hunt for work.
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
   do NOT call any launch tool (you do not have one and must not). The conductor's spawn
   already released you. After staging-end, call get_job_mission ONCE, WITHOUT your boot
   protocol_etag: the implementation protocol differs from this staging one, so the full
   block always comes back and you need all of it. Keep the NEW protocol_etag it returns
   for any later refetch. It returns your implementation protocol immediately and flips
   you to working. Do NOT wait for a human, do NOT return to the
   dashboard, and do NOT sleep-poll a gate: a single get_job_mission carries you straight
   into implementation.

6. IMPLEMENT -- drive your agents to completion, exactly like solo implementation.

7. CLOSE OUT + REPORT -- call complete_job(...) FIRST (this closes your orchestrator
   execution so the closeout readiness gate passes), THEN write_project_closeout(...)
   (commit SHA). This order matches the solo PHASE 3 closeout and the server-enforced
   gate -- the INVERSE raises COMPLETION_BLOCKED (your execution is still open when the
   readiness check runs) and stalls every chain advance. write_project_closeout is the
   conductor's ADVANCE signal: when it RETURNS it has stamped the server gate
   (ready_to_advance / project_closeout_at) -- never skip it or the chain stalls.
   ONLY AFTER write_project_closeout RETURNS, post DONE to the Hub thread, as the LAST
   thing you do. Do NOT announce "closed out" / "clear to advance" BEFORE that return:
   the conductor advances on the SERVER gate, not your message, so a DONE posted while
   the gate is still false races your own closeout and misleads a conductor that trusts
   the Hub. The Hub post is human-facing courtesy; write_project_closeout is the real
   signal, and the two must agree (post only once the gate is set).
────────────────────────────────────────────────────────────────────────────
"""
