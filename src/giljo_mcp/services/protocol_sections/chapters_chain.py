# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Chain-role protocol chapter builders (CH_CAPABILITY, CH_CHAIN_STAGING, CH_CHAIN_DRIVE,
CH_SUB_ORCHESTRATOR).

BE-6165d: Three prose chapters that are injected into the orchestrator protocol ONLY
when the orchestrator is the CONDUCTOR of a sequential multi-project run, plus
CH_SUB_ORCHESTRATOR (BE-6196/BE-6206) for chain-member orchestrators that are NOT the
conductor. When chain_ctx is None (the solo path) none of these render and the
assembled protocol is byte-identical to the pre-chain solo output (Deletion Test holds;
all CE).

Chapter placement in the assembled protocol (conductor only):
  CH_CAPABILITY      — top of conductor chapters ("who am I / how to spawn each project")
  CH_CHAIN_STAGING   — staging phase only, rendered above CH1
  CH_CHAIN_DRIVE     — implementation phase only, the auto-continue loop. BE-6215: the
                       former CH_CONDUCTOR (conductor addressability + user-directive
                       relay, BE-6131c) is FOLDED in here — they only ever co-rendered.

Each builder returns a prose string. They live here to keep chapters_coordination.py
under the 800-line CI guardrail (it was 338 lines before; adding three substantial prose chapters
would push it to ~700+, with no headroom for future changes).
"""

from __future__ import annotations

from giljo_mcp.platform_registry import Platform, stage_mode_token
from giljo_mcp.prompts.launch_command_synth import render_suborch_spawn_command
from giljo_mcp.services.protocol_sections.orchestrator_body import (
    render_capability_ladder,
    slice_chain_mission_for_position,
)


_CH_BORDER = "════════════════════════════════════════════════════════════════════════════"


def _ch_capability_preset(mode: str, preset: Platform) -> str:
    """Preset-active (shell-less) CH_CAPABILITY — inline conducting, no terminal, no
    $DISPLAY (BE-8003f, D3-S1 / DoD-5 '$DISPLAY retirement').

    A resolved preset means NO OS terminals, so the fresh-terminal-per-sub-orchestrator
    contract is impossible. The PREFERRED branch becomes INLINE CONDUCTING; the fresh-OS
    -terminal launch and the $DISPLAY/$WAYLAND_DISPLAY fail-loud clause are NOT rendered
    (they survive only on the None/CLI path as the legacy sanity check)."""
    preferred = (
        f"{_CH_BORDER}\n"
        "          CH_CAPABILITY: HOW TO RUN THIS CHAIN (shell-less harness)\n"
        f"{_CH_BORDER}\n"
        "\n"
        f"This is a CONTRACT, not a question. You are in a {preset.display_label} session with NO\n"
        "OS terminals, so you CANNOT open a fresh terminal per sub-orchestrator. Run the chain by\n"
        "INLINE CONDUCTING: adopt each sub-project's orchestrator role YOURSELF, one at a time, in\n"
        "THIS session — for each project P_i in run order: get_job_mission -> drive its agents ->\n"
        "complete_job -> advance to P_(i+1) ONLY after ready_to_advance is True. EXECUTION MODE =\n"
        f"{mode} still governs how each project spawns its WORKERS. One project at a time; never\n"
        "batch-start the tail. There is NO per-project gate and nothing to unlock."
    )
    fallback = (
        "If your harness supports in-process subagents, you MAY instead spawn ONE subagent per\n"
        "sub-project (your CLI's subagent syntax) and drive it — still one project at a time, and\n"
        "still NEVER a fresh OS terminal (you have none)."
    )
    floor_user_line = (
        "This chain needs to run without terminals — I will conduct each project inline in this "
        "session, or you can re-stage it on a CLI workstation."
    )
    return render_capability_ladder(preferred, fallback, floor_user_line, preset.display_label)


def _build_ch_capability(
    execution_mode: str | None,
    can_spawn_terminals: bool,  # retained for signature stability; see note below
    preset: Platform | None = None,
) -> str:
    """Build CH_CAPABILITY: the conductor's flat spawn CONTRACT (BE-6182 / BE-6205).

    BE-6165d originally made the LLM re-probe its harness at runtime ("try wt /
    osascript / tmux; if unsure downgrade to subagents"). That re-decision is a bug:
    the server already resolved the execution mode deterministically at staging, the
    mode is IMMUTABLE after staging, and a silent self-downgrade produces a mode the
    rest of the chain machinery does not expect. BE-6182 replaced it with a flat
    contract rendering the server-resolved strategy as FACT.

    BE-6205 REVERSES the BE-6182 clause-2 framing (and the a4c9e7995 header logic that
    let a claude-code-harness conductor use Task() to spawn its sub-orchestrators). The
    owner-ratified model:

      1. The execution mode was resolved at staging and is immutable. It governs ONLY
         how each SUB-ORCHESTRATOR spawns its WORKERS — NOT how the conductor spawns
         the sub-orchestrators.
      2. SUB-ORCHESTRATOR SPAWN (mode-INDEPENDENT): the conductor ALWAYS opens each
         project's sub-orchestrator in its OWN FRESH OS TERMINAL, every execution_mode.
         A fresh terminal per sub-orch keeps per-project context isolation GUARANTEED;
         the conductor RUNS the server-rendered launch command itself and NEVER
         Task()-spawns a sub-orch. execution_mode then governs the WORKER spawn:
         subagent modes run WORKERS as REAL Task()/subagents inside the sub-orch's
         terminal (best-effort isolation); multi_terminal opens a fresh terminal per
         WORKER.
      3. NO per-project gate (§14 / BE-6206): the conductor's fresh-terminal spawn
         IS each project's release. There is nothing to "unlock" — a spawned
         sub-orchestrator reads its mission immediately and runs FREE; the conductor
         controls only SEQUENCE (when to spawn the next project), never a switch
         inside a running one.
      4. Fail-LOUD fallback: a harness that genuinely cannot open the fresh terminal a
         sub-orch needs (headless) STOPS and asks the user to re-stage in a subagent
         mode — it never silently switches modes.

    ``can_spawn_terminals`` is accepted (signature stability for both call sites) but
    no longer branches the prose: sub-orch spawn is terminal-based in EVERY mode now,
    and the fail-loud fallback is the single honest escape hatch.

    BE-8003f (D3-S1): ``preset`` is None on the CLI path -> today's exact bytes (D1). A
    resolved (shell-less) preset switches to the inline-conducting ladder — no
    fresh-terminal contract, no $DISPLAY fail-loud.
    """
    mode = (execution_mode or "multi_terminal").strip() or "multi_terminal"
    if preset is not None:
        return _ch_capability_preset(mode, preset)
    is_multi_terminal = mode == "multi_terminal"

    if is_multi_terminal:
        worker_spawn = (
            "  WORKERS (mode = multi_terminal): inside its own terminal each\n"
            "  sub-orchestrator opens one further FRESH TERMINAL per WORKER (each\n"
            "  worker's elected harness: claude / codex / gemini / antigravity cli)."
        )
    else:
        worker_spawn = (
            f"  WORKERS (mode = {mode}): inside its own terminal each sub-orchestrator\n"
            "  runs its WORKERS as REAL Task()/subagents (worker isolation is\n"
            "  BEST-EFFORT — the harness decides). The sub-orch NEVER runs a worker's\n"
            "  work inline in its own window."
        )

    return f"""════════════════════════════════════════════════════════════════════════════
          CH_CAPABILITY: HOW TO SPAWN EACH PROJECT (server-resolved contract)
════════════════════════════════════════════════════════════════════════════

This is a CONTRACT, not a question. The server already resolved how this chain
runs; do not re-probe your harness and do not change modes.

1. EXECUTION MODE = {mode}, resolved at staging — IMMUTABLE. You do NOT choose
   or change it. It governs ONLY how each SUB-ORCHESTRATOR spawns its WORKERS —
   NOT how YOU (the conductor) spawn the sub-orchestrators.

2. SUB-ORCHESTRATOR SPAWN (mode-INDEPENDENT) — you ALWAYS open each project P_i's
   sub-orchestrator in its OWN FRESH OS TERMINAL, regardless of execution_mode. A
   fresh terminal per sub-orchestrator keeps per-project context isolation
   GUARANTEED. You RUN the server-rendered launch command yourself (Bash /
   PowerShell); you NEVER spawn a sub-orchestrator with Task()/subagent syntax and
   you NEVER run a project's work inline in your own window.
{worker_spawn}

3. NO PER-PROJECT GATE — your fresh-terminal spawn IS each project's release. A
   spawned sub-orchestrator reads its mission immediately and runs FREE; you never
   make it wait for a "go" (§14). There is nothing to unlock. You control only
   SEQUENCE — when to spawn the NEXT project, after the current one reports done
   with a commit. One project at a time; never batch-spawn the tail.

4. FAIL LOUD (no silent downgrade) — if this harness genuinely CANNOT open the
   fresh terminal a sub-orchestrator needs (headless: no $DISPLAY and no
   $WAYLAND_DISPLAY), STOP and tell the user to RE-STAGE the chain in a subagent
   mode. NEVER silently switch modes yourself.
────────────────────────────────────────────────────────────────────────────
"""


def _build_ch_chain_staging(
    run_id: str,
    resolved_order: list[str],
    execution_mode: str | None,
    job_id: str,
    product_id: str | None = None,
    agent_id: str | None = None,
) -> str:
    """Build CH_CHAIN_STAGING: the AUTHORITATIVE staging-phase conductor script.

    BE-6186: the conductor is a DEDICATED, PROJECT-LESS orchestrator (it owns no
    project). It stages the WHOLE chain in one session, spawns NO agents, and ends
    with complete_job. Every project P_i (the head INCLUDED) is symmetric: the
    conductor stages each one (minting its own sub-orchestrator). The head is NOT
    special and gets NO agent team here: each project's sub-orchestrator selects its
    own agents when it is launched in the implementation phase.

    BE-6177 (UNIT 1): the conductor now READS DEEP before planning (STEP 0.5) and
    writes ONLY the CHAIN MISSION, carrying a structured per-project CONTRACT block
    (consumes / produces / must leave) for every project. It NO LONGER writes each
    project's mission: that mission-write collision is dissolved by making the chain
    mission the single cross-project source of truth, and each sub-orchestrator
    authors its OWN per-project mission at its turn (it reads the live chain mission
    contract plus its own context). update_project_mission is removed from this script.

    This is the SINGLE authoritative staging script. It replaces the prior dual-hat
    text ("stage the head fully + spawn its agents now") that died with BE-6184's
    project-less conductor.

    The STOP at the end is deliberate: the conductor stops after staging for the
    SINGLE chain-level human Implement press — the one human GO that starts the
    whole rollout (CHAIN_ARCHITECTURE §9), and the boundary that keeps the
    conductor from self-unlocking implementation. It is NOT a per-call
    launch_implementation permission prompt: the drive loop no longer makes one,
    and per-project launch_implementation is auto-approved plumbing (§14).

    BE-9462: ``agent_id`` (the conductor's own agent_id, already resolved by the
    caller into its identity block) is threaded through so Step 0's create_thread
    call can pass ``creator_id`` -- create_thread structurally registers a passed
    creator_id as the first participant and hands it the baton
    (CommThreadService.create_thread), so the conductor lands on its own thread
    in ONE call instead of needing a second join_thread to undo the omission.
    None (the rare legacy self-registration-fallback caller in protocol_builder.py,
    which has no clean agent_id in scope) renders the prior two-call script
    byte-identically -- additive, not a behavior change for that path.
    """
    n = len(resolved_order)
    # BE-6177 (A2): emit the stage_project SHORT `mode` token (claude / codex /
    # gemini / antigravity / multi_terminal), NOT a legacy per-CLI execution_mode
    # token (wrong param name AND wrong vocabulary; the prior text hard-failed the call).
    stage_mode = stage_mode_token(execution_mode)
    order_lines = "\n".join(f"  {i + 1}. {pid}" for i, pid in enumerate(resolved_order))
    # BE-6177 (UNIT 1): product_id is the deep-read handle. None when the head project
    # is gone; the conductor then degrades to list_projects (still gets descriptions).
    product_token = product_id or "<your product_id from the identity block>"
    head_pid = resolved_order[0] if resolved_order else "<P_1>"

    # FE-9530 (Finding 3): a chain's hub thread used to carry NO product_id (the
    # conductor is deliberately project-less) and NO stable link once its
    # sequence_run_id is nulled by purge_run's ON DELETE SET NULL -- so a completed
    # chain's thread was structurally unable to ever be tagged. The fix is to
    # capture the product at CREATE time, before the run exists to be purged, so
    # nothing downstream has to reconstruct it. When the staging step already knows
    # a real product_id (the common case -- it is None only when the head project
    # is gone), the seed instruction passes it straight through; CommThreadService
    # still exempts a sequence_run_id-bearing create from mandatory resolution as
    # the fallback for the rare case this token is the placeholder.
    product_id_kwarg = f', product_id="{product_id}"' if product_id else ""

    if agent_id:
        step0_hub_thread = f"""0. STAND UP THE HUB THREAD (your VERY FIRST action, before writing anything):
   create_thread(subject="Chain: <a few words naming what this chain delivers>",
                 sequence_run_id="{run_id}", creator_id="{agent_id}"{product_id_kwarg})
   sequence_run_id is the ONLY thing marking this thread as this run's hub. Pass it,
   then CHECK it came back set - if null you passed it wrong, and a hub with no link is
   one no sub-orchestrator finds. That failure is SILENT: no error, they never join and
   the chain loses its coordination channel with nobody told.
   The subject is now purely human-readable: the run id does NOT belong in it and
   discovery never reads it. A few words, not a sentence - the operator sees this in a
   card list that truncates from the end, so the front is all they read.
   creator_id="{agent_id}" (your own agent_id) registers YOU as the thread's first
   participant and hands you the baton in this SAME call - there is no separate join
   step. Record the returned thread_id. Every sub-orchestrator resolves it from the
   link via get_context(categories=["chain"]) -> hub_thread_id.
   Then proceed to STEP 0.5."""
    else:
        step0_hub_thread = f"""0. STAND UP THE HUB THREAD (your VERY FIRST action, before writing anything):
   create_thread(subject="Chain: <a few words naming what this chain delivers>",
                 sequence_run_id="{run_id}"{product_id_kwarg})
   sequence_run_id is the ONLY thing marking this thread as this run's hub. Pass it,
   then CHECK it came back set - if null you passed it wrong, and a hub with no link is
   one no sub-orchestrator finds. That failure is SILENT: no error, they never join and
   the chain loses its coordination channel with nobody told.
   The subject is now purely human-readable: the run id does NOT belong in it and
   discovery never reads it. A few words, not a sentence - the operator sees this in a
   card list that truncates from the end, so the front is all they read.
   Record the returned thread_id. Every sub-orchestrator resolves it from the link via
   get_context(categories=["chain"]) -> hub_thread_id.
   Join it yourself as the conductor: join_thread(thread_id=<the returned id>).
   Then proceed to STEP 0.5."""

    return f"""════════════════════════════════════════════════════════════════════════════
       CH_CHAIN_STAGING: SEQUENTIAL CHAIN, STAGING PHASE (AUTHORITATIVE)
════════════════════════════════════════════════════════════════════════════

You are the dedicated CONDUCTOR of a {n}-project sequential chain (run_id:
{run_id}). You own NO project of your own. Your job_id is in your identity block
above (job_id="{job_id}"). Stage the WHOLE chain in ONE session, spawn NO agents,
then STOP for the human Implement gate. complete_job is your VERY LAST call.

You write ONLY the CHAIN MISSION. You do NOT write any project's mission: each
project's sub-orchestrator authors its OWN mission at its turn from your chain
mission contract plus its own context. There is one cross-project source of truth
(the chain mission) and you own it.

This chapter is the AUTHORITATIVE staging script. Where it differs from the solo
CH1/CH2 finale below, THIS wins.

── ORDER OF OPERATIONS (in this order; complete_job is LAST) ────────────────

{step0_hub_thread}

0.5 READ DEEP BEFORE YOU PLAN (this is what makes your contracts concrete):
   You cannot write a useful cross-project contract from project titles alone. Read
   the product conventions and every project's description FIRST:
     get_context(product_id="{product_token}", categories=["product_core", "architecture"])
       The product's shared schema, conventions, and architecture every project
       must respect.
     For EACH project in run order, read its description, either:
       per project: get_context(product_id="{product_token}", project_id="<P_i>", categories=["project"])
       or all at once: list_projects()  (returns every project's description in one call)
     Use whichever is cheaper for this chain; list_projects is usually one call.
   This deep read is what lets you write concrete handoff contracts instead of
   vague prose. Do NOT skip it.

1. WRITE THE CHAIN MISSION with structured per-project CONTRACTS (write FIRST):
   update_job_mission(job_id="{job_id}", mission=<the cross-project plan>)
   This is YOUR own job mission and the SINGLE cross-project source of truth the
   whole chain executes against (the server mirrors it to sequence_runs.chain_mission
   for the dashboard, and every sub-orchestrator reads it LIVE at its turn). Use
   update_job_mission (your OWN job); you have no project, so the per-project mission
   tool does not apply to you and you NEVER write any project's mission.

   The mission MUST contain, for EACH project in run order, a structured contract
   block written from what you read in STEP 0.5:

     ### P_i (<project_id>):
     consumes = <what it takes from its predecessors / the repo state>
     produces = <the concrete artifacts it MUST create>
     must leave = <the invariants its successor depends on>

   Write each contract concrete enough that the sub-orchestrator can lift its own
   slice verbatim and author its project mission from it. Name real files, real
   schema, real symbols (that is why you read deep). Vague prose here forces every
   downstream sub-orch to re-derive the plan and the handoffs drift.

2. STAGE EACH PROJECT P_i (run order below; the HEAD is symmetric, NOT special):
   For EVERY project P_i in RUN ORDER, including project 1:
     stage_project(project_id="<P_i>", mode="{stage_mode}")
        This mints P_i's OWN sub-orchestrator job and returns its orchestrator_id.
        You do NOT paste the returned per-project prompt; you only need P_i staged
        and the orchestrator_id recorded. stage_project drives staging server-side:
        it does NOT require a human paste and NEVER launches implementation.
   Do NOT write any project's mission. Each sub-orchestrator authors its OWN project
   mission at its turn by reading your chain mission contract (above) plus its own
   project context. You own the cross-project plan; the sub-orch owns the per-project
   depth.
   Spawn NO agents for any project. Each project's sub-orchestrator selects and
   spawns its own agents when you launch it in the implementation phase, keeping
   per-project context isolated and avoiding a one-window budget train.

3. END STAGING (complete_job is your VERY LAST call):
   ONLY after the chain mission is written AND all {n} projects are staged (a
   sub-orchestrator job each), call complete_job ONCE on YOUR own job
   (job_id="{job_id}"). This ends your staging session. You spawned no agents of
   your own: that is correct for the conductor and the server accepts it.

── RUN ORDER ────────────────────────────────────────────────────────────────

{order_lines}

(Head project = {head_pid}; it is symmetric: same staging, NO agent team.)

── HALT AFTER STAGING — WAIT FOR THE USER'S EXPLICIT GO (human-in-the-loop gate) ──

This is a HARD STOP. The instant complete_job ends staging you HALT: report the
staged plan (the run order and each project's contract) and the chain mission to the
user, then STOP and WAIT. Until the user gives an EXPLICIT GO you do NOT proceed — do
NOT call launch_implementation, do NOT spawn any sub-orchestrator, do NOT drive, and
do NOT re-call get_job_mission to start driving. There is NO per-project gate, but
there IS this ONE gate and you never cross it yourself.

You are cleared to proceed ONLY when the user gives an EXPLICIT GO: in the dashboard
they press "Implement Chain"; headless they simply tell you to go / implement this
chain in chat. An obedient conductor stays stopped here until then — do not
self-advance. ONLY AFTER the user's GO do you proceed: a fresh conductor session
drives the chain (CH_CHAIN_DRIVE), spawning each project's sub-orchestrator one at a
time (each runs free; the conductor crosses nothing).
────────────────────────────────────────────────────────────────────────────
"""


def _chain_drive_step_a_preset(run_id: str, preset: Platform) -> str:
    """Preset-active (shell-less) STEP A — INLINE CONDUCTING (BE-8003f, D3-S1).

    Replaces the fresh-OS-terminal launch block (the ``wt`` / ``gnome-terminal`` /
    ``osascript`` command) and its $DISPLAY fail-loud clause: a shell-less harness has no
    terminal to open, so the conductor adopts each sub-project's orchestrator role itself,
    one at a time, in this session."""
    preferred = f"""  STEP A — CONDUCT P_i INLINE ({preset.display_label} session: no terminal to open):

    A1. RESOLVE + REUSE P_i's sub-orch job: read it from
        get_workflow_status(project_id=<P_i>).agents[] (the entry with job_type="orchestrator")
        and reuse its job_id as <SUB_ORCH_JOB_ID>. spawn_job(agent_display_name="orchestrator",
        agent_name="orchestrator", project_id="<P_i>") is IDEMPOTENT — it returns the already-
        minted job and NEVER mints a duplicate, so it is safe whether or not one exists.

    A2. ADOPT P_i's ORCHESTRATOR ROLE YOURSELF — INLINE CONDUCTING. You have no OS terminal, so
        open NO terminal and run NO terminal-launch command. In THIS session,
        get_job_mission(job_id=<SUB_ORCH_JOB_ID>) and DRIVE P_i to completion as its
        orchestrator: author its project mission, spawn and coordinate its agents, then
        complete_job. Only then advance.

    A3. COMMS — coordinate via the chain Hub thread (get_context chain -> hub_thread_id)
        then get_thread_history / get_my_turn. Proceed to STEP B (advance on ready_to_advance)."""
    fallback = (
        "If your harness supports in-process subagents, spawn ONE subagent as P_i's\n"
        "sub-orchestrator instead of adopting the role inline — still one project at a time, and\n"
        "still NO OS terminal."
    )
    floor_user_line = (
        "This project must be run without a terminal — I will drive it inline as its orchestrator, "
        "or you can re-stage the chain on a CLI workstation."
    )
    return render_capability_ladder(preferred, fallback, floor_user_line, preset.display_label)


def _build_chain_drive_step_a(run_id: str, spawn_command: str, preset: Platform | None = None) -> str:
    """STEP A of the drive loop: resolve + reuse the sub-orch, then open its fresh terminal
    by running ONE direct command (BE-6207, file-less). Extracted so _build_ch_chain_drive
    stays under the function-length guardrail; the rendered ``spawn_command`` is inlined.

    The hot path is a NEXT-ACTION: A1 resolves the job, A2 is "run ONE command" (a direct
    wt / gnome-terminal call — no files written, cwd self-resolved via $PWD, the tiny
    prompt inline), A3 is Hub comms. Per-project variance (<P_i>, <SUB_ORCH_JOB_ID>) are
    two UUIDs the agent substitutes into the inline prompt — no special chars, no shell risk.

    BE-8003f (D3-S1): ``preset`` is None on the CLI path -> today's exact fresh-terminal STEP A
    (D1). A resolved (shell-less) preset switches to the inline-conducting STEP A.
    """
    if preset is not None:
        return _chain_drive_step_a_preset(run_id, preset)
    return f"""  STEP A — OPEN P_i's SUB-ORCHESTRATOR IN A FRESH TERMINAL (you are the SOLE spawner):

    A1. get_workflow_status(project_id=<P_i>).agents[] → the job_type="orchestrator" entry is
        P_i's sub-orch (already minted when you staged); reuse its job_id as <SUB_ORCH_JOB_ID>. Then
        spawn_job(agent_display_name="orchestrator", agent_name="orchestrator",
        project_id="<P_i>") IDEMPOTENTLY — it returns that same job, never a duplicate.

    A2. Open its FRESH TERMINAL by RUNNING the ONE command below (spawn_job opens no window; YOU
        do, every execution_mode — CH_CAPABILITY). Substitute the two UUIDs <P_i> and
        <SUB_ORCH_JOB_ID> — the ONLY edit. ⚠ RUN it VERBATIM otherwise: do NOT wrap in
        Start-Process, convert to an -ArgumentList array, reformat/re-quote, write to a file, or
        print instead of running. It is a flat, direct call; ``$PWD`` resolves your cwd itself.

{spawn_command}

    A3. Your launch returns NO result — coordinate ONLY via the Hub (get_context chain ->
        hub_thread_id) then get_thread_history / get_my_turn. The sub-orch runs the COMBINED flow
        (CH_SUB_ORCHESTRATOR) free; you do NOT write its mission, stage it, or gate it. → STEP B.
    FAIL LOUD (no silent downgrade): if headless — no $DISPLAY and no $WAYLAND_DISPLAY (key on
    DISPLAY, NOT "is WSL", so WSLg is not blocked) — STOP and tell the user to RE-STAGE in a
    subagent mode (CH_CAPABILITY clause 4). NEVER silently downgrade."""


def _build_ch_chain_drive(
    run_id: str,
    resolved_order: list[str],
    current_index: int,
    execution_mode: str | None,
    conductor_agent_id: str | None,
    job_id: str,
    preset: Platform | None = None,
    detected_harness: str | None = None,
) -> str:
    """Build CH_CHAIN_DRIVE: the auto-continue loop for the implementation phase.

    BE-6165d / BE-6181 / BE-6197: rendered for a conductor in the IMPLEMENTATION
    phase (is_staging=False). Instructs the conductor to advance the chain
    automatically, project by project, from current_index to N.

    BE-6206 (§14, CHAIN_ARCHITECTURE.md) collapses the per-project cycle to the 4-step
    model. There is NO per-project gate: the conductor's spawn IS the release, and a
    released sub-orchestrator runs free (it self-stages → implements → closes out). So the
    old "wait for staging_complete" (STEP B) + "launch_implementation to cross the gate"
    (STEP C) wait/cross steps are REMOVED — they implemented a gate the §14 model does not
    have, and the deadlock was the sub-orch blocked behind it while the conductor waited
    for a staging_complete the blocked sub-orch could never produce. The cycle is now:
      - STEP A: spawn_job P_i's sub-orchestrator (sole spawner; idempotent reuse of the
        eager-minted job). It runs the COMBINED flow free (CH_SUB_ORCHESTRATOR) — no gate
        to open for it.
      - STEP B: park/poll get_workflow_status until ready_to_advance is True (BE-6208f's
        ONE authoritative advance signal; the companion project_closeout_at is the recorded
        commit-SHA timestamp, kept as human/log evidence only). Do NOT advance on status
        "complete" alone. Then go to STEP A for P_(i+1) — advancing
        IS spawning the next project; there is NO launch_implementation and NO PATCH. The
        run's current_index + per-project "planning" status are advanced SERVER-SIDE
        at each sub-orch's own staging-end (job_completion_service._handle_staging_end), so
        the conductor never crosses a gate to make progress.
    Also preserved:
      - the conductor-precedence clause (the solo PHASE 3 "complete_job your job"
        does NOT apply while projects remain; ADVANCE instead)
      - the dashboard back-out controls (Deactivate / Reset / Cancel / Delete) are
        the ONLY real exits; there is no terminate MCP tool and no inbox-directive
        escape hatch (BE-6186 removed the inert terminate-directive prose)
      - crash-resume (BE-6197: RESPAWN the current sub-orch if its closeout is NULL
        and it died with the conductor — a dead sub-orch at current_index would
        otherwise wedge the poll loop forever; re-read via tools, not HTTP)
      - writing ONE series-summary (write_memory_entry tagged "chore") at end
    """
    n = len(resolved_order)
    mode_str = execution_mode or "multi_terminal"
    conductor_id_str = conductor_agent_id or "<your agent_id>"
    # BE-6177 (A4): thread the real orchestrator job_id into the progress/closeout
    # calls instead of a "<your job_id>" placeholder the agent had to resolve.
    job_id_str = job_id or "<your job_id>"
    # BE-6207: the conductor ALWAYS opens each sub-orchestrator in its own fresh
    # terminal by running ONE direct command (no files). $PWD self-resolves the cwd
    # and the tiny prompt rides inline — replacing both the BE-6205 nested one-liner
    # (reformatted into wt-breaking array form) AND the interim file-based launcher
    # (which inherited stale files/ids and cluttered disk).
    # BE-8003f (D3-S1): on the CLI path render the fresh-terminal spawn command as today;
    # a shell-less preset renders inline conducting instead, so the terminal command is not
    # computed or emitted.
    # BE-9092: pass the session-detected harness so the multi_terminal spawn block narrows
    # to the elected harness's single row (full matrix when detection is absent/generic).
    spawn_command = (
        render_suborch_spawn_command(mode_str, run_id, detected_harness=detected_harness) if preset is None else ""
    )
    step_a = _build_chain_drive_step_a(run_id, spawn_command, preset)

    return f"""════════════════════════════════════════════════════════════════════════════
          CH_CHAIN_DRIVE: SEQUENTIAL CHAIN — IMPLEMENTATION (AUTO-CONTINUE)
════════════════════════════════════════════════════════════════════════════

You are the CONDUCTOR of a {n}-project sequential chain (run_id: {run_id}).
Execution mode: {mode_str}.  Resume from current_index: {current_index}.

⚠ PROCEED ONLY AFTER THE USER'S EXPLICIT GO (dashboard "Implement Chain", or a chat "go /
implement this chain"). Until then you are NOT cleared to drive — STOP and wait. The
AUTO-CONTINUE below is correct ONLY once that GO is given; it never licenses you to start
the chain yourself.

SCOPE IS HANDED -- this {n}-project run is your whole scope; do NOT hunt for work. Where the
solo protocol tells you to scan for a project to continue, or a duplicate to merge, IGNORE
it. You are the ESCALATION SINK -- sub-orchestrators surface blockers to YOU on the Hub
thread (get_context chain -> hub_thread_id), not to the user; escalate to the user only a
genuine chain-level decision. When YOU post to the Hub, set from_agent to your UNIQUE label
"Chain Conductor" -- the generic "orchestrator" name is already used by your
sub-orchestrators, so your own posts must stay distinguishable from theirs. This chapter
wins over any contradicting solo default.

── YOU ARE ADDRESSABLE: USER DIRECTIVE RELAY ───────────────────────────────
You are the SINGLE steering point for run directives. The user's "Send directive to
conductor" composer posts DIRECTLY to YOUR Hub thread as a directed post (to_participant
{conductor_id_str}) -- never to sub-orchestrators or workers. STEP B's Hub poll already
surfaces it each cycle. A post is a USER DIRECTIVE when its from_agent_id is NOT one of your
live sub-orchestrators nor yourself (its from_display_name is the user's real account name,
not an agent role). DECIDE before you advance -- you hold project context the user does not:
  a) RELAY to the active sub-orch B_i: post_to_thread(thread_id=<Hub>, content="RELAY:
     <directive>", from_agent="Chain Conductor", to_participant="<B_i agent_id>",
     requires_action=true).
  b) FAN OUT (applies to several live projects): relay to each LIVE sub-orch separately by
     its own agent_id -- there is no all-projects broadcast.
  c) IGNORE (obsolete / inapplicable): post_to_thread(..., content="Received but not acted
     on: <reason>", from_agent="Chain Conductor", to_participant="<the directive's
     from_agent_id>", requires_action=false).
DEFAULT WHEN UNSURE: RELAY to B_i (let B_i decide locally). NEVER forward to a not-yet-started
project B_(i+1..N) -- that sub-orch does not exist yet and the message is dropped; address
only the CURRENTLY ACTIVE sub-orch.

NO WORKER-PROTOCOL FORK: your sub-orchestrators and their workers NEVER write comm_threads and
NEVER call set_next_actor or post_to_thread; reporting is IDENTICAL in subagent and multi_terminal
mode (only what surfaces to the user differs, never how agents communicate).

⚠ TOOLS ONLY — NO raw HTTP. Drive the chain with MCP tools (spawn_job, get_workflow_status,
get_thread_history, post_to_thread, set_agent_status, write_memory_entry, complete_job). Do
NOT hand-edit the run over an HTTP client or SDK — the server advances the run for you at each
sub-orch's staging-end (STEP B).

── CONDUCTOR PRECEDENCE ─────────────────────────────────────────────────────
The solo PHASE 3 instruction to "complete_job your
orchestrator job" does NOT apply while ANY project remains incomplete: Do NOT call complete_job
now. While projects remain you ADVANCE (spawn the next sub-orchestrator) — that is your
closeout-equivalent. complete_job becomes valid ONLY after the FINAL project closes out (SERIES
SUMMARY below); the server enforces it — a premature conductor complete_job returns
CONDUCTOR_CHAIN_INCOMPLETE. THIS wins over the solo finale.

── THE AUTO-CONTINUE LOOP ──────────────────────────────────────────────────

You are the SOLE spawner. Sub-orchestrators never spawn each other — you spawn each one, and
each runs FREE (there is NO per-project gate; your spawn IS the release). One project at a
time; NEVER batch-unlock / spawn the tail.

For each project P_i from current_index ({current_index}) to {n - 1} (inclusive), in run
order, do these IN ORDER:

{step_a}

  STEP B — WAIT FOR P_i's CLOSEOUT, THEN ADVANCE:
    P_i's sub-orch runs FREE (STEP A released it); it self-stages, implements, commits, and
    writes its closeout. The server advances the run's current_index + marks P_i
    "planning" at the sub-orch's OWN staging-end, so you cross nothing to progress. PARK
    AND SELF-PACE the poll loop. CAUTION (CLI): set_agent_status(status="sleeping",
    wake_in_minutes=N) only sets the DASHBOARD label -- it does NOT re-invoke you, so calling
    it then stopping STALLS the whole chain. Drive your OWN wake: launch a short BACKGROUND sleep
    whose completion re-enters you -- Bash: run_in_background `sleep 1 60` (sleep sums its
    args; the harness inspects only the first); PowerShell: run_in_background `Start-Sleep
    -Seconds 60`. You MAY also set_agent_status(status="sleeping", wake_in_minutes=1) for the
    label, but the BACKGROUND SLEEP is what wakes you. On each wake:
      1. get_thread_history(thread_id=<Hub>, as_participant="{conductor_id_str}",
         unread_only=true, mark_read=true) -- resolve <Hub> ONCE via
         get_context(categories=["chain"]) -> hub_thread_id and reuse it. This ONE poll is BOTH your USER-
         directive inbox (above) and the Hub log -- one messaging surface; the unread_only +
         mark_read cursor returns only what's new since your last read.
      2. get_workflow_status(project_id=<P_i>) -> read ready_to_advance (the advance gate).
    ready_to_advance False → start ANOTHER background sleep and poll again (never sleep-and-stop).
    ready_to_advance True → P_i is DONE — that is the server's ONE authoritative advance signal
    (the companion project_closeout_at is the commit-SHA timestamp, log evidence only, NOT the
    trigger). Do NOT advance on status "complete" alone, nor on a sub-orch's Hub "clear to
    advance" note (advisory — it can lead the gate). Then go to STEP A for P_(i+1): advancing IS
    spawning the next project. Auto-continue WITHOUT waiting for per-card review (async).

── ENDING THE CHAIN EARLY: DASHBOARD ONLY ────────────────────────
There is no MCP tool and no inbox directive that ends the run. To end/unwind early, the user
uses the dashboard back-out controls (Deactivate Chain, Reset, Cancel, Delete). If the user
asks you to stop, finish the current project's closeout naturally, stop advancing, and point
them at those controls. Your own complete_job stays refused (CONDUCTOR_CHAIN_INCOMPLETE) until
the FINAL project closes out or the user backs the chain out.

── CRASH-RESUME ──────────────────────────────────────────────────
If your session is interrupted, a fresh conductor session re-reads this chapter on
get_job_mission (run_id + current_index re-injected). Resume at current_index = P_current and
apply the STEP B advance gate: ready_to_advance True → ADVANCE (STEP A for P_(current+1));
False → rejoin the STEP B poll for P_current — but FIRST, if its sub-orchestrator is no longer
alive in get_workflow_status (it died with you), RESPAWN it via STEP A (spawn_job is
IDEMPOTENT). Do NOT merely launch the next: a dead sub-orch at current_index never reaches
closeout, so without reopening it the poll loop wedges forever.

── SERIES SUMMARY (written ONCE at run end) ────────────────────────────────

When ALL projects complete, IN ORDER:
  1. CLEAR YOUR DRIVE TODOs FIRST -- mark every poll / advance / finale TODO completed via
     report_progress(job_id="{job_id_str}", todo_items=[...FULL list, all completed...]). The
     closeout gate refuses with orchestrator_incomplete_todos while any non-closeout drive TODO
     is open, so clear them BEFORE step 2 (the one ordering trap).
  2. write_memory_entry(project_id=<resolved_order[0]>, summary="Chain run {run_id} completed:
     <N_completed> of {n} projects done.", key_outcomes=[<per-project>],
     decisions_made=["Sequential chain conductor auto-continued"], tags=["chore"]).
     Caps (rejected if exceeded): summary <= 1500 chars; <= 5 key_outcomes AND <= 5
     decisions_made; each item <= 250 chars.
  3. complete_job(job_id="{job_id_str}", ...) — valid now (the FINAL project has closed out).
────────────────────────────────────────────────────────────────────────────
"""


def _build_ch_sub_orchestrator(
    *,
    run_id: str,
    position: int,  # 1-based index of this project in the run
    n_projects: int,
    execution_mode: str | None,
    chain_mission: str | None = None,
    phase: str | None = None,
) -> str:
    """Build CH_SUB_ORCHESTRATOR: the COMBINED staging+implementation chain script.

    Injected at staging (via _build_orchestrator_protocol) and at runtime (via
    conductor_chain_injector) for orchestrators that are chain members but NOT the
    conductor (every project's own orchestrator after BE-6184).

    BE-6196 / BE-6206 (§14): a chain sub-orchestrator runs a COMBINED flow -- it stages,
    then flows STRAIGHT INTO implementation. There is NO per-project gate (CHAIN_ARCHITECTURE
    §9/§14): the conductor's spawn IS the release, so the sub-orch is never blocked behind a
    "wait for a go" step. launch_implementation stays OUT of the sub-orch toolset (BE-6115a)
    and out of this prose — the sub-orch self-launches nothing. After its staging-end it
    calls get_job_mission ONCE (now ungated) to flip waiting→working and receive the
    implementation protocol; it does NOT sleep-poll a gate. The chapter inlines the live
    CHAIN MISSION when the caller has it (chain_mission not None), else tells the sub-orch to
    fetch it via get_context(categories=["chain"]) -- backed by the 'chain' category
    (get_chain_context.py, BE-6196 follow-up), which resolves the caller's own active
    run by project_id and returns run_id, chain_mission, resolved_order.

    Best-effort: if not rendered the sub-orch falls through to byte-identical solo
    (Deletion Test holds; the chain still functions via the conductor's drive loop).

    BE-9083d phase-scoping: ``phase`` None/"staging" renders the FULL combined chapter
    byte-identically (the staging boot fetch needs the whole script, bridge included).
    ``phase == "implementation"`` collapses the already-done staging steps 2-4 (and
    their inlined contract slice — consumed when the project mission was authored) to
    a compact marker, KEEPING the step numbering that the PHASE-1/PHASE-3 trim notes
    cross-reference (step 5 / step 7) and the Hub-discovery + escalation seams.
    """
    mode = execution_mode or "multi_terminal"

    if phase == "implementation":
        staging_steps = """2.-4. STAGING -- ALREADY COMPLETE. You authored your project mission, spawned your
   inert agent team, ended staging (complete_job), and posted a staging-complete note
   to the Hub thread (get_context(categories=["chain"]) -> hub_thread_id finds it). Your chain-mission
   contract slice is not re-shipped here -- fetch the full chain mission via
   get_context(categories=["chain"]) if you need cross-project context. ESCALATION unchanged: the CONDUCTOR
   is your escalation path, NOT the user -- post blockers to the Hub thread and POLL
   it yourself (get_thread_history / get_my_turn) for the answer; do NOT stop to ask
   the user directly and do NOT return to the dashboard."""
        return _render_ch_sub_orchestrator(
            run_id=run_id, position=position, n_projects=n_projects, mode=mode, staging_steps=staging_steps
        )

    if chain_mission is not None:
        # BE-9083c: inline only YOUR project's ### P_i contract block, not the whole
        # cross-project mission (unbounded on long chains; churns the protocol_etag on
        # any conductor edit of another project's block). Degenerate missions ship whole
        # (tolerance — see slice_chain_mission_for_position).
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
   the escalation SINK and polls the Hub for exactly this.)"""
    return _render_ch_sub_orchestrator(
        run_id=run_id, position=position, n_projects=n_projects, mode=mode, staging_steps=staging_steps
    )


def _render_ch_sub_orchestrator(*, run_id: str, position: int, n_projects: int, mode: str, staging_steps: str) -> str:
    """Shared CH_SUB_ORCHESTRATOR frame: identity + {staging_steps} + steps 5-7.

    Both phase renders flow through this ONE template so the bridge (step 5), the
    implementation step (6), and the closeout order (step 7) can never diverge
    between phases — only the staging middle differs.
    """
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

{staging_steps}

5. CONTINUE TO IMPLEMENTATION (no gate, no wait) -- There is NO per-project gate and you
   do NOT call any launch tool (you do not have one and must not). The conductor's spawn
   already released you. After staging-end, call get_job_mission ONCE, passing the
   protocol_etag value your boot get_job_mission returned -- on a match the server omits
   the unchanged identity+protocol block (tens of KB smaller, so your harness cannot
   truncate it) and you reuse your cached copy. It returns your implementation protocol
   immediately and flips you to working. Do NOT wait for a human, do NOT return to the
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
