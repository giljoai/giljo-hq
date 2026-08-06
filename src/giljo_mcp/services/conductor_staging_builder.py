# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Dedicated chain-conductor staging-response builder (BE-6186).

The dedicated chain conductor is a PROJECT-LESS orchestrator (BE-6184): it owns no
project row, so the project-bound staging assembler in
``MissionOrchestrationService`` cannot build its staging response. This module owns
the small pure builder for it: given a resolved conductor ``ChainContext`` and the
conductor's own ``job_id``, it returns the staging response carrying CH_CAPABILITY +
CH_CHAIN_STAGING as ``orchestrator_protocol`` (the same shape a project-bound staging
response uses), so the conductor receives its authoritative staging script rather than
the STOP placeholder BE-6184 returned.

Factored out of ``mission_orchestration_service.py`` to keep that module under the
800-line guardrail (BE-6186). Pure: no DB, no session; the caller resolves the
``ChainContext`` and threads it in. Edition Scope: CE.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.platform_registry import Platform, get_platform
from giljo_mcp.services.conductor_job_minter import projectless_conductor_staging_directive
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_capability,
    _build_ch_chain_staging,
)
from giljo_mcp.services.sequence_chain_context import ChainContext


def build_conductor_staging_response(
    *,
    chain_ctx: ChainContext,
    job_id: str,
    agent_id: str,
    tenant_key: str,
    product_id: str | None = None,
    preset: Platform | None = None,
) -> dict[str, Any]:
    """Return the staging response for a dedicated, project-less chain conductor.

    ``chain_ctx`` is a resolved conductor ChainContext (role == "conductor"). The
    conductor's own ``job_id`` is threaded into CH_CHAIN_STAGING (its write channel
    for the chain mission via update_job_mission). CH_CAPABILITY + CH_CHAIN_STAGING
    are returned under ``orchestrator_protocol`` exactly the way the project-bound
    staging assembler carries the protocol, so the conductor consumes it the same way.

    BE-6177 (UNIT 1): the conductor now READS DEEP before planning and writes ONLY the
    chain mission (with structured per-project contracts), no longer each project's
    mission. ``product_id`` is the conductor's deep-read handle: it is surfaced in the
    identity block so the conductor can call get_context(product_id=...) for the
    product's conventions and each project's description before authoring contracts. It
    is the head project's product_id, resolved by the caller; None when the head
    project is gone (the conductor degrades gracefully to list_projects).
    """
    chain_mode = chain_ctx.execution_mode
    platform = get_platform(chain_mode)
    can_spawn = platform.can_spawn_terminals if platform is not None else True

    # BE-8003f (D2 activation): a resolved harness ``preset`` (shell-less) renders the
    # inline-conducting CH_CAPABILITY ladder; preset=None keeps today's bytes (D1).
    orchestrator_protocol = {
        "ch_capability": _build_ch_capability(
            execution_mode=chain_mode,
            can_spawn_terminals=can_spawn,
            preset=preset,
        ),
        "ch_chain_staging": _build_ch_chain_staging(
            run_id=chain_ctx.run_id,
            resolved_order=chain_ctx.resolved_order,
            execution_mode=chain_mode,
            job_id=job_id,
            product_id=product_id,
        ),
        "navigation_hint": (
            "You are the dedicated chain conductor. CH_CHAIN_STAGING is your "
            "authoritative staging script; CH_CAPABILITY states how each project is spawned."
        ),
    }

    identity: dict[str, Any] = {
        "job_id": job_id,
        "agent_id": agent_id,
        "project_id": None,
        "product_id": product_id,
        "run_id": chain_ctx.run_id,
        "tenant_key": tenant_key,
        "id_glossary": {
            "job_id": "Your OWN conductor job: update_job_mission (chain mission), complete_job (staging-end)",
            "agent_id": "Use for: post_to_thread(from_agent), get_thread_history(as_participant) on the Hub thread you create",
            "product_id": (
                "The chain's product: read context BEFORE planning via "
                "get_context(product_id=...) (product conventions + each project's "
                "description); the deep read that lets you write concrete contracts"
            ),
        },
    }

    # BE-6187: the conductor STANDS UP the Hub thread itself as Step 0 of
    # CH_CHAIN_STAGING (create_thread), then joins it (join_thread). The server does
    # NOT create the thread; it only exposes the tools the conductor needs to do so.
    # Sub-orchestrators later discover the thread via its sequence_run_id link
    # (BE-9291): get_context(categories=["chain"]) -> hub_thread_id.
    #
    # BE-6177 (UNIT 1): get_context + list_projects are the conductor's deep-read
    # affordance (read the product conventions + every project description before
    # planning). update_project_mission is GONE: the conductor writes ONLY the chain
    # mission (update_job_mission); each sub-orchestrator authors its OWN project
    # mission at its turn, so the conductor never has a reason to write one.
    mcp_tools_available = [
        "create_thread",
        "join_thread",
        "get_context",
        "list_projects",
        "update_job_mission",
        "stage_project",
        "get_workflow_status",
        "complete_job",
        "post_to_thread",
        "get_thread_history",
    ]

    return {
        "status": "CHAIN_CONDUCTOR_STAGING",
        "identity": identity,
        "orchestrator_protocol": orchestrator_protocol,
        "mcp_tools_available": mcp_tools_available,
        "thin_client": True,
    }


async def resolve_conductor_early_return(
    session: AsyncSession,
    *,
    chain: Any,
    repo: Any,
    execution: Any,
    job_id: str,
    tenant_key: str,
    preset: Platform | None = None,
) -> dict[str, Any]:
    """Resolve the project-less chain conductor's staging early-return payload.

    BE-6184/BE-6186: the DEDICATED chain conductor is project-less. It has no project
    row to stage but DOES need a real staging protocol (it stages the whole chain in
    one session). Resolve its active run by the calling agent_id (the run-phase gate)
    and return the rewritten CH_CHAIN_STAGING as ``orchestrator_protocol``; no project
    row is dereferenced. Fall back to the STOP-shaped directive only when this agent is
    not the live conductor of any active run (nothing to stage).

    BE-9291-F1: lifted verbatim out of ``MissionOrchestrationService`` — that branch
    took ``_build_orchestrator_context`` to 296 lines against a 295 shrink-only budget
    (the guardrail-7 breach), while the module itself sat at exactly its 835-line
    budget, so the extraction had to leave the file rather than move within it. This is
    the same seam BE-6186 opened for the same reason. Unlike the pure builder above,
    this resolver DOES take a session: it is the caller-side resolution step that feeds
    ``build_conductor_staging_response``. ``chain`` is the SequenceChainContextResolver
    and ``repo`` the MissionRepository, passed in so this module owns no service wiring.
    """
    conductor_ctx = await chain.resolve_for_conductor(
        session,
        conductor_agent_id=str(execution.agent_id),
        tenant_key=tenant_key,
        is_staging=True,
    )
    if conductor_ctx is not None:
        # BE-6177 (UNIT 1): resolve the head project's product_id so the conductor can
        # read deep (get_context(product_id=...)) before writing its cross-project
        # contracts. Best-effort: a missing/gone head project yields product_id=None
        # and the conductor degrades to list_projects.
        head_product_id: str | None = None
        resolved_order = conductor_ctx.resolved_order
        if resolved_order:
            head_project = await repo.get_project_by_id(session, tenant_key, resolved_order[0])
            if head_project is not None:
                head_product_id = head_project.product_id
        return build_conductor_staging_response(
            chain_ctx=conductor_ctx,
            job_id=job_id,
            agent_id=str(execution.agent_id),
            tenant_key=tenant_key,
            product_id=head_product_id,
            preset=preset,
        )
    return projectless_conductor_staging_directive(job_id)
