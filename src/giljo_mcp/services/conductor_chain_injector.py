# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Runtime conductor chain-chapter injector (BE-6177 Bug 4).

The runtime orchestrator protocol returned by ``get_job_mission`` is built by
``_generate_agent_protocol`` (agent_protocol.py), which is chain-BLIND — it never
resolves ``chain_ctx``. So a conductor orchestrator that calls ``get_job_mission`` in
the IMPLEMENTATION phase never receives its CH_CONDUCTOR / CH_CHAIN_DRIVE "advance the
chain" instructions. The staging dashboard prompt delivers the chain chapters through
``MissionOrchestrationService._build_orchestrator_protocol``, but the runtime mission
path does not — leaving the chain to silently dead-end at project 1 on any model that
doesn't self-author a chain note (BE-6177; the C1 close-down guard only backstops it).

This module mirrors the conductor branch of ``_build_orchestrator_protocol``: for the
conductor orchestrator in implementation phase it resolves ``chain_ctx`` and appends
CH_CAPABILITY + CH_CHAIN_DRIVE to the runtime protocol (BE-6215: the former CH_CONDUCTOR
is folded into CH_CHAIN_DRIVE).

BE-6184: the conductor is now a DEDICATED, PROJECT-LESS orchestrator minted at
run-create (``job.project_id IS NULL``), found by its ``conductor_agent_id`` on the
active run rather than by owning the head project. The injector therefore routes a
project-LESS conductor job through ``resolve_for_conductor`` (agent-id lookup, run-phase
gate) and a project-BOUND orchestrator through ``resolve`` (project lookup, which after
BE-6184 classifies the head project's orchestrator as a sub_orchestrator → no-op).

Solo / sub_orchestrator / non-orchestrator / not-yet-launched ⇒ no-op: the protocol is
returned byte-identical (Deletion Test holds). Edition Scope: CE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from giljo_mcp.platform_registry import Platform, get_platform
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_capability,
    _build_ch_chain_drive,
    _build_ch_sub_orchestrator,
)
from giljo_mcp.services.protocol_sections.orchestrator_body import (
    trim_embedded_protocol_for_chain,
)
from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver


if TYPE_CHECKING:
    from giljo_mcp.services.mission_service import MissionService


async def inject_conductor_chain_drive(
    mission_svc: MissionService,
    full_protocol: str | None,
    job: Any,
    execution: Any,
    project: Any,
    tenant_key: str,
    preset: Platform | None = None,
    detected_harness: str | None = None,
) -> str | None:
    """Append the implementation-phase chain chapters for a conductor orchestrator.

    Returns ``full_protocol`` unchanged for any job that is not a conductor of an
    active sequential run in the implementation phase.

    BE-8003f (D2 activation): a resolved harness ``preset`` (shell-less) switches
    CH_CAPABILITY + CH_CHAIN_DRIVE to their inline-conducting ladder; ``preset=None``
    (every CLI caller) keeps today's fresh-terminal bytes byte-identical (D1).

    BE-9092: ``detected_harness`` (the session-detected harness token, or None/``generic``)
    lets CH_CHAIN_DRIVE's multi_terminal spawn block narrow to the detected harness's
    single command row; None/generic keeps the full OSxharness matrix byte-identical.
    """
    # Only an orchestrator job participates in a chain.
    if not full_protocol or job.job_type != "orchestrator":
        return full_protocol

    # BE-6184: the conductor is now a DEDICATED, PROJECT-LESS orchestrator
    # (job.project_id IS NULL). The old gate early-returned on ``not job.project_id``,
    # which would WRONGLY skip CH_CHAIN_DRIVE for that conductor (the exact dead-end).
    # Phase gate, split by whether this job owns a project:
    #   * project-BOUND orchestrator (sub-orchestrator): only ``project is None`` is a
    #     defensive bail. The §14 fix removed the per-project launch gate, so a chain
    #     sub-orch must receive its COMBINED CH_SUB_ORCHESTRATOR chapter on its FIRST
    #     fetch — BEFORE implementation_launched_at is stamped (that stamp now happens at
    #     the sub-orch's OWN staging-end, not via a conductor gate-cross). resolve()
    #     below returns None for a SOLO project (no active run) → byte-identical no-op,
    #     so dropping the impl_launched_at precondition cannot leak chain prose into solo.
    #   * project-LESS conductor: there is NO project row to read, so gate on the
    #     RUN being in a driving phase instead. find_active_run_for_project already
    #     filters to active statuses (pending/running/stalled), so reaching a
    #     conductor ChainContext below IS the run-phase signal; do not deref project.
    if job.project_id and project is None:
        return full_protocol

    resolver = SequenceChainContextResolver(
        db_manager=mission_svc.db_manager,
        tenant_manager=mission_svc.tenant_manager,
        websocket_manager=mission_svc._websocket_manager,
        test_session=mission_svc._test_session,
    )
    # Best-effort: chain resolution is an ENHANCEMENT to the runtime protocol — it must
    # NEVER break mission delivery. Any failure (e.g. a transient DB/session error)
    # leaves the orchestrator with its normal solo protocol (the C1 guard still backstops
    # a chain). The common solo path returns chain_ctx=None and no-ops below.
    try:
        async with mission_svc._get_session(tenant_key) as session:
            if job.project_id:
                # Project-bound orchestrator: resolve the run via its project. After
                # BE-6184 this classifies the head project's orchestrator as a
                # sub_orchestrator (agent_id != conductor_agent_id), so it no-ops below.
                chain_ctx = await resolver.resolve(
                    session,
                    project_id=str(job.project_id),
                    tenant_key=tenant_key,
                    orchestrator_agent_id=str(execution.agent_id),
                    is_staging=False,
                )
            else:
                # BE-6184: project-less DEDICATED conductor, found by its agent id on
                # the active run (the run-phase gate); no project to deref.
                chain_ctx = await resolver.resolve_for_conductor(
                    session,
                    conductor_agent_id=str(execution.agent_id),
                    tenant_key=tenant_key,
                    is_staging=False,
                )
    except Exception:  # noqa: BLE001 — chain injection is best-effort; never block the mission
        return full_protocol

    if chain_ctx is None:
        return full_protocol

    # BE-6187: a sub_orchestrator (every project's own orchestrator after BE-6184)
    # gets CH_SUB_ORCHESTRATOR at runtime — its chain position, where to find the Hub
    # thread (get_context(categories=["chain"]) -> hub_thread_id), and the close-out
    # advance signal. Best-effort:
    # any failure leaves the solo protocol untouched (Deletion Test holds).
    if chain_ctx.role == "sub_orchestrator":
        order = chain_ctx.resolved_order or []
        pid = str(job.project_id) if job.project_id else None
        if pid is not None and pid in order:
            position = order.index(pid) + 1
            # BE-9083d phase-scoping: ONE source of truth for the live phase — the same
            # CE-0026 signal every other derivation uses (implementation_launched_at,
            # stamped at this sub-orch's OWN staging-end). The staging fetch keeps the
            # FULL combined chapter (bridge included) and defers the implementation-only
            # solo regions; the implementation fetch collapses the done staging steps.
            phase = "implementation" if getattr(project, "implementation_launched_at", None) is not None else "staging"
            # BE-6214: the override-first preamble is gone (its three seams now live in
            # CH_SUB_ORCHESTRATOR). Lean-trim the embedded solo protocol so the PHASE-3
            # finale + worker-spawn duplication CH_SUB_ORCHESTRATOR restates is not
            # re-shipped. Solo never reaches here (chain_ctx is None returns above).
            # BE-9083a: chain chapter FIRST — harness truncation eats the tail of a
            # large payload, and the chain script is the part a sub-orch cannot
            # reconstruct from solo prose. The trimmed solo body follows it.
            return "\n\n".join(
                [
                    _build_ch_sub_orchestrator(
                        run_id=chain_ctx.run_id,
                        position=position,
                        n_projects=len(order),
                        execution_mode=chain_ctx.execution_mode,
                        chain_mission=chain_ctx.chain_mission,  # BE-6196: inline the live contract
                        phase=phase,
                    ),
                    trim_embedded_protocol_for_chain(full_protocol, "sub_orchestrator", phase=phase),
                ]
            )
        return full_protocol

    # Only the conductor of an active multi-project run gets the drive chapters.
    if chain_ctx.role != "conductor":
        return full_protocol

    chain_mode = chain_ctx.execution_mode
    platform = get_platform(chain_mode)
    can_spawn = platform.can_spawn_terminals if platform is not None else True

    # BE-6214: the override-first conductor preamble is gone (its three seams now live
    # in CH_CHAIN_DRIVE). Lean-trim the embedded solo protocol so the PHASE-1/PHASE-2
    # region CH_CHAIN_DRIVE STEP A/B owns collapses to a pointer instead of re-shipping.
    # BE-6215: CH_CONDUCTOR (addressability + directive relay) is FOLDED into
    # CH_CHAIN_DRIVE — they only ever co-render in the drive phase, so the separate
    # chapter was pure overhead. _build_ch_chain_drive already receives conductor_agent_id
    # + job_id and now renders the relay protocol inline.
    # BE-9083a: chain chapters FIRST (CH_CAPABILITY + CH_CHAIN_DRIVE), trimmed solo
    # body LAST — harness truncation eats the tail, and the drive loop is the part
    # the conductor cannot function without.
    parts: list[str] = [
        _build_ch_capability(execution_mode=chain_mode, can_spawn_terminals=can_spawn, preset=preset),
        _build_ch_chain_drive(
            run_id=chain_ctx.run_id,
            resolved_order=chain_ctx.resolved_order,
            current_index=chain_ctx.current_index,
            execution_mode=chain_mode,
            conductor_agent_id=chain_ctx.conductor_agent_id,
            job_id=str(job.job_id),
            preset=preset,
            detected_harness=detected_harness,  # BE-9092: narrow the multi_terminal spawn matrix
        ),
        trim_embedded_protocol_for_chain(full_protocol, "conductor"),
    ]
    return "\n\n".join(parts)
