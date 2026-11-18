# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, not_, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by, distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message
from giljo_mcp.platform_registry import normalize_execution_mode


REVIEW_STEP_RELEASED_AT = datetime(2026, 11, 16, tzinfo=UTC)

_STAGE_PROMPT_HANDED_OUT = "staged"


@dataclass(frozen=True)
class StartListProjectFacts:

    project_id: str | None
    project_name: str | None
    staged: bool
    staged_mode: str | None
    requested: bool
    in_progress: bool
    built: bool
    reviewed: bool


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

    async def get_start_list_project_facts(self, session: AsyncSession, tenant_key: str) -> StartListProjectFacts:
        from giljo_mcp.services.next_action import STAGING_COMPLETE

        live = project_not_trashed()
        launched = Project.ever_launched_at.is_not(None)
        staged = and_(live, or_(Project.staging_status == STAGING_COMPLETE, launched))
        requested = and_(live, Project.staging_status == _STAGE_PROMPT_HANDED_OUT)
        in_progress = and_(
            live, Project.status == ProjectStatus.ACTIVE, Project.implementation_launched_at.is_not(None)
        )
        built = and_(
            launched, or_(Project.status == ProjectStatus.COMPLETED, Project.closeout_executed_at.is_not(None))
        )
        finished_at = func.coalesce(Project.closeout_executed_at, Project.completed_at)
        reviewed = and_(
            built,
            or_(
                Project.reviewed_at.is_not(None),
                finished_at.is_(None),
                finished_at < REVIEW_STEP_RELEASED_AT,
                not_(live),
            ),
        )

        def ordered(column, condition, *, newest_first: bool):
            order = (Project.created_at.desc(), Project.id.desc()) if newest_first else (Project.created_at, Project.id)
            return func.array_agg(aggregate_order_by(column, *order)).filter(condition)

        stmt = select(
            ordered(Project.id, live, newest_first=False),
            ordered(Project.name, live, newest_first=False),
            func.count(case((staged, 1))),
            ordered(Project.execution_mode, staged, newest_first=True),
            func.count(case((requested, 1))),
            func.count(case((in_progress, 1))),
            func.count(case((built, 1))),
            func.count(case((reviewed, 1))),
        ).where(Project.tenant_key == tenant_key)
        (
            ids,
            names,
            staged_count,
            staged_modes,
            requested_count,
            in_progress_count,
            built_count,
            reviewed_count,
        ) = (await session.execute(stmt)).one()
        return StartListProjectFacts(
            project_id=ids[0] if ids else None,
            project_name=names[0] if names else None,
            staged=staged_count > 0,
            staged_mode=normalize_execution_mode(staged_modes[0]) if staged_modes else None,
            requested=requested_count > 0,
            in_progress=in_progress_count > 0,
            built=built_count > 0,
            reviewed=reviewed_count > 0,
        )


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

    async def count_agent_jobs_for_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
    ) -> dict[str, int]:
        if not project_ids:
            return {}
        stmt = (
            select(AgentJob.project_id, func.count(AgentJob.job_id))
            .where(AgentJob.project_id.in_(project_ids), AgentJob.tenant_key == tenant_key)
            .group_by(AgentJob.project_id)
        )
        result = await session.execute(stmt)
        return dict(result.all())

    async def count_messages_for_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
    ) -> dict[str, int]:
        if not project_ids:
            return {}
        stmt = (
            select(Message.project_id, func.count(Message.id))
            .where(Message.project_id.in_(project_ids), Message.tenant_key == tenant_key)
            .group_by(Message.project_id)
        )
        result = await session.execute(stmt)
        return dict(result.all())

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

    async def get_latest_closeout_summaries(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
    ) -> dict[str, str]:
        if not project_ids:
            return {}
        query = (
            select(ProductMemoryEntry.project_id, ProductMemoryEntry.summary)
            .where(
                ProductMemoryEntry.project_id.in_(project_ids),
                ProductMemoryEntry.tenant_key == tenant_key,
                ProductMemoryEntry.entry_type.in_(("project_closeout", "project_completion")),
                ProductMemoryEntry.deleted_by_user.is_(False),
                ProductMemoryEntry.summary.is_not(None),
            )
            .ext(distinct_on(ProductMemoryEntry.project_id))
            .order_by(ProductMemoryEntry.project_id, ProductMemoryEntry.sequence.desc())
        )
        result = await session.execute(query)
        return dict(result.all())


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
