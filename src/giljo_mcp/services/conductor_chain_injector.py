# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver, chain_member_phase


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
    if not full_protocol or job.job_type != "orchestrator":
        return full_protocol

    if job.project_id and project is None:
        return full_protocol

    resolver = SequenceChainContextResolver(
        db_manager=mission_svc.db_manager,
        tenant_manager=mission_svc.tenant_manager,
        websocket_manager=mission_svc._websocket_manager,
        test_session=mission_svc._test_session,
    )
    try:
        async with mission_svc._get_session(tenant_key) as session:
            if job.project_id:
                chain_ctx = await resolver.resolve(
                    session,
                    project_id=str(job.project_id),
                    tenant_key=tenant_key,
                    orchestrator_agent_id=str(execution.agent_id),
                    is_staging=False,
                )
            else:
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

    if chain_ctx.role == "sub_orchestrator":
        order = chain_ctx.resolved_order or []
        pid = str(job.project_id) if job.project_id else None
        if pid is not None and pid in order:
            position = order.index(pid) + 1
            phase = chain_member_phase(project)
            return "\n\n".join(
                [
                    _build_ch_sub_orchestrator(
                        run_id=chain_ctx.run_id,
                        position=position,
                        n_projects=len(order),
                        execution_mode=chain_ctx.execution_mode,
                        chain_mission=chain_ctx.chain_mission,
                        phase=phase,
                    ),
                    trim_embedded_protocol_for_chain(full_protocol, "sub_orchestrator", phase=phase),
                ]
            )
        return full_protocol

    if chain_ctx.role != "conductor":
        return full_protocol

    chain_mode = chain_ctx.execution_mode
    platform = get_platform(chain_mode)
    can_spawn = platform.can_spawn_terminals if platform is not None else True

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
            detected_harness=detected_harness,
        ),
        trim_embedded_protocol_for_chain(full_protocol, "conductor"),
    ]
    return "\n\n".join(parts)
