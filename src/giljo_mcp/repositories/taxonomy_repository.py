# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.models.tasks import Task
from giljo_mcp.repositories._project_enrichment_reads_mixin import project_not_trashed


logger = logging.getLogger(__name__)


class TaxonomyRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def count_for_tenant(self, session: AsyncSession, tenant_key: str) -> int:
        result = await session.execute(
            select(func.count()).select_from(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key)
        )
        return result.scalar() or 0

    async def add_taxonomy_type(self, session: AsyncSession, taxonomy_type: TaxonomyType) -> None:
        session.add(taxonomy_type)

    async def flush(self, session: AsyncSession) -> None:
        await session.flush()

    async def get_by_abbreviation(
        self,
        session: AsyncSession,
        tenant_key: str,
        abbreviation: str,
    ) -> TaxonomyType | None:
        result = await session.execute(
            select(TaxonomyType).where(
                TaxonomyType.tenant_key == tenant_key,
                TaxonomyType.abbreviation == abbreviation,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        type_id: str,
    ) -> TaxonomyType | None:
        result = await session.execute(
            select(TaxonomyType).where(
                TaxonomyType.id == type_id,
                TaxonomyType.tenant_key == tenant_key,
            )
        )
        return result.scalar_one_or_none()

    async def flush_and_refresh(self, session: AsyncSession, taxonomy_type: TaxonomyType) -> TaxonomyType:
        await session.flush()
        await session.refresh(taxonomy_type)
        return taxonomy_type

    async def delete_taxonomy_type(self, session: AsyncSession, taxonomy_type: TaxonomyType) -> None:
        await session.delete(taxonomy_type)
        await session.flush()

    async def list_with_project_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> list[Any]:
        project_count_subq = (
            select(func.count(Project.id))
            .where(
                Project.project_type_id == TaxonomyType.id,
                Project.tenant_key == tenant_key,
                project_not_trashed(),
            )
            .correlate(TaxonomyType)
            .scalar_subquery()
            .label("project_count")
        )

        stmt = (
            select(TaxonomyType, project_count_subq)
            .where(TaxonomyType.tenant_key == tenant_key)
            .order_by(TaxonomyType.sort_order, TaxonomyType.abbreviation)
        )

        result = await session.execute(stmt)
        return result.all()

    async def get_project_count_for_type(
        self,
        session: AsyncSession,
        tenant_key: str,
        type_id: str,
    ) -> int:
        result = await session.execute(
            select(func.count(Project.id)).where(
                Project.project_type_id == type_id,
                Project.tenant_key == tenant_key,
                project_not_trashed(),
            )
        )
        return result.scalar() or 0

    async def get_next_series_number(
        self,
        session: AsyncSession,
        tenant_key: str,
        type_id: str,
        product_id: str | None = None,
    ) -> int:
        if not tenant_key:
            raise ValueError("tenant_key is required to compute the next series number")

        bucket_key = f"taxonomy:{tenant_key}:{product_id or ''}"
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": bucket_key},
        )

        project_query = select(func.coalesce(func.max(Project.series_number), 0)).where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            project_not_trashed(),
        )
        task_query = select(func.coalesce(func.max(Task.series_number), 0)).where(
            Task.tenant_key == tenant_key,
            Task.product_id == product_id,
            Task.deleted_at.is_(None),
        )

        project_max = (await session.execute(project_query)).scalar_one()
        task_max = (await session.execute(task_query)).scalar_one()
        return max(project_max, task_max) + 1

    async def get_used_series_numbers(
        self,
        session: AsyncSession,
        tenant_key: str,
        type_id: str,
        product_id: str | None = None,
    ) -> set[int]:
        query = (
            select(Project.series_number)
            .where(
                Project.project_type_id == type_id,
                Project.tenant_key == tenant_key,
                Project.product_id == product_id,
                Project.series_number.is_not(None),
                project_not_trashed(),
            )
            .order_by(Project.series_number)
        )
        result = await session.execute(query)
        return set(result.scalars().all())

    async def check_series_available(
        self,
        session: AsyncSession,
        tenant_key: str,
        type_id: str | None,
        series_number: int,
        subseries: str | None = None,
        exclude_project_id: str | None = None,
        product_id: str | None = None,
    ) -> bool:
        query = select(Project.id).where(
            Project.tenant_key == tenant_key,
            Project.series_number == series_number,
            Project.product_id == product_id,
            project_not_trashed(),
        )
        if type_id:
            query = query.where(Project.project_type_id == type_id)
        else:
            query = query.where(Project.project_type_id.is_(None))

        if subseries is not None:
            query = query.where(Project.subseries == subseries)
        else:
            query = query.where(Project.subseries.is_(None))

        if exclude_project_id:
            query = query.where(Project.id != exclude_project_id)

        result = await session.execute(query)
        return result.first() is None

    async def get_used_subseries(
        self,
        session: AsyncSession,
        tenant_key: str,
        type_id: str | None,
        series_number: int,
        exclude_project_id: str | None = None,
        product_id: str | None = None,
    ) -> list[str]:
        query = select(Project.subseries).where(
            Project.tenant_key == tenant_key,
            Project.series_number == series_number,
            Project.product_id == product_id,
            Project.subseries.isnot(None),
            project_not_trashed(),
        )
        if type_id:
            query = query.where(Project.project_type_id == type_id)
        else:
            query = query.where(Project.project_type_id.is_(None))

        if exclude_project_id:
            query = query.where(Project.id != exclude_project_id)

        result = await session.execute(query)
        return sorted([row[0] for row in result.all()])
