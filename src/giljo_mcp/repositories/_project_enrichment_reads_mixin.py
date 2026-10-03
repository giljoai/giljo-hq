# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message


def project_not_trashed():
    return or_(Project.deleted_at.is_(None), Project.status != ProjectStatus.DELETED)


class ProjectEnrichmentReadsMixin:


    async def get_not_deleted(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        stmt = select(Project).where(
            and_(
                Project.id == project_id,
                Project.tenant_key == tenant_key,
                project_not_trashed(),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


    async def get_active_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
        include_unreviewed: bool = False,
    ) -> list[Project]:
        statuses = (
            [ProjectStatus.ACTIVE.value, ProjectStatus.COMPLETED.value]
            if include_unreviewed
            else ProjectStatus.ACTIVE.value
        )
        conditions = self._build_list_conditions(
            tenant_key,
            statuses,
            include_cancelled=False,
            product_id=product_id,
            hidden=None,
            search=None,
        )
        if include_unreviewed:
            conditions.append(or_(Project.status == ProjectStatus.ACTIVE.value, Project.reviewed_at.is_(None)))
        stmt = (
            select(Project)
            .options(selectinload(Project.project_type))
            .where(and_(*conditions))
            .order_by(Project.created_at)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def count_agent_jobs(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> int:
        stmt = select(func.count(AgentJob.job_id)).where(
            AgentJob.project_id == project_id, AgentJob.tenant_key == tenant_key
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def count_messages(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> int:
        stmt = select(func.count(Message.id)).where(Message.project_id == project_id, Message.tenant_key == tenant_key)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_agent_job_type_summary(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list:
        query = (
            select(AgentJob.job_type, func.count(AgentJob.job_id).label("count"))
            .where(AgentJob.project_id == project_id, AgentJob.tenant_key == tenant_key)
            .group_by(AgentJob.job_type)
        )
        result = await session.execute(query)
        return result.all()

    async def get_agent_details_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list:
        query = (
            select(AgentJob, AgentExecution)
            .join(AgentExecution, AgentJob.job_id == AgentExecution.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.tenant_key == tenant_key,
            )
            .order_by(AgentJob.created_at)
        )
        result = await session.execute(query)
        return result.all()

    async def get_memory_entries_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        limit: int | None = None,
    ) -> list[ProductMemoryEntry]:
        if limit is not None:
            query = (
                select(ProductMemoryEntry)
                .where(
                    ProductMemoryEntry.project_id == project_id,
                    ProductMemoryEntry.tenant_key == tenant_key,
                )
                .order_by(ProductMemoryEntry.sequence.desc())
                .limit(limit)
            )
            result = await session.execute(query)
            entries = list(result.scalars().all())
            entries.reverse()
            return entries

        query = (
            select(ProductMemoryEntry)
            .where(
                ProductMemoryEntry.project_id == project_id,
                ProductMemoryEntry.tenant_key == tenant_key,
            )
            .order_by(ProductMemoryEntry.sequence)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_messages_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        limit: int | None = None,
    ) -> list[Message]:
        if limit is not None:
            query = (
                select(Message)
                .where(
                    Message.project_id == project_id,
                    Message.tenant_key == tenant_key,
                )
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(query)
            messages = list(result.scalars().all())
            messages.reverse()
            return messages

        query = (
            select(Message)
            .where(
                Message.project_id == project_id,
                Message.tenant_key == tenant_key,
            )
            .order_by(Message.created_at)
        )
        result = await session.execute(query)
        return list(result.scalars().all())


    async def get_agent_job_type_summaries_for_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
    ) -> dict[str, list]:
        if not project_ids:
            return {}
        query = (
            select(AgentJob.project_id, AgentJob.job_type, func.count(AgentJob.job_id).label("count"))
            .where(AgentJob.project_id.in_(project_ids), AgentJob.tenant_key == tenant_key)
            .group_by(AgentJob.project_id, AgentJob.job_type)
        )
        result = await session.execute(query)
        grouped: dict[str, list] = {}
        for row in result.all():
            grouped.setdefault(row.project_id, []).append(row)
        return grouped

    async def get_agent_details_for_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
    ) -> dict[str, list]:
        if not project_ids:
            return {}
        query = (
            select(AgentJob, AgentExecution)
            .join(AgentExecution, AgentJob.job_id == AgentExecution.job_id)
            .where(
                AgentJob.project_id.in_(project_ids),
                AgentJob.tenant_key == tenant_key,
                AgentExecution.tenant_key == tenant_key,
            )
            .order_by(AgentJob.project_id, AgentJob.created_at)
        )
        result = await session.execute(query)
        grouped: dict[str, list] = {}
        for job, execution in result.all():
            grouped.setdefault(job.project_id, []).append((job, execution))
        return grouped

    async def get_memory_entries_for_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
    ) -> dict[str, list[ProductMemoryEntry]]:
        if not project_ids:
            return {}
        query = (
            select(ProductMemoryEntry)
            .where(
                ProductMemoryEntry.project_id.in_(project_ids),
                ProductMemoryEntry.tenant_key == tenant_key,
            )
            .order_by(ProductMemoryEntry.project_id, ProductMemoryEntry.sequence)
        )
        result = await session.execute(query)
        grouped: dict[str, list[ProductMemoryEntry]] = {}
        for entry in result.scalars().all():
            grouped.setdefault(entry.project_id, []).append(entry)
        return grouped


    async def get_agent_status_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> dict:
        job_counts_result = await session.execute(
            select(AgentExecution.status, func.count(AgentExecution.agent_id).label("count"))
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                )
            )
            .group_by(AgentExecution.status)
        )
        return dict(job_counts_result.all())

    async def get_last_activity_at(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> datetime | None:
        last_activity_result = await session.execute(
            select(
                func.greatest(
                    func.max(AgentExecution.completed_at),
                    func.max(AgentExecution.started_at),
                    func.max(AgentExecution.last_progress_at),
                    func.max(AgentExecution.last_activity_at),
                )
            )
            .select_from(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                )
            )
        )
        return last_activity_result.scalar()

    async def get_product_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ):
        from giljo_mcp.models.products import Product

        result = await session.execute(
            select(Product).where(
                and_(
                    Product.id == product_id,
                    Product.tenant_key == tenant_key,
                )
            )
        )
        return result.scalar_one_or_none()


    async def get_product_with_vision_docs(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ):
        from giljo_mcp.models.products import Product

        result = await session.execute(
            select(Product)
            .options(selectinload(Product.vision_documents))
            .where(Product.id == product_id, Product.tenant_key == tenant_key)
        )
        return result.scalar_one_or_none()
