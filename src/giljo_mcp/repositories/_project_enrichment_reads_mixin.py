# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""ProjectRepository enrichment & summary reads (BE-6005 split).

Cohesive read-only query group extracted from ``ProjectRepository`` to keep that
module under the 800-line guardrail: per-project and batched (grouped-IN) agent
job/execution reads, 360-memory and message reads, agent status-count /
last-activity aggregation, and product / vision-doc lookups. Inherited by
``ProjectRepository`` so the public repository API is unchanged. All methods
enforce tenant_key isolation; the session is passed in by the caller. Behavior
is byte-identical to the pre-split single-class repository.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message


class ProjectEnrichmentReadsMixin:
    """Enrichment, batched-IN, summary, and vision reads. Inherited by ProjectRepository."""

    # ============================================================================
    # Read Operations — ProjectQueryService
    # ============================================================================

    async def get_active_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> list[Project]:
        """Get every currently active project for a tenant, optionally scoped to one product.

        BE-9525a product-scoped this read; BE-9525b (ruling 5 amended) dropped
        ``idx_project_single_active_per_product``, so more than one project can
        legitimately be ACTIVE in the same product now. A ``.limit(1)`` +
        ``scalar_one_or_none()`` here would be the same arbitrary-but-stable
        wrong-answer class BE-9521 fixed for a different read (FE-9524 hit it
        again on ``ProductRepository.get_active_product``) -- there is no
        single-row guarantee left to lean on, so this returns every match,
        deterministically ordered, instead of picking one.
        """
        conditions = [Project.tenant_key == tenant_key, Project.status == ProjectStatus.ACTIVE]
        if product_id is not None:
            conditions.append(Project.product_id == product_id)
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
        """Count agent jobs for a project."""
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
        """Count messages for a project."""
        stmt = select(func.count(Message.id)).where(Message.project_id == project_id, Message.tenant_key == tenant_key)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_agent_job_type_summary(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list:
        """Get agent job type counts for a project."""
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
        """Get detailed agent job/execution pairs for a project."""
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
        """Get 360 memory entries for a project.

        When ``limit`` is set, returns the most recent ``limit`` entries
        (highest sequence first), then re-orders ascending so callers see a
        chronological view of the trailing window. When unset, returns the
        full chronological history.
        """
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
        """Get messages for a project ordered by creation time.

        BE-6071 F6c: when ``limit`` is set, returns the most recent ``limit``
        messages (created_at DESC LIMIT pushed to SQL) then re-orders ascending
        so callers see a chronological view of the trailing window — mirrors
        ``get_memory_entries_for_project``. When unset, returns the full
        chronological history (byte-compatible with the prior behavior).
        """
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

    # ============================================================================
    # BE-6071 F6b: batched (grouped-IN) enrichment reads. Each runs ONE query
    # over the listed project_ids and groups by project_id in Python (the
    # established BE-6066 pattern), replacing the per-project N+1 in
    # _build_mcp_project_list. No window functions — the per-project memory cap
    # is applied in Python by the query service.
    # ============================================================================

    async def get_agent_job_type_summaries_for_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
    ) -> dict[str, list]:
        """Grouped agent job-type counts for many projects: {project_id: [rows]}."""
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
        """Grouped agent job/execution pairs for many projects: {project_id: [(job, exec)]}."""
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
        """Grouped 360 memory entries for many projects: {project_id: [entries asc by sequence]}.

        Returns the full per-project history (ascending by sequence); the caller
        applies any trailing-window cap in Python.
        """
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

    # ============================================================================
    # Read Operations — ProjectSummaryService
    # ============================================================================

    async def get_agent_status_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> dict:
        """Aggregate agent execution status counts for a project."""
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
        """Get the most recent activity timestamp for a project's agents."""
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
        """Get a product by ID with tenant isolation."""
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

    # ============================================================================
    # Read Operations — ConsolidatedVisionService
    # ============================================================================

    async def get_product_with_vision_docs(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ):
        """Get a product with eagerly loaded vision documents."""
        from giljo_mcp.models.products import Product

        result = await session.execute(
            select(Product)
            .options(selectinload(Product.vision_documents))
            .where(Product.id == product_id, Product.tenant_key == tenant_key)
        )
        return result.scalar_one_or_none()
