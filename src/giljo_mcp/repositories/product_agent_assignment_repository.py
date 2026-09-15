# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

from sqlalchemy import and_, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.templates import AgentTemplate


logger = logging.getLogger(__name__)


class ProductAgentAssignmentRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def get_assignments_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
        *,
        active_only: bool = False,
    ) -> list[ProductAgentAssignment]:
        stmt = (
            select(ProductAgentAssignment)
            .join(ProductAgentAssignment.template)
            .options(contains_eager(ProductAgentAssignment.template))
            .where(
                and_(
                    ProductAgentAssignment.product_id == product_id,
                    ProductAgentAssignment.tenant_key == tenant_key,
                    AgentTemplate.deleted_at.is_(None),
                )
            )
        )
        if active_only:
            stmt = stmt.where(ProductAgentAssignment.is_active.is_(True))

        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return list(result.unique().scalars().all())

    async def get_assignment(
        self,
        session: AsyncSession,
        product_id: str,
        template_id: str,
        tenant_key: str,
    ) -> ProductAgentAssignment | None:
        stmt = select(ProductAgentAssignment).where(
            and_(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.template_id == template_id,
                ProductAgentAssignment.tenant_key == tenant_key,
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_assignment(
        self,
        session: AsyncSession,
        product_id: str,
        template_id: str,
        tenant_key: str,
        is_active: bool,
    ) -> ProductAgentAssignment:
        existing = await self.get_assignment(session, product_id, template_id, tenant_key)

        if existing:
            existing.is_active = is_active
            await session.flush()
            return existing

        assignment = ProductAgentAssignment(
            product_id=product_id,
            template_id=template_id,
            tenant_key=tenant_key,
            is_active=is_active,
        )
        session.add(assignment)
        await session.flush()
        return assignment

    async def enable_templates_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
        template_ids: list[str],
    ) -> list[ProductAgentAssignment]:
        if not template_ids:
            return []

        existing_stmt = select(ProductAgentAssignment.template_id).where(
            and_(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.tenant_key == tenant_key,
                ProductAgentAssignment.template_id.in_(template_ids),
            )
        )
        with tenant_session_context(session, tenant_key):
            existing_result = await session.execute(existing_stmt)
        existing_template_ids = {row[0] for row in existing_result.all()}

        new_assignments = []
        for template_id in template_ids:
            if template_id in existing_template_ids:
                continue
            assignment = ProductAgentAssignment(
                product_id=product_id,
                template_id=template_id,
                tenant_key=tenant_key,
                is_active=True,
            )
            session.add(assignment)
            new_assignments.append(assignment)

        if new_assignments:
            await session.flush()

        return new_assignments

    async def remove_assignments_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> int:
        stmt = sql_delete(ProductAgentAssignment).where(
            and_(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.tenant_key == tenant_key,
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.rowcount

    async def get_enabled_distinct_roles(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
        exclude_template_id: str | None = None,
    ) -> set[str]:
        from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES

        stmt = (
            select(AgentTemplate.role)
            .join(ProductAgentAssignment, ProductAgentAssignment.template_id == AgentTemplate.id)
            .where(
                and_(
                    ProductAgentAssignment.product_id == product_id,
                    ProductAgentAssignment.tenant_key == tenant_key,
                    ProductAgentAssignment.is_active.is_(True),
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.deleted_at.is_(None),
                    AgentTemplate.role.isnot(None),
                    AgentTemplate.role.notin_(list(SYSTEM_MANAGED_ROLES)),
                )
            )
            .distinct()
        )
        if exclude_template_id:
            stmt = stmt.where(AgentTemplate.id != exclude_template_id)

        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {row[0] for row in result.all()}

    async def get_active_template_ids_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> set[str]:
        stmt = (
            select(ProductAgentAssignment.template_id)
            .join(AgentTemplate, AgentTemplate.id == ProductAgentAssignment.template_id)
            .where(
                and_(
                    ProductAgentAssignment.product_id == product_id,
                    ProductAgentAssignment.tenant_key == tenant_key,
                    ProductAgentAssignment.is_active.is_(True),
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.deleted_at.is_(None),
                )
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {row[0] for row in result.all()}
