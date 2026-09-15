# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_agent_selection import template_ids_for_product
from giljo_mcp.template_renderer import MAX_PACKAGED_TEMPLATES


logger = logging.getLogger(__name__)


class MissionRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def get_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentJob | None:
        result = await session.execute(
            select(AgentJob).where(
                and_(
                    AgentJob.job_id == job_id,
                    AgentJob.tenant_key == tenant_key,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_active_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        result = await session.execute(
            select(AgentExecution)
            .where(
                and_(
                    AgentExecution.job_id == job_id,
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
                )
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_project_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        result = await session.execute(
            select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key)
        )
        return result.scalar_one_or_none()

    async def get_project_executions_with_jobs(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list:
        result = await session.execute(
            select(AgentExecution, AgentJob)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentExecution.tenant_key == tenant_key,
                )
            )
        )
        return result.all()

    async def get_template_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        template_id: str,
    ) -> AgentTemplate | None:
        result = await session.execute(
            select(AgentTemplate).where(
                and_(
                    AgentTemplate.id == template_id,
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_template_by_role(
        self,
        session: AsyncSession,
        tenant_key: str,
        role: str,
    ) -> AgentTemplate | None:
        stmt = select(AgentTemplate).where(
            AgentTemplate.tenant_key == tenant_key,
            AgentTemplate.role == role,
            AgentTemplate.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        template = result.scalar_one_or_none()
        if template:
            return template

        stmt = (
            select(AgentTemplate)
            .where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.role == role,
                AgentTemplate.is_default,
                AgentTemplate.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def refresh(self, session: AsyncSession, entity) -> None:
        await session.refresh(entity)


    async def count_non_orchestrator_agents(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.agent_display_name != "orchestrator",
                AgentExecution.status.not_in(["decommissioned"]),
            )
        )
        return result.scalar() or 0

    async def count_non_orchestrator_agents_by_liveness(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> tuple[int, int]:
        result = await session.execute(
            select(
                func.count(),
                func.count().filter(AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES)),
            )
            .select_from(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.agent_display_name != "orchestrator",
            )
        )
        total, in_flight = result.one()
        return int(total or 0), int(in_flight or 0)


    async def get_execution_with_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        result = await session.execute(
            select(AgentExecution)
            .options(joinedload(AgentExecution.job))
            .where(
                and_(
                    AgentExecution.job_id == job_id,
                    AgentExecution.tenant_key == tenant_key,
                )
            )
            .order_by(AgentExecution.started_at.desc())
        )
        return result.scalars().first()

    async def get_project_with_vision_docs(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ):
        from giljo_mcp.models.products import Product

        result = await session.execute(
            select(Product)
            .where(and_(Product.id == product_id, Product.tenant_key == tenant_key))
            .options(selectinload(Product.vision_documents))
        )
        return result.scalar_one_or_none()

    async def get_product_name(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ) -> str | None:
        from giljo_mcp.models.products import Product

        result = await session.execute(
            select(Product.name).where(and_(Product.id == product_id, Product.tenant_key == tenant_key))
        )
        return result.scalar_one_or_none()

    async def get_active_templates(
        self,
        session: AsyncSession,
        tenant_key: str,
        limit: int = MAX_PACKAGED_TEMPLATES,
        *,
        product_id: str | None = None,
    ) -> list[AgentTemplate]:
        template_ids = await template_ids_for_product(session, product_id, tenant_key)

        stmt = select(AgentTemplate).where(
            and_(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.deleted_at.is_(None),
            )
        )
        if template_ids is not None:
            stmt = stmt.where(AgentTemplate.id.in_(template_ids))

        result = await session.execute(stmt.limit(limit))
        return list(result.scalars().all())

    async def get_category_metadata(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ) -> tuple[int, object]:
        from giljo_mcp.models.product_memory_entry import ProductMemoryEntry

        result = await session.execute(
            select(
                func.count(ProductMemoryEntry.id),
                func.max(ProductMemoryEntry.created_at),
            ).where(
                and_(
                    ProductMemoryEntry.product_id == product_id,
                    ProductMemoryEntry.tenant_key == tenant_key,
                    ProductMemoryEntry.deleted_by_user.is_(False),
                )
            )
        )
        row = result.one()
        return row[0], row[1]
