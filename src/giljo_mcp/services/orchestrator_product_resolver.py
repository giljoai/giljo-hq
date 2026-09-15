# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.system_prompts.identity_provenance import append_identity_source, format_identity_source
from giljo_mcp.system_prompts.service import ResolvedOverride, coerce_product_id


async def _resolve_product_id(
    service: Any,
    session: AsyncSession,
    job: Any,
    execution: Any,
    tenant_key: str,
    project: Any | None,
) -> str | None:
    try:
        if job.project_id:
            return coerce_product_id(getattr(project, "product_id", None) if project is not None else None)

        from giljo_mcp.services.sequence_run_service import SequenceRunService

        svc = SequenceRunService(db_manager=service.db_manager, tenant_manager=service.tenant_manager, session=session)
        run = await svc.find_active_run_for_conductor(conductor_agent_id=str(execution.agent_id), tenant_key=tenant_key)
        if not run:
            return None
        resolved_order = run.get("resolved_order") or []
        if not resolved_order:
            return None
        head = await service._repo.get_project_by_id(session, tenant_key, resolved_order[0])
        return coerce_product_id(getattr(head, "product_id", None) if head is not None else None)
    except Exception:  # noqa: BLE001 - best-effort; identity delivery must not fail on this
        service._logger.warning(
            "[BE-9385d] orchestrator product resolution failed (non-fatal); using tenant rung",
            extra={"job_id": getattr(job, "job_id", None)},
        )
        return None


async def resolve_orchestrator_override(
    service: Any,
    session: AsyncSession,
    job: Any,
    execution: Any,
    tenant_key: str,
    project: Any | None,
) -> ResolvedOverride:
    try:
        from giljo_mcp.system_prompts.service import SCOPE_PRODUCT, SystemPromptService

        product_id = await _resolve_product_id(service, session, job, execution, tenant_key, project)
        record = await SystemPromptService(db_manager=service.db_manager).get_orchestrator_prompt(
            tenant_key=tenant_key, product_id=product_id, session=session
        )
        if not record.is_override:
            return ResolvedOverride(content=None)
        return ResolvedOverride(
            content=record.content,
            scope=record.scope,
            updated_at=record.updated_at,
            product_id=product_id if record.scope == SCOPE_PRODUCT else None,
        )
    except Exception:  # noqa: BLE001
        service._logger.warning(
            "[HO1027] Failed to read orchestrator prompt override; using default seed",
            extra={"job_id": getattr(job, "job_id", None)},
        )
        return ResolvedOverride(content=None)


async def compose_identity_with_provenance(
    service: Any,
    session: AsyncSession,
    job: Any,
    execution: Any,
    tenant_key: str,
    project: Any | None,
    *,
    tool: str,
    role: str | None,
) -> tuple[str, str, str]:
    from giljo_mcp.template_seeder import compose_orchestrator_identity

    resolved = await resolve_orchestrator_override(service, session, job, execution, tenant_key, project)
    identity_source = format_identity_source(
        resolved.scope,
        updated_at=resolved.updated_at,
        product_name=await resolve_product_name(service, session, tenant_key, resolved.product_id),
    )
    composed = compose_orchestrator_identity(resolved.content, tool=tool, role=role)
    return append_identity_source(composed, identity_source), identity_source, resolved.scope


async def resolve_product_name(
    service: Any, session: AsyncSession, tenant_key: str, product_id: str | None
) -> str | None:
    if not product_id:
        return None
    try:
        return await service._repo.get_product_name(session, tenant_key, product_id)
    except Exception:  # noqa: BLE001 - a missing label must never cost the identity
        service._logger.warning(
            "[FE-9408] product name lookup failed (non-fatal); provenance line omits it",
            extra={"product_id": product_id},
        )
        return None
