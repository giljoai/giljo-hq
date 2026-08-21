# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The orchestrator's override for a job, resolved on the product ladder (BE-9385d).

Owns ONE question end to end: given an orchestrator job, what override text should
its identity be composed from -- product override, tenant override, or nothing (the
seed)? That splits into "which product is this job's" and "what does the ladder
resolve for it", and both live here so no caller has to hold half the answer.

Lives outside ``mission_service.py`` for the reason ``conductor_staging_builder``
and ``sequence_run_query_mixin`` were extracted before it -- that module sits at its
shrink-only line budget, so the resolver had to leave the file rather than move
within it. The entry point takes the calling service and its session, the shape
``inject_conductor_chain_drive(self, ...)`` already established, so this module
constructs no service wiring of its own.

Edition Scope: Both.
"""

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
    """Resolve the product whose orchestrator override applies to ``job``.

    ``service`` is the calling MissionService -- the same shape
    ``inject_conductor_chain_drive(self, ...)`` already uses, so the resolver reads
    the repository, session factory and logger it needs without a nine-argument call.

    A project-bound orchestrator takes its project's product, read off the ``project``
    row the caller already fetched -- no extra query on the common path.

    The DEDICATED chain conductor is PROJECT-LESS (``job.project_id IS NULL``,
    BE-6184), so reading ``project.product_id`` would silently drop the conductor to
    the tenant rung while its member projects resolved the product one -- an
    inconsistent chain persona that presents as flakiness rather than as a bug. The
    conductor therefore resolves through its active ``sequence_run`` to the HEAD
    project's product. That is deliberately the SAME rule
    ``conductor_staging_builder.resolve_conductor_early_return`` (BE-6177) already
    uses for the conductor's deep-read handle: one rule for "which product is this
    conductor's", so the two surfaces cannot drift apart.

    Best-effort, and it NEVER raises. Any failure returns None, which lands the ladder
    on the tenant rung -- byte-identical to pre-ladder behavior. That includes an
    unusable product id: ``coerce_product_id`` degrades it to None rather than letting
    a ValueError reach the caller's broad ``except``, where it would have replaced the
    tenant's own override with the packaged seed.
    """
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
    """Return what the ladder resolves for this job's orchestrator identity.

    ``content`` is None when the ladder lands on the seeded default; ``scope`` is
    which rung answered (``product`` / ``tenant`` / ``default``), which is what makes
    a "wrong persona" report one line to diagnose instead of an evening of forensics.

    FE-9408 widened this from ``(content, scope)`` to :class:`ResolvedOverride` so the
    winning row's ``updated_at`` and the resolved ``product_id`` survive the call.
    Both were already in hand and thrown away one line before the caller needed them.
    ``product_id`` matters most for the PROJECT-LESS conductor: its product is known
    only here (resolved through its run's head project), so without it the conductor
    could never name the product whose override it is wearing. No extra queries.

    NEVER raises. HO1027's contract is that a failed override read degrades to the
    default seed rather than failing mission delivery, and that contract now lives
    here with the read itself instead of at the call site.
    """
    try:
        # Imported inside the function so the module attribute stays patchable, the
        # way the pre-BE-9385d call site did it (tests patch SystemPromptService).
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
    """Return ``(agent_identity, identity_source, scope)`` for an orchestrator job.

    ``scope`` is the bare rung token, handed back so the caller's BE-9385d log line
    keeps logging ``product`` / ``tenant`` / ``default`` verbatim -- an operator
    grepping for that value is a reader this project must not break while adding one.

    FE-9408. This module already owns "which override applies to this job" end to end;
    composing the identity from that answer and stating which rung it came from is the
    same question's last mile, and keeping the two together is what stops the served
    text and the line describing it from ever disagreeing.

    The composition itself is untouched: ``compose_orchestrator_identity`` is called
    with exactly the arguments it was called with before, and the provenance line is
    APPENDED to its output. Everything ahead of that append is byte-for-byte what
    yesterday's orchestrator received -- which is the property the content pin asserts.
    """
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
    """Best-effort product NAME for the provenance line, or None.

    Separate from the ladder read, and separately guarded, on purpose: a name is
    cosmetic and the override text is not. Folding this lookup into the resolver's
    own ``try`` would mean a hiccup reading one product row degrades the whole read to
    the packaged seed -- a tenant losing its saved persona because a label could not
    be fetched. Here a failure costs the line its parenthetical and nothing else.
    """
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
