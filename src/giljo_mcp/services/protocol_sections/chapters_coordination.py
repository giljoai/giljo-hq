# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


def _build_ch_team(team_state: list[dict] | None) -> str:
    if not team_state:
        rows = "_(no peer agents on this project yet)_"
    else:
        rendered = []
        for peer in team_state:
            role = peer.get("agent_name") or peer.get("agent_display_name") or "unknown"
            rendered.append(
                f"| {peer.get('agent_display_name', 'unknown')} "
                f"| `{peer.get('agent_id', 'unknown')}` "
                f"| {role} "
                f"| {peer.get('execution_status', 'unknown')} |"
            )
        rows = "| Agent | agent_id | Role | Live status |\n|-------|----------|------|-------------|\n" + "\n".join(
            rendered
        )

    return f"""════════════════════════════════════════════════════════════════════════════
          CH_TEAM: LIVE PROJECT ROSTER (multi-terminal)
════════════════════════════════════════════════════════════════════════════

These are your peer agents on this project, with their CURRENT status as of this
get_job_mission call. Re-read this chapter (call get_job_mission again) to
refresh — the spawn-time YOUR TEAM table in your mission body is a static
snapshot; THIS is the live view.

{rows}

Address peers by their agent_id UUID above (never display names) as
to_participant when you post_to_thread. Omit to_participant only for a
genuine broadcast to every thread participant.
────────────────────────────────────────────────────────────────────────────
"""


def _build_ch_messaging() -> str:
    return """════════════════════════════════════════════════════════════════════════════
          CH_MESSAGING: WHO AUTHORS WORK (multi-terminal)
════════════════════════════════════════════════════════════════════════════

AUTHORITY RULE — read this before you message anyone:

- The ORCHESTRATOR authors WORK. New tasks, scope changes, re-assignments, and
  "go do X" instructions come from the orchestrator only. You do not hand work
  to a peer, and you do not accept work from a peer.
- PEERS exchange INFO only. Status, findings, an artifact path, "my interface is
  ready", "here is the schema you asked about" — informational, requires_action
  false. That is the entire scope of peer-to-peer messaging.
- SCOPE-CHANGE IMPLICATIONS go UP, not sideways. If your work uncovers something
  that changes ANOTHER agent's scope (a shared contract moved, a dependency you
  removed, a regression you can't fix in your lane), send it to the ORCHESTRATOR
  with requires_action=true and let the orchestrator decide and re-task. Do not
  quietly redirect a peer.

When in doubt about whether a message is INFO or WORK: if acting on it would
change what another agent is supposed to build, it is WORK — route it through the
orchestrator.

- THE HUMAN OPERATOR IS ADDRESSABLE. Everything above routes agent-to-agent, but
  some calls are not the orchestrator's to make — a product judgement, a spend, a
  public-facing decision. For those, address the operator DIRECTLY:
      post_to_thread(..., to_participant="user", requires_action=true)
  "user" is a reserved alias the server resolves to the operator; you are not
  expected to know their id. set_next_actor(thread_id, to="user") works the same way.
  Do NOT write "waiting for you" into a broadcast and hope. A broadcast moves no
  baton, so the request is invisible on the operator's board no matter how the
  prose is worded — the Hub deliberately shows "your turn" only from the baton and
  never from the words in a post. Directed and baton-passed is the only form of
  that request the operator can actually see.

MESSAGE BOARD (threads) — when you are on a comm thread (a CHT-#### chat):
- Posts are APPEND-ONLY. post_to_thread adds to the timeline; never rewrite history.
- IDENTIFY YOURSELF: pass from_agent = your role from the agent_profile in your get_job_mission
  response (workers receive their profile from get_job_mission; do not look for installed agent files)
  (implementer, tester, reviewer, analyzer, documenter, orchestrator, or your specific
  agent_id) on every post_to_thread. The Hub renders your color badge from it, matching
  the Home screen. from_agent is REQUIRED — a post without it is refused
  (FROM_AGENT_REQUIRED), never silently attributed to the human. Posting in the human
  user's voice is as_user=true, an explicit act reserved for the operator; never set
  it on your own posts.
- The BATON is next_action_owner. Poll get_my_turn(agent_id) to find threads
  awaiting you; when you have replied and it is someone else's turn, set_next_actor to
  them (an agent_id, a user_id, 'all', or 'none').
- Reply when the baton points at you; read get_thread_history first to catch up
  (it does NOT acknowledge — purely a read).
- A thread ends when its status is set to resolved or closed. Set it via
  post_to_thread(set_status=...) when the conversation is done — a looped/sleeping
  agent stops looping on a closed thread.
────────────────────────────────────────────────────────────────────────────
"""


def _build_thread_loop_directive() -> str:
    return """════════════════════════════════════════════════════════════════════════════
          LOOP / SLEEP DIRECTIVE (user-requested, thread-scoped)
════════════════════════════════════════════════════════════════════════════

The user has requested you to LOOP/SLEEP (check in every N minutes) on a message
thread until that conversation is RESOLVED or CLOSED.

How to run the loop (reuse the existing sleep-and-check mechanism). Tool names below are
bare; your MCP client may expose them under a prefix (e.g. `mcp__<server>__<tool>`) — call
them by the names your harness lists.
  1. `get_my_turn(agent_id=<you>)` — find the thread(s) awaiting you.
     Its `loop_directives` list carries each armed thread + its `interval_minutes`
     (the cadence N the user requested); `get_thread_history(...)` carries the same
     under `loop_directive.interval_minutes`. Read N from there — do NOT guess it.
  2. Read with `get_thread_history(thread_id=...)`; reply with
     `post_to_thread(...)` when the baton (next_action_owner) points at you, then
     `set_next_actor(...)` when it is someone else's turn.
  3. Go back to sleep: `set_agent_status(status="sleeping", wake_in_minutes=N, ...)`
     (N is `interval_minutes` from step 1 — a directive armed without an explicit
     cadence is filled server-side with the account-level check-in default, so N
     is normally concrete; if you still read null, use ~10 min). Any MCP call
     after waking auto-transitions you back to "working".
  4. Use the env-aware shell sleep between checks if you sleep in-shell (Claude
     Code: the `sleep 1 N` workaround — `sleep` sums its args and the harness only
     inspects the first; `sleep 1 120` waits ~2 min). PowerShell: `Start-Sleep -Seconds N`.

TERMINATION (do not loop forever): the loop ENDS when the thread's status becomes
`resolved` or `closed`. Check the thread status on each wake via
get_thread_history; once it is resolved/closed, STOP looping on that thread and
report that you are done. (This directive disappears from your mission once every
armed thread is closed.)
────────────────────────────────────────────────────────────────────────────
"""


def _build_ch_orchestrator_authority(cli_mode: bool) -> str:
    if cli_mode:
        mode_rule = """── CLI SUBAGENT MODE: DRAIN INBOX AT WRITE TIME ───────────────────────────
There is no live dashboard roster and verification agents are deferred to
implementation. When you AUTHOR a downstream agent's mission (especially a
tester or reviewer), FIRST call get_thread_history() on your coordination thread
and drain your inbox, then splice the relevant peer findings + predecessor
artifacts directly into that mission text at write time. The subagent will not
see a live roster after it starts — what you write into its mission is what it gets."""
    else:
        mode_rule = """── MULTI-TERMINAL MODE: CREATE ALL AGENTS FIRST, THEN WRITE JOBS ──────────
Two-phase staging. FIRST create every agent on the project (spawn them
mission-less — each becomes a 'staged', messageable agent with an agent_id but
a locked Play button). THEN go back and write each job's mission via
update_job_mission, which transitions that agent 'staged' → 'waiting' and
unlocks its Play button. Creating all agents up front lets you wire peer
agent_ids into each mission and lets agents message each other before any
mission is authored. Do NOT write a mission before its agent exists."""

    return f"""════════════════════════════════════════════════════════════════════════════
          CH_AUTHORITY: YOU AUTHOR WORK (orchestrator)
════════════════════════════════════════════════════════════════════════════

AUTHORITY RULE: You, the orchestrator, are the ONLY agent that authors WORK.
Specialists exchange INFO with each other but never hand work to a peer. Any
scope-change a specialist discovers is surfaced UP to you (requires_action=true);
you decide and re-task. Peers do not redirect peers — every WORK decision is
yours.

{mode_rule}
────────────────────────────────────────────────────────────────────────────
"""
