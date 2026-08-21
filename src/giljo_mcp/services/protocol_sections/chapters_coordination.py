# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Coordination protocol chapter builders (CH_TEAM, CH_MESSAGING, CH_AUTHORITY).

BE-6008 introduced three runtime-rendered coordination chapters that govern how
agents on a multi_terminal project see each other and who is allowed to author
work. They were originally added to chapters_reference.py, which pushed that file
to 799/800 lines and forced the docstrings to be condensed to fit under the CI
line ceiling (scripts/ci_guardrails.sh). They live here in their own topic-named
module so both files have headroom and the full WHY can be documented.

These chapters are the coordination contract between agents:
  * CH_TEAM (specialist) — the live peer roster, rendered fresh each
    get_job_mission call rather than baked in at spawn time.
  * CH_MESSAGING (specialist) — the authority rule from the worker's side:
    peers exchange INFO, only the orchestrator authors WORK.
  * CH_AUTHORITY (orchestrator) — the same authority rule from the
    orchestrator's side, plus the mode-specific staging mechanics.

BE-6215: CH_CONDUCTOR (the conductor addressability + directive-relay protocol,
BE-6131c) was FOLDED into CH_CHAIN_DRIVE (chapters_chain.py) — both chapters only
ever co-rendered in the drive phase, so the separate chapter was pure overhead. Its
``_build_ch_conductor_sequencing`` builder is removed; the relay protocol now renders
inline in CH_CHAIN_DRIVE from the conductor_agent_id + job_id it already receives.
"""

from __future__ import annotations


def _build_ch_team(team_state: list[dict] | None) -> str:
    """Build CH_TEAM: a LIVE roster chapter for a multi_terminal specialist.

    BE-6008: this chapter is rendered at READ time from the live execution rows
    on the project, not from the static "YOUR TEAM" header that was frozen into
    the mission body at spawn time. That distinction is the whole point — a
    specialist that re-calls get_job_mission sees its peers' CURRENT status
    (working / blocked / complete) instead of the snapshot from when it was
    first staged. Peers join, finish, and block over the life of a project; the
    spawn-time table goes stale immediately, this view does not.

    ``team_state`` is current_team_state with the calling agent excluded, so a
    specialist never sees itself in its own roster. An empty/None team_state
    renders a friendly placeholder rather than an empty table, which happens
    when a specialist is the first (or only) agent staged on the project.
    """
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
    """Build CH_MESSAGING: the inter-agent authority rule for a multi_terminal specialist.

    BE-6008: this is the specialist-facing half of the authority contract. A
    specialist exchanges INFO with its peers but never authors WORK for them and
    never accepts WORK from them — only the orchestrator authors WORK. The rule
    exists because peer-to-peer work hand-offs silently fork the plan: two agents
    start redirecting each other, the orchestrator's view of who-is-doing-what
    drifts, and scope changes happen with no single owner.

    The chapter draws the line concretely (status / findings / artifact paths =
    INFO; new tasks / scope changes / re-assignments = WORK) and gives the
    escalation path: a discovery that would change ANOTHER agent's scope goes UP
    to the orchestrator with requires_action=true, never sideways to the peer.
    The orchestrator decides and re-tasks. The closing heuristic — "if acting on
    it would change what another agent is supposed to build, it is WORK" — is the
    tie-breaker for the ambiguous middle.
    """
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
  expected to know their id. pass_baton(thread_id, to="user") works the same way.
  Do NOT write "waiting for you" into a broadcast and hope. A broadcast moves no
  baton, so the request is invisible on the operator's board no matter how the
  prose is worded — the Hub deliberately shows "your turn" only from the baton and
  never from the words in a post. Directed and baton-passed is the only form of
  that request the operator can actually see.

MESSAGE BOARD (threads) — when you are on a comm thread (a CHT-#### chat):
- Posts are APPEND-ONLY. post_to_thread adds to the timeline; never rewrite history.
- IDENTIFY YOURSELF: pass from_agent = your role from your activated agent template
  (implementer, tester, reviewer, analyzer, documenter, orchestrator, or your specific
  agent_id) on every post_to_thread. The Hub renders your color badge from it, matching
  the Home screen. from_agent is REQUIRED — a post without it is refused
  (FROM_AGENT_REQUIRED), never silently attributed to the human. Posting in the human
  user's voice is as_user=true, an explicit act reserved for the operator; never set
  it on your own posts.
- The BATON is next_action_owner. Poll get_my_turn(agent_id) to find threads
  awaiting you; when you have replied and it is someone else's turn, pass_baton to
  them (an agent_id, a user_id, 'all', or 'none').
- Reply when the baton points at you; read get_thread_history first to catch up
  (it does NOT acknowledge — purely a read).
- A thread ends when its status is set to resolved or closed. Set it via
  post_to_thread(set_status=...) when the conversation is done — a looped/sleeping
  agent stops looping on a closed thread.
────────────────────────────────────────────────────────────────────────────
"""


def _build_thread_loop_directive() -> str:
    """Build the thread-scoped loop/sleep directive (BE-6054c).

    Injected into an addressed agent's mission ONLY when the user has armed a loop
    on a comm thread the agent participates in (a ``loop_directive`` message on a
    NON-terminal thread). Generalizes the orchestrator auto-checkin loop: instead
    of looping until "TODO cleared", the agent loops until the THREAD is
    resolved/closed. The interval rides the existing ``set_agent_status(sleeping,
    wake_in_minutes=N)`` pipeline — no new mechanism. The loop provably terminates
    because the directive stops being injected once the thread reaches a terminal
    status (the server no longer sees a live loop_directive for the agent).
    """
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
     `pass_baton(...)` when it is someone else's turn.
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
    """Build CH_AUTHORITY: orchestrator-side staging + messaging authority rule.

    BE-6008: this is the orchestrator-facing half of the authority contract that
    CH_MESSAGING describes for specialists. The orchestrator is the ONLY agent
    that authors WORK; specialists exchange INFO and surface scope-changes UP for
    the orchestrator to decide and re-task. Stating the rule on both sides keeps
    a single, unambiguous owner of the plan.

    Beyond the shared authority rule, the chapter carries the mode-specific
    staging mechanics, because HOW peers become messageable differs by execution
    mode:

      * multi_terminal — two-phase staging. Create ALL agents first (spawn them
        mission-less; each becomes a 'staged', messageable agent with an
        agent_id but a locked Play button), THEN go back and write each job's
        mission. Creating every agent up front means peer agent_ids exist before
        any mission is authored, so the orchestrator can wire peers into each
        other's missions and agents can message each other immediately.

      * CLI subagent modes — there is no live dashboard roster and verification
        agents (tester/reviewer) are deferred to implementation. So the
        orchestrator drains its inbox at mission-WRITE time and splices the
        relevant peer findings + predecessor artifacts directly into each
        downstream mission as it authors it — what gets written into the mission
        is all the subagent will ever see; there is no live roster to re-read
        after it starts.

    Args:
        cli_mode: True for any subagent execution mode (canonical ``subagent``
            or a stored legacy per-CLI alias), False for multi_terminal.
    """
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
