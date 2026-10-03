# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun


class CommThreadCreateBindingMixin:

    async def _resolve_create_product_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        project_id: str | None,
        sequence_run_id: str | None,
    ) -> str | None:
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
