# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TaxonomyRepository - data access for the unified taxonomy_types table.

Renamed from ``ProjectTypeRepository`` in Phase A of the agent-parity +
unified Type taxonomy project (2026-05). The same physical table now backs
both project classification and task classification (see migrations
ce_0014 and ce_0015).

Tenant isolation is enforced at the query level on every operation.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.models.tasks import Task


logger = logging.getLogger(__name__)


class TaxonomyRepository:
    """Repository for taxonomy_types database operations.

    Methods accept an AsyncSession parameter (session-in pattern) so the
    calling service controls transaction boundaries.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def count_for_tenant(self, session: AsyncSession, tenant_key: str) -> int:
        """Count taxonomy types for a tenant."""
        result = await session.execute(
            select(func.count()).select_from(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key)
        )
        return result.scalar() or 0

    async def add_taxonomy_type(self, session: AsyncSession, taxonomy_type: TaxonomyType) -> None:
        """Add a taxonomy type to the session (no commit)."""
        session.add(taxonomy_type)

    async def flush(self, session: AsyncSession) -> None:
        """Flush the current session (write to DB without committing)."""
        await session.flush()

    async def get_by_abbreviation(
        self,
        session: AsyncSession,
        tenant_key: str,
        abbreviation: str,
    ) -> TaxonomyType | None:
        """Get a taxonomy type by abbreviation within a tenant."""
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
        """Get a taxonomy type by ID within a tenant."""
        result = await session.execute(
            select(TaxonomyType).where(
                TaxonomyType.id == type_id,
                TaxonomyType.tenant_key == tenant_key,
            )
        )
        return result.scalar_one_or_none()

    async def flush_and_refresh(self, session: AsyncSession, taxonomy_type: TaxonomyType) -> TaxonomyType:
        """Flush pending changes and refresh the taxonomy type."""
        await session.flush()
        await session.refresh(taxonomy_type)
        return taxonomy_type

    async def delete_taxonomy_type(self, session: AsyncSession, taxonomy_type: TaxonomyType) -> None:
        """Delete a taxonomy type and flush."""
        await session.delete(taxonomy_type)
        await session.flush()

    async def list_with_project_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> list[Any]:
        """List all taxonomy types with project counts, ordered by sort_order.

        Returns:
            List of (TaxonomyType, project_count) tuples.
        """
        # BE-9355: the liveness predicate belongs INSIDE the correlated subquery.
        # In the outer WHERE it would filter the taxonomy rows themselves, and a
        # type with no live projects would vanish from the picker instead of
        # showing zero.
        project_count_subq = (
            select(func.count(Project.id))
            .where(
                Project.project_type_id == TaxonomyType.id,
                Project.tenant_key == tenant_key,
                Project.deleted_at.is_(None),
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
        """Count LIVE projects assigned to a taxonomy type.

        BE-9355: soft-deleted projects are excluded because this count is the
        delete guard in ``taxonomy_ops.delete_taxonomy_type``. Counting a trashed
        project told the user to "reassign or remove" a project that was already
        removed and no longer reachable in the UI -- an instruction that could not
        be followed, leaving the type undeletable until the retention window
        expired. ``projects.project_type_id`` is ``ondelete="SET NULL"``, so the
        delete now detaches any trashed project rather than destroying it.
        """
        result = await session.execute(
            select(func.count(Project.id)).where(
                Project.project_type_id == type_id,
                Project.tenant_key == tenant_key,
                Project.deleted_at.is_(None),
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
        """Get the next available series number for a product (global, tag-agnostic).

        BE-6049b: this feeds the ``/next-series`` UI preview, which must AGREE with
        the allocator ``ProjectRepository.get_next_series_number_shared``. So the
        watermark is now ONE global ``max+1`` per ``(tenant_key, product_id)`` —
        across all tags and unioning both projects AND tasks — instead of the old
        per-type ``project_type_id`` filter. ``type_id`` is retained in the
        signature for the HTTP contract but is intentionally NOT used for bucketing.

        BE-6079 (M1): the ``product_id`` predicate is applied UNCONDITIONALLY, so a
        ``None`` product scopes to the ``product_id IS NULL`` bucket exactly as the
        allocator does (``Project.product_id == None`` renders ``IS NULL``). Without
        this the preview computed a tenant-wide max across all products when no
        product was active, diverging from what the allocator would actually mint.

        Soft-deleted projects AND tasks are excluded (ACTIVE pool only) so this
        preview agrees with the allocator after BE-6130b made tasks soft-delete.
        Returns 1 when the product has no rows.
        """
        project_query = select(func.coalesce(func.max(Project.series_number), 0)).where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            Project.deleted_at.is_(None),
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
        """Get all used series numbers for a taxonomy type within a product."""
        query = (
            select(Project.series_number)
            .where(
                Project.project_type_id == type_id,
                Project.tenant_key == tenant_key,
                Project.series_number.is_not(None),
                Project.deleted_at.is_(None),
            )
            .order_by(Project.series_number)
        )
        if product_id is not None:
            query = query.where(Project.product_id == product_id)
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
        """Check if a series number combination is available within a product."""
        query = select(Project.id).where(
            Project.tenant_key == tenant_key,
            Project.series_number == series_number,
            Project.deleted_at.is_(None),
        )
        if product_id is not None:
            query = query.where(Project.product_id == product_id)
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
        """Get all used subseries letters for a type + series_number within a product."""
        query = select(Project.subseries).where(
            Project.tenant_key == tenant_key,
            Project.series_number == series_number,
            Project.subseries.isnot(None),
            Project.deleted_at.is_(None),
        )
        if product_id is not None:
            query = query.where(Project.product_id == product_id)
        if type_id:
            query = query.where(Project.project_type_id == type_id)
        else:
            query = query.where(Project.project_type_id.is_(None))

        if exclude_project_id:
            query = query.where(Project.id != exclude_project_id)

        result = await session.execute(query)
        return sorted([row[0] for row in result.all()])
