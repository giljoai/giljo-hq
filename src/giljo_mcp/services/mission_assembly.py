# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Mission assembly — build the full mission text, protocol, and MissionResponse.

BE-6211f: verbatim split from ``mission_service.py``. Both functions take
already-fetched ORM objects and open NO database sessions — the caller
(``MissionService.get_agent_mission``) does all I/O and passes the results in.
``MissionService`` keeps thin back-compat shims that delegate here.
"""

from __future__ import annotations

import hashlib
from typing import Any

from giljo_mcp.models import AgentExecution, AgentJob
from giljo_mcp.platform_registry import (
    EXECUTION_MODE_TO_TOOL,
    HARNESS_CLI_TOOL_TYPES,
    Platform,
    effective_harness,
    has_local_agent_file_channel,
)
from giljo_mcp.schemas.responses.orchestration import (
    IDENTITY_RESOLVED,
    IDENTITY_TEMPLATE_UNBOUND,
    IDENTITY_TEMPLATE_UNRESOLVED,
)
from giljo_mcp.schemas.service_responses import MissionResponse
from giljo_mcp.services.execution_mode_gate import effective_execution_mode
from giljo_mcp.services.protocol_builder import (
    _generate_agent_protocol,
    _generate_team_context_header,
)
from giljo_mcp.services.protocol_survival import compute_next_required_actions


# HO1020: execution_mode -> protocol tool (fail-safe default 'multi_terminal').
_EXECUTION_MODE_TO_TOOL = EXECUTION_MODE_TO_TOOL


def compute_is_chain_conductor(chain_execution_mode: str | None, project_id: Any) -> bool:
    """BE-6211g: the project-less chain-conductor signal — an active chain run
    (``chain_execution_mode`` resolved) AND no owned project.

    SHARED by the protocol-body trim (this module, move b) and the identity trim
    (mission_service, move c) so the two can never disagree on conductor-ness for one
    run. Extracted from the duplicated inline literal both sites previously carried.
    """
    return bool(chain_execution_mode) and not project_id


_UNRESOLVED_IDENTITY_BLOCK = """You are running WITHOUT a role identity. {cause}, so no role
instructions, behavioral rules or success criteria could be loaded for you.

Work your mission literally and conservatively — you have no role framing to lean on. Where the
protocol tells you to take your role "from your activated agent template", you have none: use your
display name '{display_name}' as your `from_agent` value instead.

This is a degradation, not a stop. Keep working your mission, and report it once via
report_progress (or post_to_thread) so whoever spawned you can {remedy}."""


def compose_template_identity(identity_template: Any, execution: AgentExecution) -> str:
    """Compose an agent's operating identity from its bound template.

    BE-6211f-style extraction (BE-9333): lifted out of
    ``MissionService._resolve_mission_template`` — pure, no I/O — so the identity
    composition and its BE-9333 unresolved counterpart below live side by side.

    Not a byte-for-byte move: two redundant truthiness guards were collapsed
    (``if X:`` wrapping ``if isinstance(X, list) and len(X) > 0:``, where the inner
    test already implies the outer for every value). Behaviour is unchanged.
    """
    # Framing directive -- tells the LLM how to process this field
    role_label = (identity_template.role or execution.agent_name or "agent").upper()
    identity_parts = [
        f"You are {role_label}. The following defines your expertise, "
        f"behavioral constraints, and success criteria. "
        f"Internalize these as your operating identity.\n"
    ]

    # Role prose (user_instructions only -- system_instructions excluded
    # because the thin prompt already handles MCP bootstrap)
    if identity_template.user_instructions:
        identity_parts.append(identity_template.user_instructions)

    # Behavioral rules (structured list from template)
    rules = identity_template.behavioral_rules
    if isinstance(rules, list) and len(rules) > 0:
        identity_parts.append("\n## Behavioral Rules\n" + "\n".join(f"- {r}" for r in rules))

    # Success criteria (structured list from template)
    criteria = identity_template.success_criteria
    if isinstance(criteria, list) and len(criteria) > 0:
        identity_parts.append("\n## Success Criteria\n" + "\n".join(f"- {c}" for c in criteria))

    return "\n\n".join(identity_parts)


def compose_unresolved_identity(job: AgentJob, execution: AgentExecution) -> tuple[str, str]:
    """BE-9333: explicit identity text + status for a job whose template did not resolve.

    Two distinct causes with two distinct remedies, so the response never blurs them:

    * ``template_id`` is SET but the row no longer loads — the user soft-deleted (or the
      30-day reaper purged) the agent template while this job was live. ``AgentJob.template_id``
      is not cleared at soft-delete and ``get_template_by_id`` filters ``deleted_at IS NULL``
      (``mission_repository.py``), so a healthy agent DEGRADES mid-run with nothing said.
    * ``template_id`` is NULL on a non-orchestrator job — nothing was ever bound.

    Returns ``(identity_text, identity_status)``. Never returns None: a bare null is precisely
    the signal-less state this exists to remove.
    """
    display_name = execution.agent_display_name or execution.agent_name or "agent"
    requested = execution.agent_name or display_name
    if getattr(job, "template_id", None):
        cause = f"The agent template this job was created against ('{requested}') has been DELETED"
        remedy = "restore that agent from the trash, or re-spawn this work against a live agent"
        status = IDENTITY_TEMPLATE_UNRESOLVED
    else:
        cause = f"This job was never bound to an agent template ('{requested}' resolved to none)"
        remedy = "re-spawn this work against an agent that exists"
        status = IDENTITY_TEMPLATE_UNBOUND
    return _UNRESOLVED_IDENTITY_BLOCK.format(cause=cause, display_name=display_name, remedy=remedy), status


def should_serve_identity(identity_status: str, execution_mode: Any) -> bool:
    """BE-9402: whether ``get_job_mission`` ships the identity block, per the MODE ELECTION.

    ``projects.execution_mode`` is a stored user election -- a signal the server
    genuinely has, unlike what sits on the client's disk. It answers the only
    question that matters here: has the agent ALREADY been handed this persona by
    its harness? :func:`has_local_agent_file_channel` is that question, asked in its
    own words rather than borrowed from ``is_subagent_mode`` (which answers a
    TOPOLOGY question and deliberately differs on ``generic_mcp`` -- see its docstring).

    * **subagent** and the four legacy CLI tokens -- yes. The orchestrator spawns each
      worker through the harness's own subagent mechanism, which loads the installed
      ``gil-*`` / ``.claude/agents/*`` file. That file is rendered from the SAME template
      row this identity is composed from, so serving it again is a byte-for-byte
      duplicate: 1,300-2,400 tokens per agent, ~8-14k across a six-agent run. Omit it.
    * **multi_terminal** -- no, and this serve is LOAD-BEARING: do not "optimise" it
      away to match the row above. A launched terminal boots on the ~50-token
      natural-language prompt from ``launch_command_synth.build_loaded_prompt``
      ("call get_job_mission and execute it"). Nothing else reaches that process, so
      the server is its ONLY identity channel. Withholding here strands the agent
      with no role framing at all.
    * **generic_mcp** -- no, for the same reason as multi_terminal despite being a
      subagent TOPOLOGY. It has no CLI, so nothing installs agent files for it; its own
      protocol prose says templates are "served by the MCP server, not local files".
    * **unset / unrecognised** -- also no. The direction of the fail-safe is to SERVE:
      duplicate tokens are a cost, no persona is a broken agent. The predicate is a
      membership test, so an unknown token answers False and gets served. (A NULL never
      arrives -- ``check_implementation_gate`` blocks it upstream.)

    ``identity_status`` narrows the omission to the identity the installed file
    actually duplicates -- a bound template's persona (``resolved``). Two kinds are
    served in EVERY mode because no file carries them:

    * ``orchestrator_default`` -- the subagent-mode orchestrator is the user's ROOT
      session, not something spawned via a subagent call, so no file feeds it. It is
      also composed through ``compose_orchestrator_identity``, which appends the system
      harness block (MCP tool usage, check-in protocol, harness reminder override) that
      the installed file is not rendered through. Omitting it would leave a subagent
      orchestrator with no identity channel whatsoever.
    * ``template_unresolved`` / ``template_unbound`` -- BE-9333's explicit degradation
      report. Not a persona, no file equivalent, and roughly four lines: nothing to
      de-duplicate, and BE-9333's guarantee that this block is never silently null
      must survive this change.
    """
    return not (has_local_agent_file_channel(execution_mode) and identity_status == IDENTITY_RESOLVED)


def _apply_identity_serve_gate(
    logger,
    job_id: str,
    agent_identity: str | None,
    identity_status: str,
    protocol_exec_mode: Any,
) -> str | None:
    """BE-9402: apply :func:`should_serve_identity` and log a withholding.

    THE DEFENCE OF THE SERVE SITE. Withholding happens for exactly ONE combination --
    a ``subagent`` election carrying a ``resolved`` (bound-template) identity -- because
    that is the only identity an installed ``gil-*`` / ``.claude/agents/*`` file already
    carries. Why each of the other four outcomes KEEPS being served, so that none of them
    is later "optimised" away to match:

    * **multi_terminal** -- its terminal boots on the ~50-token prompt from
      ``launch_command_synth.build_loaded_prompt``. Nothing else reaches that process; the
      server is its only identity channel.
    * **unrecognised / absent election** -- fail SAFE. Duplicate tokens cost tokens; no
      persona breaks the agent. (A NULL never arrives: ``check_implementation_gate`` blocks
      it upstream.)
    * **orchestrator_default** -- composed by ``compose_orchestrator_identity`` off
      ``resolve_orchestrator_override``, i.e. the BE-9385d product -> tenant -> seeded-default
      chain plus the system harness block. That is server-side tenant DATA no client file
      can carry, and a subagent-mode orchestrator is the user's ROOT session that nothing
      spawns from a file. Withholding it deletes per-product customization outright.
    * **template_unresolved / template_unbound** -- BE-9333's degradation report, four lines,
      no file equivalent. Withholding it restores the signal-less null BE-9333 removed.

    ``protocol_exec_mode`` must be the mode the protocol render resolved through
    ``effective_execution_mode`` (BE-9335), so a chain member can never be rendered
    for one harness while being gated on another.

    The log line exists because an omission is otherwise invisible: ``agent_identity``
    simply arrives null. Here it is deliberate, and the line says so.

    Pinned by tests/integration/test_be9402_mode_elected_identity_boundary.py -- the two
    carve-out rows fail if the ``identity_status`` term is dropped.
    """
    if should_serve_identity(identity_status, protocol_exec_mode):
        return agent_identity
    if agent_identity:
        logger.info(
            "[AGENT_IDENTITY] Withheld by the subagent mode election -- the harness loads it from disk",
            extra={"job_id": job_id, "identity_status": identity_status},
        )
    return None


def gate_identity_source(served_identity: str | None, identity_source: str | None) -> str | None:
    """FE-9408: provenance rides ONLY where the identity it describes rides.

    Lives beside the serve gate because it is the same decision. On a withheld response
    (BE-9402) the agent reads its persona off an installed ``gil-*`` file; a source line
    here would attribute text this response did not send, and would name a rung of the
    override ladder that the file on disk never consulted -- worse than silence, because
    it reads as an answer.
    """
    return identity_source if served_identity else None


def compute_protocol_etag(agent_identity: str | None, full_protocol: str | None) -> str:
    """BE-6208g: sha256 of the static identity+protocol block (the cacheable part).

    A NUL separator keeps the two segments unambiguous so distinct (identity,
    protocol) pairs cannot collide on concatenation.
    """
    static_block = (agent_identity or "") + "\x00" + (full_protocol or "")
    return hashlib.sha256(static_block.encode("utf-8")).hexdigest()


def _maybe_inject_ch6(
    full_protocol: str,
    execution: AgentExecution,
    protocol_exec_mode: str,
    project: Any,
    checkin_cadence_minutes: int | None,
) -> str:
    """Append CH6 (check-in protocol) for a multi-terminal orchestrator.

    Handover 0960 / BE-6013: CH6 is ALWAYS injected for a multi-terminal
    orchestrator — the cadence decision lives INSIDE the protocol (re-read live
    via get_workflow_status() every cycle), so a Settings change reaches an
    already-running orchestrator without a restart. CLI modes and
    non-orchestrator agents never receive it.
    BE-9335: keyed off protocol_exec_mode, the SAME resolved value the header
    uses, so CH6 and the header cannot disagree for a chain member.
    FE-9296b: the project-less dedicated conductor now receives CH6 too (it
    previously had no cadence at all), in its conductor prose variant. The
    seed is the caller-resolved cadence; the slider-era project columns are
    the session-free fallback.
    """
    if execution.agent_display_name != "orchestrator" or protocol_exec_mode != "multi_terminal":
        return full_protocol
    from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch6_auto_checkin

    interval = checkin_cadence_minutes
    if interval is None:
        has_override = project is not None and getattr(project, "auto_checkin_enabled", False)
        interval = getattr(project, "auto_checkin_interval", 10) if has_override else 10
    return full_protocol + "\n" + _build_ch6_auto_checkin(interval, for_conductor=project is None)


def assemble_mission_context(
    logger,
    job: AgentJob,
    execution: AgentExecution,
    project: Any,
    agent_identity: str | None,
    all_project_executions: list[AgentExecution],
    mission_lookup: dict[str, str],
    current_team_state: list[dict] | None,
    tenant_key: str,
    integrations: dict | None = None,
    chain_execution_mode: str | None = None,
    preset: Platform | None = None,
    comm_thread_id: str | None = None,
    detected_harness: str | None = None,
    checkin_cadence_minutes: int | None = None,
    identity_status: str = IDENTITY_RESOLVED,
    identity_source: str | None = None,
) -> MissionResponse:
    """Build the full mission text, protocol, and MissionResponse.

    FE-9296b: ``checkin_cadence_minutes`` is the caller-resolved check-in
    cadence (this module opens no sessions); None falls back to the project
    columns — see _maybe_inject_ch6.

    Combines team context header, Serena integration, and the 5-phase
    lifecycle protocol into the final response object.

    BE-8003f (D2 activation): a resolved harness ``preset`` (shell-less
    web_sandbox/desktop_app/chat) makes ``_generate_agent_protocol`` render the
    preset-active S3/S4 ladder; ``preset=None`` (every CLI caller) keeps today's
    bytes byte-identical (D1).

    BE-9012d: ``comm_thread_id`` is the caller-resolved bound Hub thread id for
    this job's project (None for a project-less job); threaded straight into
    ``_generate_agent_protocol`` so the worker body can reference it.

    BE-9079: ``detected_harness`` is the session-detected harness token (claude-code /
    codex / ..., else "generic"/None). It applies the SAME DETECTED-beats-declared render
    precedence get_staging_instructions uses (``effective_harness``): a concrete detected
    harness overrides ONLY the render ``tool`` (which spawn/forbidden prose the orchestrator
    protocol renders), leaving the declared ``execution_mode`` untouched — mirroring
    mission_orchestration_service's ``protocol_tool`` override. None/"generic" resolves back
    to the declared hint (== ``agent_tool``), so the render stays byte-identical to today.
    """
    job_id = job.job_id

    # BE-6008: a multi_terminal specialist (non-orchestrator) gets the LIVE
    # CH_TEAM roster in full_protocol below, so suppress the static `## YOUR
    # TEAM` table in its mission body — shipping both is a duplicate roster.
    project_exec_mode = getattr(project, "execution_mode", "multi_terminal") if project else "multi_terminal"
    is_multi_terminal_specialist = (
        execution.agent_display_name != "orchestrator" and project_exec_mode == "multi_terminal"
    )

    # Handover 0353: Generate team-aware mission with context header
    team_context_header = _generate_team_context_header(
        execution,
        all_project_executions,
        mission_lookup=mission_lookup,
        include_team_table=not is_multi_terminal_specialist,
    )
    raw_mission = job.mission or ""
    # Handover 0825: Mission framing directive
    mission_framing = (
        "This is your assigned work order. Execute the following tasks "
        "within the scope and team structure defined below.\n\n"
    )
    full_mission = mission_framing + team_context_header + raw_mission

    # BE-5008: Read integration toggles from passed dict (loaded in async caller)
    integrations = integrations or {}
    include_serena = integrations.get("serena_mcp", {}).get("use_in_prompts", False)

    if include_serena:
        try:
            # INF-6007: role-specific guidance via the consolidated source of
            # truth. The role is the job_type (orchestrator/analyzer/implementer/
            # tester/reviewer/documenter); for_role falls back to a generic block
            # for an unknown/None role.
            from giljo_mcp.prompt_generation.serena_instructions import for_role

            role = job.job_type
            serena_instructions = for_role(role, enabled=True)
            full_mission = serena_instructions + "\n\n---\n\n" + full_mission
            logger.info(
                "[SERENA] Injected role-specific Serena guidance into agent mission",
                extra={"job_id": job_id, "agent_id": execution.agent_id, "role": role},
            )
        except (ImportError, AttributeError) as e:
            logger.warning(f"[SERENA] Failed to inject Serena guidance: {e}")

    # Generate 5-phase lifecycle protocol (Handover 0334, 0359, 0378 Bug 2, 0497d)
    git_enabled = integrations.get("git_integration", {}).get("enabled", False)
    # Handover 0841: Derive platform tool for platform-aware signoff.
    # HO1020 (Wave 2 Item 2): map via the module-level _EXECUTION_MODE_TO_TOOL
    # constant (fail-safe default "multi_terminal" routes unknown modes to the
    # platform-neutral generic branch instead of Claude Code Task() syntax).
    # BE-6177: a chained orchestrator's header mode comes from the RUN
    # (chain_execution_mode), not the project column. This keeps the
    # full_protocol header (EXECUTION_MODE / FORBIDDEN-Task banner) in agreement
    # with CH_CAPABILITY for the same run. None (solo path) → project mode,
    # byte-identical render.
    # BE-9335: this precedence is now the SHARED rule (effective_execution_mode), not a
    # one-site expression — every chain-member mode reader resolves through it so the
    # boundaries cannot disagree about which harness a member is in.
    protocol_exec_mode = effective_execution_mode(project_exec_mode, chain_execution_mode)
    agent_tool = _EXECUTION_MODE_TO_TOOL.get(protocol_exec_mode, "multi_terminal")
    # BE-6205 follow-up: the project-less DEDICATED conductor (project_id is None,
    # resolved to an active run → chain_execution_mode populated) self-spawns each
    # sub-orchestrator in a fresh terminal. Select the conductor-autonomy banner
    # variant so a cold conductor never stalls on the stock "user opens terminals"
    # prose. A project-bound sub-orch / solo orchestrator keeps the stock banner.
    is_chain_conductor = compute_is_chain_conductor(chain_execution_mode, job.project_id)
    # BE-9079: DETECTED-beats-declared for the RENDER TOOL (mirror of
    # mission_orchestration_service's protocol_tool override at the staging boundary).
    # Only a CONCRETE detected harness overrides the render key; detected None/"generic"
    # resolves back to the declared hint (== agent_tool), so tool stays agent_tool and the
    # render is byte-identical to today. execution_mode is left as the declared-derived
    # agent_tool (the staging path likewise keeps execution_mode declared and swaps only
    # the tool axis). This reaches _generate_orchestrator_protocol so an orchestrator
    # refetching its mission from a detected claude-code/codex session renders that
    # harness's native spawn prose instead of the generic ladder.
    render_tool = agent_tool
    resolved_harness = effective_harness(protocol_exec_mode, {"harness": detected_harness})
    if resolved_harness in HARNESS_CLI_TOOL_TYPES:
        render_tool = resolved_harness
    full_protocol = _generate_agent_protocol(
        job_id=job_id,
        tenant_key=tenant_key,
        agent_name=execution.agent_display_name,
        agent_id=str(execution.agent_id),
        execution_mode=agent_tool,
        git_integration_enabled=git_enabled,
        job_type=job.job_type,
        tool=render_tool,
        is_chain_conductor=is_chain_conductor,
        preset=preset,
        comm_thread_id=comm_thread_id,
    )

    # CH6 check-in protocol — see _maybe_inject_ch6 for the gate + seed rules.
    full_protocol = _maybe_inject_ch6(full_protocol, execution, protocol_exec_mode, project, checkin_cadence_minutes)

    # BE-6008: multi_terminal SPECIALISTS (not the orchestrator, which gets its
    # own roster + authority rule via its orchestrator protocol) receive a
    # live-roster chapter and the inter-agent authority rule. CLI execution
    # modes (claude_code_cli/codex_cli/gemini_cli) get neither — their
    # orchestrator coordinates inline and there is no live dashboard roster.
    if is_multi_terminal_specialist:
        from giljo_mcp.services.protocol_sections.chapters_coordination import (
            _build_ch_messaging,
            _build_ch_team,
        )

        full_protocol += "\n" + _build_ch_team(current_team_state)
        full_protocol += "\n" + _build_ch_messaging()

    # Handover 0731c: Typed return (MissionResponse)
    # CE-0026 / BE-6209b: surface the orchestrator's LIVE project phase so the
    # orch knows where it is at read time (staging vs implementation).
    # execution.project_phase is FROZEN at execution-creation (every orchestrator
    # exec is minted 'staging'), so reading it directly went stale and kept
    # reporting 'staging' after implementation launched. Derive from the same
    # authoritative gate the implementation launch uses
    # (project.implementation_launched_at — see the staging-vs-implementation
    # branch above and assert_implementation_ready), falling back to the frozen
    # column for a project-less conductor (minted 'implementation').
    # Non-orchestrator agents don't have phase semantics — leave None.
    if job.job_type != "orchestrator":
        phase_for_response = None
    elif project is not None:
        phase_for_response = "implementation" if project.implementation_launched_at is not None else "staging"
    else:
        phase_for_response = getattr(execution, "project_phase", None)
    # BE-9083a: the phase-x-role next-steps checklist, derived from the SAME live
    # signals as the fields above (chain_execution_mode resolves only for an active
    # run; phase_for_response derives from implementation_launched_at per CE-0026 —
    # never from the frozen execution snapshot). Rides EARLY in the response so it
    # survives harness tail-truncation of the large blocks.
    next_required_actions = compute_next_required_actions(
        job_type=job.job_type,
        phase=phase_for_response,
        is_chain_member=bool(chain_execution_mode) and bool(job.project_id),
        is_chain_conductor=is_chain_conductor,
    )
    # BE-9402 SERVE SITE. Withheld ONLY for `subagent` + `resolved` -- that one pair is what
    # the installed agent file already duplicates. multi_terminal, an unrecognised/absent
    # election, `orchestrator_default` and `template_unresolved`/`template_unbound` are all
    # STILL SERVED, each for a reason that is load-bearing rather than an oversight to
    # "optimise" away -- read _apply_identity_serve_gate before touching any of them.
    served_identity = _apply_identity_serve_gate(logger, job_id, agent_identity, identity_status, protocol_exec_mode)
    return MissionResponse(
        job_id=job.job_id,
        agent_id=execution.agent_id,
        agent_name=execution.agent_display_name,
        agent_display_name=execution.agent_display_name,
        agent_identity=served_identity,
        identity_status=identity_status,  # BE-9333: rides the wire only when degraded
        identity_source=gate_identity_source(served_identity, identity_source),  # FE-9408
        mission=full_mission,
        project_id=str(job.project_id) if job.project_id else None,  # BE-6184: project-less conductor -> None
        parent_job_id=str(execution.spawned_by) if execution.spawned_by else None,
        status=execution.status,
        created_at=job.created_at.isoformat() if job.created_at else None,
        started_at=execution.started_at.isoformat() if execution.started_at else None,
        thin_client=True,
        full_protocol=full_protocol,
        current_team_state=current_team_state,
        project_phase=phase_for_response,
        next_required_actions=next_required_actions,
    )
