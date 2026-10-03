# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import AgentExecution, AgentJob, Message, Project, Task
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.platform_registry import normalize_execution_mode
from giljo_mcp.repositories._project_enrichment_reads_mixin import project_not_trashed
from giljo_mcp.utils.taxonomy_alias import format_taxonomy_alias


_LIVE_MEMORY_ENTRY_CRITERIA = (
    Product.deleted_at.is_(None),
    ProductMemoryEntry.deleted_by_user.is_not(True),
)


class ProductStatisticsRepository:

    def __init__(self, db_manager):
        self.db = db_manager


    async def get_project_stats_aggregated(
        self,
        session: AsyncSession,
        tenant_key: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple]:
        agent_count = (
            select(func.count(AgentExecution.agent_id))
            .select_from(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == Project.id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.tenant_key == tenant_key,
            )
            .correlate(Project)
            .scalar_subquery()
        )
        message_count = (
            select(func.count(Message.id))
            .where(Message.project_id == Project.id, Message.tenant_key == tenant_key)
            .correlate(Project)
            .scalar_subquery()
        )
        task_count = (
            select(func.count(Task.id))
            .where(Task.project_id == Project.id, Task.tenant_key == tenant_key, Task.deleted_at.is_(None))
            .correlate(Project)
            .scalar_subquery()
        )
        completed_task_count = (
            select(func.count(Task.id))
            .where(
                Task.project_id == Project.id,
                Task.tenant_key == tenant_key,
                Task.status == "completed",
                Task.deleted_at.is_(None),
            )
            .correlate(Project)
            .scalar_subquery()
        )
        last_activity = (
            select(func.max(Message.created_at))
            .where(Message.project_id == Project.id, Message.tenant_key == tenant_key)
            .correlate(Project)
            .scalar_subquery()
        )

        query = select(
            Project,
            func.coalesce(agent_count, 0),
            func.coalesce(message_count, 0),
            func.coalesce(task_count, 0),
            func.coalesce(completed_task_count, 0),
            last_activity,
        ).where(Project.tenant_key == tenant_key, project_not_trashed())

        if status:
            query = query.where(Project.status == status)

        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        return list(result.all())


    async def get_project_status_distribution(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> dict[str, int]:
        stmt = (
            select(Project.status, func.count(Project.id))
            .where(Project.tenant_key == tenant_key, project_not_trashed())
            .group_by(Project.status)
        )
        if product_id:
            stmt = stmt.where(Project.product_id == product_id)
        result = await session.execute(stmt)
        return dict(result.all())

    async def get_project_taxonomy_distribution(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> list[dict]:
        typed_stmt = (
            select(
                TaxonomyType.label,
                TaxonomyType.color,
                func.count(Project.id).label("count"),
            )
            .join(
                TaxonomyType,
                and_(
                    Project.project_type_id == TaxonomyType.id,
                    TaxonomyType.tenant_key == tenant_key,
                ),
            )
            .where(
                Project.tenant_key == tenant_key,
                Project.project_type_id.is_not(None),
                project_not_trashed(),
            )
            .group_by(TaxonomyType.label, TaxonomyType.color)
        )
        if product_id:
            typed_stmt = typed_stmt.where(Project.product_id == product_id)
        typed_result = await session.execute(typed_stmt)
        rows = [{"label": row.label, "color": row.color, "count": row.count} for row in typed_result.all()]

        untyped_stmt = select(func.count(Project.id)).where(
            Project.tenant_key == tenant_key,
            Project.project_type_id.is_(None),
            project_not_trashed(),
        )
        if product_id:
            untyped_stmt = untyped_stmt.where(Project.product_id == product_id)
        untyped_count = await session.scalar(untyped_stmt) or 0

        if untyped_count > 0:
            rows.append({"label": "Untyped", "color": "#9E9E9E", "count": untyped_count})

        return rows

    async def get_recent_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        stmt = (
            select(
                Project.id,
                Project.name,
                Project.status,
                Project.created_at,
                Project.completed_at,
                Project.alias,
                Project.project_type_id,
                Project.series_number,
                Project.subseries,
                Project.product_id,
                TaxonomyType.abbreviation.label("type_abbreviation"),
                TaxonomyType.color.label("project_type_color"),
                Product.name.label("product_name"),
            )
            .outerjoin(
                TaxonomyType,
                and_(
                    Project.project_type_id == TaxonomyType.id,
                    TaxonomyType.tenant_key == tenant_key,
                ),
            )
            .outerjoin(
                Product,
                and_(
                    Project.product_id == Product.id,
                    Product.tenant_key == tenant_key,
                    Product.deleted_at.is_(None),
                ),
            )
            .where(
                Project.tenant_key == tenant_key,
                Project.status == ProjectStatus.COMPLETED,
                Project.completed_at.isnot(None),
                project_not_trashed(),
            )
            .order_by(Project.completed_at.desc())
            .limit(limit)
        )
        if product_id:
            stmt = stmt.where(Project.product_id == product_id)

        result = await session.execute(stmt)
        rows = result.all()

        projects = []
        for row in rows:
            abbr = row.type_abbreviation if (row.project_type_id and row.type_abbreviation) else None
            taxonomy_alias = format_taxonomy_alias(abbr, row.series_number, row.subseries, fallback=row.alias)

            projects.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "status": row.status,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "taxonomy_alias": taxonomy_alias,
                    "project_type_color": row.project_type_color,
                    "product_name": row.product_name,
                    "product_id": str(row.product_id) if row.product_id else None,
                }
            )

        return projects

    async def get_recent_memory_entries(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        stmt = (
            select(
                ProductMemoryEntry.product_id,
                ProductMemoryEntry.project_id,
                ProductMemoryEntry.project_name,
                ProductMemoryEntry.summary,
                ProductMemoryEntry.timestamp,
                ProductMemoryEntry.entry_type,
                ProductMemoryEntry.git_commits,
                Product.name.label("product_name"),
            )
            .outerjoin(
                Product,
                and_(
                    ProductMemoryEntry.product_id == Product.id,
                    Product.tenant_key == tenant_key,
                ),
            )
            .where(ProductMemoryEntry.tenant_key == tenant_key, *_LIVE_MEMORY_ENTRY_CRITERIA)
            .order_by(ProductMemoryEntry.timestamp.desc())
            .limit(limit)
        )
        if product_id:
            stmt = stmt.where(ProductMemoryEntry.product_id == product_id)

        result = await session.execute(stmt)
        return [
            {
                "product_id": str(row.product_id) if row.product_id else None,
                "project_id": str(row.project_id) if row.project_id else None,
                "project_name": row.project_name,
                "summary": (row.summary[:200] if row.summary else None),
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "entry_type": row.entry_type,
                "git_commits": row.git_commits or [],
                "product_name": row.product_name,
            }
            for row in result.all()
        ]

    async def get_total_commits(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> int:
        stmt = (
            select(func.coalesce(func.sum(func.jsonb_array_length(ProductMemoryEntry.git_commits)), 0))
            .select_from(ProductMemoryEntry)
            .outerjoin(
                Product,
                and_(
                    ProductMemoryEntry.product_id == Product.id,
                    Product.tenant_key == tenant_key,
                ),
            )
            .where(ProductMemoryEntry.tenant_key == tenant_key, *_LIVE_MEMORY_ENTRY_CRITERIA)
            .where(func.jsonb_typeof(ProductMemoryEntry.git_commits) == "array")
        )
        if product_id:
            stmt = stmt.where(ProductMemoryEntry.product_id == product_id)
        result = await session.scalar(stmt)
        return int(result or 0)

    async def get_task_status_distribution(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> dict[str, int]:
        stmt = (
            select(Task.status, func.count(Task.id))
            .where(Task.tenant_key == tenant_key, Task.deleted_at.is_(None))
            .group_by(Task.status)
        )
        if product_id:
            stmt = stmt.where(Task.product_id == product_id)
        result = await session.execute(stmt)
        return dict(result.all())

    async def get_execution_mode_distribution(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> dict[str, int]:
        stmt = (
            select(Project.execution_mode, func.count(Project.id))
            .where(Project.tenant_key == tenant_key, project_not_trashed())
            .group_by(Project.execution_mode)
        )
        if product_id:
            stmt = stmt.where(Project.product_id == product_id)
        result = await session.execute(stmt)
        distribution: dict[str, int] = {}
        for mode, count in result.all():
            key = "unset" if mode is None else (normalize_execution_mode(mode) or "unset")
            distribution[key] = distribution.get(key, 0) + count
        return distribution

    async def get_product_project_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> list[dict]:
        stmt = (
            select(
                Product.id.label("product_id"),
                Product.name.label("product_name"),
                func.count(Project.id).label("project_count"),
            )
            .outerjoin(
                Project,
                and_(
                    Product.id == Project.product_id,
                    Project.tenant_key == tenant_key,
                    project_not_trashed(),
                ),
            )
            .where(Product.tenant_key == tenant_key, Product.deleted_at.is_(None))
            .group_by(Product.id, Product.name)
            .order_by(Product.name)
        )
        result = await session.execute(stmt)
        return [
            {
                "product_id": row.product_id,
                "product_name": row.product_name,
                "project_count": row.project_count,
            }
            for row in result.all()
        ]
