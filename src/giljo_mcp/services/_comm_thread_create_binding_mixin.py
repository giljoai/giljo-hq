# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""``create_thread``'s product resolution (FE-9530, operator ruling 1, 2026-08-29).

"A thread MUST carry a product, unless application has no product." Split out of
``CommThreadService`` for the same size-budget reason ``_comm_thread_edit_mixin``,
``_comm_thread_chain_hub_mixin`` and the rest of that class's mixins exist: the
owning module sits at its shrink-only 800-line cap.

Mixed into ``CommThreadService``, so it uses that class's ``_db_manager`` through
``self`` and the public ``create_thread`` API is unchanged.

Edition Scope: CE.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun


class CommThreadCreateBindingMixin:
    """Resolve the product a NEW thread binds to. Mixed into CommThreadService."""

    async def _resolve_create_product_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        product_id: str | None,
        project_id: str | None,
        sequence_run_id: str | None,
    ) -> str | None:
        """Resolve ``product_id`` for ``create_thread``, or leave it ``None``.

        An explicit ``product_id`` is returned unchanged; the caller checks that
        case before calling this.

        - ``project_id`` supplied: derive the product from THAT PROJECT's own
          ``product_id`` (mirroring ``resolve_or_create_bound_thread``'s existing
          precedent) rather than from the tenant's shown/default product — a thread
          anchored to project P belongs to P's product regardless of which tab the
          caller happens to be viewing.
        - ``sequence_run_id`` supplied, no ``project_id``: the dedicated chain
          conductor is deliberately PROJECT-LESS (BE-6184), so its Step-0 hub-thread
          create must never 422 for lacking a product — that refusal exemption is
          unchanged. But BE-9537 found the exemption was being read as "leave it
          untagged" when it only ever meant "don't gate on it": derive the product
          from the run's HEAD project instead, the same rule
          ``orchestrator_product_resolver._resolve_product_id`` already uses for the
          conductor's own identity override, so the two surfaces cannot drift apart.
          Best-effort and NEVER raises — an empty ``resolved_order``, or a head
          project id that no longer resolves (purged/renamed), leaves the thread
          untagged, with FE-9530's seed-text interpolation remaining the fallback
          for a conductor that copies it faithfully.
        - Otherwise: ``ProductService.resolve_binding_product(write=True)``, mirroring
          ``create_task``/``create_project`` — a single product resolves silently
          (unchanged ergonomics), several with none named raises
          ``ProductAmbiguousError`` (BE-6081 Tier-2, agent-actionable, carries the
          full list). A tenant that owns ZERO products has nothing to resolve to —
          ruling 1's stated exception — so this returns ``None`` rather than raising,
          leaving a fresh install's very first thread genuinely standalone.
        """
        if project_id:
            return (
                await session.execute(
                    select(Project.product_id).where(Project.tenant_key == tenant_key, Project.id == project_id)
                )
            ).scalar_one_or_none()

        if sequence_run_id:
            return await self._resolve_product_from_sequence_run(session, tenant_key, sequence_run_id)

        from giljo_mcp.services.product_service import ProductService

        product_service = ProductService(db_manager=self._db_manager, tenant_key=tenant_key, test_session=session)
        existing_products = await product_service.list_products(include_inactive=True, lean=True)
        if not existing_products:
            return None
        bound_product = await product_service.resolve_binding_product(None, operation="create_thread", write=True)
        return bound_product.id

    async def _resolve_product_from_sequence_run(
        self, session: AsyncSession, tenant_key: str, sequence_run_id: str
    ) -> str | None:
        """Best-effort HEAD-project product for a project-less chain-conductor create.

        Never raises: an unresolvable run (not found, empty ``resolved_order``, or a
        head project id that no longer names a live project) returns ``None`` rather
        than blocking the create — see ``_resolve_create_product_id``.
        """
        run = (
            await session.execute(
                select(SequenceRun).where(SequenceRun.tenant_key == tenant_key, SequenceRun.id == sequence_run_id)
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        resolved_order = run.resolved_order or []
        if not resolved_order:
            return None
        return (
            await session.execute(
                select(Project.product_id).where(Project.tenant_key == tenant_key, Project.id == resolved_order[0])
            )
        ).scalar_one_or_none()
