# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    chain_mode = chain_ctx.execution_mode
    platform = get_platform(chain_mode)
    can_spawn = platform.can_spawn_terminals if platform is not None else True

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
            agent_id=agent_id,
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
    conductor_ctx = await chain.resolve_for_conductor(
        session,
        conductor_agent_id=str(execution.agent_id),
        tenant_key=tenant_key,
        is_staging=True,
    )
    if conductor_ctx is not None:
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
