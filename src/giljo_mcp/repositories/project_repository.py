# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import String, and_, asc, cast, delete, desc, func, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.models.roadmaps import RoadmapItem
from giljo_mcp.models.tasks import Message, Task
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.repositories._project_enrichment_reads_mixin import ProjectEnrichmentReadsMixin, project_not_trashed
from giljo_mcp.repositories._project_keyset import (
    completion_recency_order_clauses,
    keyset_axis_for_sort_key,
    project_keyset_after,
)


logger = logging.getLogger(__name__)

MAX_SERIES_NUMBER = 9999


class ProjectRepository(ProjectEnrichmentReadsMixin):

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def add(self, session: AsyncSession, project: Project) -> None:
        session.add(project)

    async def refresh(self, session: AsyncSession, entity: Project) -> None:
        await session.refresh(entity)

    async def flush(self, session: AsyncSession) -> None:
        await session.flush()


    async def lock_rows_for_series_shared(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None,
    ) -> None:
        if not tenant_key:
            raise ValueError("tenant_key is required to lock a series-number bucket")

        bucket_key = f"taxonomy:{tenant_key}:{product_id or ''}"
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": bucket_key},
        )

        project_lock = select(Project.id).where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
        )
        task_lock = select(Task.id).where(
            Task.tenant_key == tenant_key,
            Task.product_id == product_id,
        )

        await session.execute(project_lock.with_for_update())
        await session.execute(task_lock.with_for_update())

    async def get_next_series_number_shared(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None,
    ) -> int:
        project_max_q = select(func.coalesce(func.max(Project.series_number), 0)).where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            project_not_trashed(),
        )
        task_max_q = select(func.coalesce(func.max(Task.series_number), 0)).where(
            Task.tenant_key == tenant_key,
            Task.product_id == product_id,
            Task.deleted_at.is_(None),
        )

        project_max = (await session.execute(project_max_q)).scalar_one()
        task_max = (await session.execute(task_max_q)).scalar_one()
        next_series_number = max(project_max, task_max) + 1
        if next_series_number > MAX_SERIES_NUMBER:
            raise ValidationError(
                message=f"Serial space exhausted: this product has used all serials "
                f"1-{MAX_SERIES_NUMBER}. Cannot assign a new project or task number.",
                context={"product_id": product_id, "next_series_number": next_series_number},
            )
        return next_series_number

    async def check_duplicate_taxonomy(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None,
        project_type_id: str | None,
        series_number: int,
        subseries: str | None,
    ) -> bool:
        dup_query = select(Project.id).where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            Project.series_number == series_number,
            project_not_trashed(),
        )
        if project_type_id:
            dup_query = dup_query.where(Project.project_type_id == project_type_id)
        else:
            dup_query = dup_query.where(Project.project_type_id.is_(None))
        if subseries is not None:
            dup_query = dup_query.where(Project.subseries == subseries)
        else:
            dup_query = dup_query.where(Project.subseries.is_(None))
        dup_result = await session.execute(dup_query)
        return dup_result.scalar_one_or_none() is not None

    async def get_with_project_type(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        with tenant_session_context(session, tenant_key):
            result = await session.execute(
                select(Project)
                .options(selectinload(Project.project_type))
                .where(Project.tenant_key == tenant_key)
                .where(Project.id == project_id)
            )
        return result.scalar_one_or_none()

    async def get_by_id_with_type(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        result = await session.execute(
            select(Project)
            .options(selectinload(Project.project_type))
            .where(Project.tenant_key == tenant_key, Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        result = await session.execute(
            select(Project).where(and_(Project.id == project_id, Project.tenant_key == tenant_key))
        )
        return result.scalar_one_or_none()

    async def get_project_type_by_label(
        self,
        session: AsyncSession,
        tenant_key: str,
        label: str,
    ) -> TaxonomyType | None:
        result = await session.execute(
            select(TaxonomyType).where(
                TaxonomyType.tenant_key == tenant_key,
                func.lower(TaxonomyType.label) == label.lower(),
            )
        )
        return result.scalar_one_or_none()

    async def get_project_type_by_abbreviation(
        self,
        session: AsyncSession,
        tenant_key: str,
        abbreviation: str,
    ) -> TaxonomyType | None:
        result = await session.execute(
            select(TaxonomyType).where(
                TaxonomyType.tenant_key == tenant_key,
                func.upper(TaxonomyType.abbreviation) == abbreviation.upper(),
            )
        )
        return result.scalar_one_or_none()

    async def get_agent_pairs_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list:
        agent_query = (
            select(AgentJob, AgentExecution)
            .join(AgentExecution, AgentJob.job_id == AgentExecution.job_id)
            .where(AgentJob.project_id == project_id, AgentJob.tenant_key == tenant_key)
            .order_by(AgentJob.created_at)
        )
        agent_result = await session.execute(agent_query)
        return agent_result.all()

    ROADMAP_SORT_KEY: ClassVar[str] = "roadmap"

    COMPLETION_RECENCY_SORT_KEY: ClassVar[str] = "completion_recency"

    _SORT_COLUMNS: ClassVar[dict] = {
        "series_number": Project.series_number,
        "name": Project.name,
        "created_at": Project.created_at,
        "completed_at": Project.completed_at,
        "status": Project.status,
        "staging_status": Project.staging_status,
    }

    def _build_list_conditions(
        self,
        tenant_key: str,
        status: str | list[str] | None,
        include_cancelled: bool,
        product_id: str | None,
        hidden: bool | None,
        search: str | None,
    ) -> list:
        conditions: list = [Project.tenant_key == tenant_key]

        if product_id:
            conditions.append(Project.product_id == product_id)

        if hidden is True:
            conditions.append(Project.hidden.is_(true()))
        elif hidden is False:
            conditions.append(Project.hidden.isnot(true()))

        if status:
            status_list = [status] if isinstance(status, str) else list(status)
            if len(status_list) == 1:
                only = status_list[0]
                conditions.append(Project.status == only)
                if only == "deleted":
                    conditions.append(Project.deleted_at.isnot(None))
                else:
                    conditions.append(project_not_trashed())
            else:
                conditions.append(Project.status.in_(status_list))
                conditions.append(project_not_trashed())
        else:
            conditions.append(project_not_trashed())
            if not include_cancelled:
                conditions.append(Project.status != ProjectStatus.CANCELLED)

        if search:
            needle = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            term = f"%{needle}%"
            conditions.append(
                or_(
                    Project.name.ilike(term, escape="\\"),
                    cast(Project.id, String).ilike(term, escape="\\"),
                    Project.taxonomy_alias.ilike(term, escape="\\"),
                    Project.description.ilike(term, escape="\\"),
                    Project.alias.ilike(term, escape="\\"),
                )
            )

        return conditions

    def _resolve_order(self, sort_key: str | None, sort_dir: str | None) -> list:
        col = self._SORT_COLUMNS.get(sort_key or "")
        if col is None:
            return []
        descending = (sort_dir or "asc").lower() == "desc"
        ordering = (desc(col) if descending else asc(col)).nulls_last()
        return [ordering, Project.id.asc()]

    def _roadmap_order_clauses(self, tenant_key: str, sort_dir: str | None) -> list:
        rm_sort = (
            select(RoadmapItem.sort_order)
            .where(
                RoadmapItem.project_id == Project.id,
                RoadmapItem.item_type == "project",
                RoadmapItem.tenant_key == tenant_key,
            )
            .limit(1)
            .scalar_subquery()
        )
        descending = (sort_dir or "asc").lower() == "desc"
        ordering = (desc(rm_sort) if descending else asc(rm_sort)).nulls_last()
        return [ordering, Project.id.asc()]

    async def list_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        status: str | list[str] | None = None,
        include_cancelled: bool = False,
        product_id: str | None = None,
        hidden: bool | None = None,
        search: str | None = None,
        sort_key: str | None = None,
        sort_dir: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        after_key: tuple[Any, str] | None = None,
    ) -> list[Project]:
        conditions = self._build_list_conditions(tenant_key, status, include_cancelled, product_id, hidden, search)
        query = select(Project).options(selectinload(Project.project_type)).where(*conditions)

        if sort_key == self.ROADMAP_SORT_KEY:
            query = query.order_by(*self._roadmap_order_clauses(tenant_key, sort_dir))
        elif sort_key == self.COMPLETION_RECENCY_SORT_KEY:
            query = query.order_by(*completion_recency_order_clauses())
        elif order_clauses := self._resolve_order(sort_key, sort_dir):
            query = query.order_by(*order_clauses)
        elif limit is not None or offset is not None:
            query = query.order_by(Project.created_at.desc(), Project.id.asc())

        if after_key is not None:
            query = query.where(project_keyset_after(keyset_axis_for_sort_key(sort_key), *after_key))

        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def count_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        status: str | list[str] | None = None,
        include_cancelled: bool = False,
        product_id: str | None = None,
        hidden: bool | None = None,
        search: str | None = None,
    ) -> int:
        conditions = self._build_list_conditions(tenant_key, status, include_cancelled, product_id, hidden, search)
        query = select(func.count()).select_from(Project).where(*conditions)
        result = await session.execute(query)
        return int(result.scalar() or 0)

    async def board_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> list[tuple[str | None, str | None, datetime | None, datetime | None, int]]:
        query = (
            select(
                Project.status,
                TaxonomyType.abbreviation,
                func.min(Project.created_at),
                func.max(Project.created_at),
                func.min(Project.completed_at),
                func.max(Project.completed_at),
                func.count(),
            )
            .select_from(Project)
            .outerjoin(TaxonomyType, Project.project_type_id == TaxonomyType.id)
            .where(Project.tenant_key == tenant_key, project_not_trashed())
            .group_by(Project.status, TaxonomyType.abbreviation)
        )
        if product_id:
            query = query.where(Project.product_id == product_id)
        result = await session.execute(query)
        return list(result.all())


    async def get_active_executions_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[AgentExecution]:
        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                    AgentExecution.status.notin_(["complete", "decommissioned"]),
                )
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_agent_jobs_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[AgentJob]:
        stmt = select(AgentJob).where(and_(AgentJob.project_id == project_id, AgentJob.tenant_key == tenant_key))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_user_approvals_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[UserApproval]:
        stmt = select(UserApproval).where(
            and_(UserApproval.project_id == project_id, UserApproval.tenant_key == tenant_key)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_tasks_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list:
        from giljo_mcp.models.tasks import Task

        stmt = select(Task).where(and_(Task.project_id == project_id, Task.tenant_key == tenant_key))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_messages_for_deletion(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[Message]:
        stmt = select(Message).where(and_(Message.project_id == project_id, Message.tenant_key == tenant_key))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def delete_entity(self, session: AsyncSession, entity) -> None:
        await session.delete(entity)

    async def bulk_delete_user_approvals_for_project(
        self, session: AsyncSession, tenant_key: str, project_id: str
    ) -> int:
        result = await session.execute(
            delete(UserApproval)
            .where(and_(UserApproval.project_id == project_id, UserApproval.tenant_key == tenant_key))
            .execution_options(synchronize_session=False)
        )
        return result.rowcount or 0

    async def bulk_delete_agent_jobs_for_project(self, session: AsyncSession, tenant_key: str, project_id: str) -> int:
        await session.execute(
            delete(AgentExecution)
            .where(
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.job_id.in_(
                    select(AgentJob.job_id).where(
                        and_(AgentJob.project_id == project_id, AgentJob.tenant_key == tenant_key)
                    )
                ),
            )
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(
            delete(AgentJob)
            .where(and_(AgentJob.project_id == project_id, AgentJob.tenant_key == tenant_key))
            .execution_options(synchronize_session=False)
        )
        return result.rowcount or 0

    async def bulk_delete_messages_for_project(self, session: AsyncSession, tenant_key: str, project_id: str) -> int:
        result = await session.execute(
            delete(Message)
            .where(and_(Message.project_id == project_id, Message.tenant_key == tenant_key))
            .execution_options(synchronize_session=False)
        )
        return result.rowcount or 0

    async def get_deleted_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> list[Project]:
        conditions = [
            Project.tenant_key == tenant_key,
            Project.status == ProjectStatus.DELETED,
            Project.deleted_at.isnot(None),
        ]
        if product_id:
            conditions.append(Project.product_id == product_id)
        stmt = select(Project).where(and_(*conditions))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_expired_deleted_projects(
        self,
        session: AsyncSession,
        cutoff_date: datetime,
    ) -> list[Project]:
        stmt = select(Project).where(
            Project.deleted_at.isnot(None),
            Project.status == ProjectStatus.DELETED,
            Project.deleted_at < cutoff_date,
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
