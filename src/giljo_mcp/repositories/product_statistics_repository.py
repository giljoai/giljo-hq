# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Product and project statistics repository — projects, messages, tasks, dashboard analytics."""

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import AgentExecution, AgentJob, Message, Project, Task
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.platform_registry import normalize_execution_mode
from giljo_mcp.utils.taxonomy_alias import format_taxonomy_alias


# What makes a 360 memory entry eligible for the dashboard. Two independent
# liveness facts, both of which these readers used to ignore:
#
# 1. Soft-deleting a PRODUCT does not cascade -- ``delete_product`` stamps
#    ``deleted_at`` on the product row alone -- so a reader has to revalidate the
#    product each entry points at, or a trashed product keeps feeding the
#    dashboard for the whole recovery window.
# 2. Purging a PROJECT does reach these rows: ``mark_entries_deleted``
#    (product_memory_repository) flags its entries ``deleted_by_user`` and keeps
#    them for history. Reached from the project purge endpoint AND from the
#    background expiry sweep -- a live path, not scaffolding.
#
# One definition, two call sites on purpose: the 360 Memories panel and the
# Commits tile are derived from the same rows (DashboardView builds its commit
# preview out of ``recent_memories``), so a predicate applied to only one of them
# would leave the panel and the counter disagreeing -- the same defect, moved.
# Both joins carry the same ON clause for the same reason.
#
# ``deleted_at`` and NOT ``is_active``: deactivating a product is not trashing it
# (``deactivate_product`` clears ``is_active`` and leaves ``deleted_at`` NULL),
# and a dormant product's history still belongs on the dashboard. This matches
# every sibling reader (product_repository, task_repository,
# vision_document_repository, product_memory_repository).
#
# ``is_not(True)`` rather than the sibling ``== False`` spelling because the
# column is NULLABLE in the shipped schema and the 0390a backfill wrote
# ``COALESCE(..., false)`` -- a NULL means "not deleted", and must not silently
# drop a live entry off the dashboard.
#
# Deliberately NOT extended to the projects a trashed product owns:
# ``project_repository`` holds no reference to ``Product`` and never filters on
# product liveness, so those projects stay visible everywhere else in the app --
# hiding them here alone would manufacture a disagreement rather than remove one.
# Do not reach for FK nullability to justify that line: ``projects.product_id``
# and ``product_memory_entries.product_id`` are BOTH ``ondelete="CASCADE"``, so
# nullability says nothing about ownership. The reason is the reader survey above.
#
# BE-9354 closed the remaining dashboard half WITHOUT reopening that decision.
# ``get_recent_projects`` still SELECTed ``Product.name``, so a trashed product's
# name kept rendering beside its completed projects (RecentProjectsList.vue:18).
# The fix neutralises the NAME -- the same liveness predicate, moved into that
# method's ``Product`` outerjoin ON clause, so a trashed parent yields a NULL
# ``product_name`` -- and leaves project visibility exactly as it was. Hiding the
# projects instead would have relocated the disagreement rather than removed it:
# their tasks, chain runs (``sequence_run_live_filter`` reads ``Project``
# directly, bypassing the repository), roadmap items and jobs would all have
# stayed visible.
#
# Callers must have joined :class:`Product`.
_LIVE_MEMORY_ENTRY_CRITERIA = (
    Product.deleted_at.is_(None),
    ProductMemoryEntry.deleted_by_user.is_not(True),
)


class ProductStatisticsRepository:
    """
    Repository for product-level statistics queries.

    Covers project counts and pagination, tenant-wide message stats,
    task counts, and dashboard distribution analytics. All methods
    enforce tenant isolation via tenant_key.
    """

    def __init__(self, db_manager):
        """
        Initialize product statistics repository.

        Args:
            db_manager: Database manager instance
        """
        self.db = db_manager

    # ============================================================================
    # PROJECT STATISTICS DOMAIN
    # ============================================================================

    async def count_total_projects(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> int:
        """
        Count total projects for tenant.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            Total project count (soft-deleted projects excluded — BE-9355)
        """
        result = await session.scalar(
            select(func.count(Project.id)).where(Project.tenant_key == tenant_key, Project.deleted_at.is_(None))
        )
        return result or 0

    async def count_projects_by_status(
        self,
        session: AsyncSession,
        tenant_key: str,
        status: str,
    ) -> int:
        """
        Count projects with specific status for tenant.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            status: Project status to filter by

        Returns:
            Project count for status

        BE-9355 (hygiene, not a defect fix): the soft-delete writer stamps
        ``status='deleted'`` and ``deleted_at`` together
        (``project_deletion_service.py:99-100``) and ``restore_project`` clears
        both, so a trashed row already sits in a bucket no caller asks for. The
        predicate makes the two liveness facts stop depending on each other, and
        matches every sibling in this file.
        """
        result = await session.scalar(
            select(func.count(Project.id)).where(
                Project.tenant_key == tenant_key,
                Project.status == status,
                Project.deleted_at.is_(None),
            )
        )
        return result or 0

    async def count_projects_staged(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> int:
        """Count LIVE projects with staging_status in ('staged', 'staging_complete').

        BE-9355: ``staging_status`` is untouched by soft-delete, so a trashed
        project kept its staged marking and inflated this tile.
        """
        result = await session.scalar(
            select(func.count(Project.id)).where(
                Project.tenant_key == tenant_key,
                Project.staging_status.in_(("staged", "staging_complete")),
                Project.deleted_at.is_(None),
            )
        )
        return result or 0

    async def get_project_stats_aggregated(
        self,
        session: AsyncSession,
        tenant_key: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple]:
        """Get paginated projects with per-project aggregate counts in ONE round-trip.

        Collapses the BE-6063b N+1 (the endpoint previously fired 5 separate
        ``get_session_async`` round-trips per project). Correlated scalar
        subqueries keep each project to exactly one row (no join fan-out). Returns
        rows of (Project, agent_count, message_count, task_count,
        completed_task_count, last_activity); counts are non-NULL ints.

        BE-9355 (hygiene): no PRODUCTION caller reaches this method today — the
        only callers are tests. The liveness predicate is applied anyway so that
        whichever paginated project surface adopts it later does not inherit the
        defect its siblings in this file had.
        """
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
        ).where(Project.tenant_key == tenant_key, Project.deleted_at.is_(None))

        if status:
            query = query.where(Project.status == status)

        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        return list(result.all())

    # ============================================================================
    # MESSAGE STATISTICS DOMAIN
    # ============================================================================

    async def count_total_messages(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> int:
        """
        Count total messages for tenant.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            Total message count
        """
        result = await session.scalar(select(func.count(Message.id)).where(Message.tenant_key == tenant_key))
        return result or 0

    async def count_messages_by_status(
        self,
        session: AsyncSession,
        tenant_key: str,
        status: str,
    ) -> int:
        """Count messages with a specific status for the tenant."""
        result = await session.scalar(
            select(func.count(Message.id)).where(Message.tenant_key == tenant_key, Message.status == status)
        )
        return result or 0

    # ============================================================================
    # TASK STATISTICS DOMAIN
    # ============================================================================

    async def count_total_tasks(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> int:
        """
        Count total tasks for tenant.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            Total task count
        """
        result = await session.scalar(
            select(func.count(Task.id)).where(Task.tenant_key == tenant_key, Task.deleted_at.is_(None))
        )
        return result or 0

    async def count_completed_tasks(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> int:
        """
        Count completed tasks for tenant.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            Completed task count
        """
        result = await session.scalar(
            select(func.count(Task.id)).where(
                Task.tenant_key == tenant_key, Task.status == "completed", Task.deleted_at.is_(None)
            )
        )
        return result or 0

    # ============================================================================
    # DASHBOARD ANALYTICS DOMAIN (Handover 0839)
    # ============================================================================

    async def get_project_status_distribution(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> dict[str, int]:
        """
        Get project count grouped by status.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            product_id: Optional product filter

        Returns:
            Dict mapping status to count, e.g. {"active": 5, "completed": 12}
        """
        stmt = (
            select(Project.status, func.count(Project.id))
            .where(Project.tenant_key == tenant_key, Project.deleted_at.is_(None))
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
        """
        Get project count grouped by project type (taxonomy).

        Includes an "Untyped" entry for projects with no project_type_id.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            product_id: Optional product filter

        Returns:
            List of dicts with keys: label, color, count
        """
        # Typed projects: join TaxonomyType, group by label + color
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
                Project.deleted_at.is_(None),
            )
            .group_by(TaxonomyType.label, TaxonomyType.color)
        )
        if product_id:
            typed_stmt = typed_stmt.where(Project.product_id == product_id)
        typed_result = await session.execute(typed_stmt)
        rows = [{"label": row.label, "color": row.color, "count": row.count} for row in typed_result.all()]

        # Untyped projects count
        untyped_stmt = select(func.count(Project.id)).where(
            Project.tenant_key == tenant_key,
            Project.project_type_id.is_(None),
            Project.deleted_at.is_(None),
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
        """
        Get the most recently completed projects.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            product_id: Optional product filter
            limit: Maximum number of results

        Returns:
            List of dicts with keys: id, name, status, created_at, completed_at,
            taxonomy_alias, project_type_color
        """
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
                    # BE-9354: in the ON clause, not the WHERE. A trashed parent
                    # must fail the join so ``product_name`` comes back NULL and
                    # the dashboard stops naming it -- while the project itself
                    # stays listed. In the WHERE this predicate would instead
                    # DROP the project, which is the visibility change this fix
                    # deliberately does not make.
                    Product.deleted_at.is_(None),
                ),
            )
            .where(
                Project.tenant_key == tenant_key,
                Project.status == ProjectStatus.COMPLETED,
                Project.completed_at.isnot(None),
                Project.deleted_at.is_(None),
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
            # BE-6049a: single-sourced via format_taxonomy_alias so this path
            # cannot drift from the SQL column_property (and pads min-4 without
            # truncating 5-6 digit grandfathered serials).
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
        """
        Get the most recent 360 memory entries.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            product_id: Optional product filter
            limit: Maximum number of results

        Returns:
            List of dicts with keys: project_name, summary, timestamp, entry_type
        """
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
        """Count the git commits recorded across live 360 memory entries (BE-6078).

        Sums ``jsonb_array_length(git_commits)`` over every LIVE
        ``product_memory_entries`` row for the tenant (and product, when the
        per-product dashboard filter is active). This is the true cumulative
        commit count — the dashboard previously showed only the capped 10-item
        preview length (DashboardView.vue), which never exceeded 10.

        Liveness is :data:`_LIVE_MEMORY_ENTRY_CRITERIA`, the same set the 360
        Memories panel applies, so the Commits tile and the commit preview built
        from that panel cannot disagree about which entries exist.

        Tenant-scoped and product-filter-aware. The ``jsonb_typeof = 'array'``
        guard skips rows whose ``git_commits`` is NULL or a non-array shape so a
        malformed legacy value can't raise instead of counting as zero.
        """
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
        """
        Get task count grouped by status.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            product_id: Optional product filter

        Returns:
            Dict mapping status to count, e.g. {"pending": 3, "completed": 10}
        """
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
        """
        Get project count grouped by execution_mode.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            product_id: Optional product filter

        Returns:
            Dict mapping the CANONICAL execution_mode to count, e.g.
            {"multi_terminal": 5, "subagent": 3, "unset": 1}.

        BE-9035c: the SQL GROUP BY buckets by the RAW stored value, so legacy
        ``*_cli`` / ``generic_mcp`` rows would otherwise show as separate buckets. We
        fold each stored value through :func:`normalize_execution_mode` and SUM the
        counts, so a legacy CLI row collapses into ``subagent`` (stored values are
        never rewritten — the fold is display-only). NULL stays ``unset``.

        BE-9355: soft-deleted projects are excluded. ``execution_mode`` survives a
        soft delete untouched, so a trashed project kept its bucket here while
        :meth:`get_project_status_distribution` — served in the SAME dashboard
        payload — already excluded it. One response described two different
        project totals at once.
        """
        stmt = (
            select(Project.execution_mode, func.count(Project.id))
            .where(Project.tenant_key == tenant_key, Project.deleted_at.is_(None))
            .group_by(Project.execution_mode)
        )
        if product_id:
            stmt = stmt.where(Project.product_id == product_id)
        result = await session.execute(stmt)
        distribution: dict[str, int] = {}
        for mode, count in result.all():
            # NULL-state: a project with no chosen execution mode groups under "unset"
            # (a None object key is not JSON-serializable). A concrete value folds to
            # its canonical mode so legacy tokens sum into the subagent bucket.
            key = "unset" if mode is None else (normalize_execution_mode(mode) or "unset")
            distribution[key] = distribution.get(key, 0) + count
        return distribution

    async def get_product_project_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> list[dict]:
        """
        Get project count per product (for product selector badges).

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            List of dicts with keys: product_id, product_name, project_count

        Trashed products are omitted and their soft-deleted projects are not
        counted, so this rollup agrees with
        :meth:`get_project_status_distribution` and with the product list the
        rest of the app serves.
        """
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
                    # In the ON clause, not the WHERE: a product whose only
                    # projects are trashed must still be listed, with a count of 0.
                    Project.deleted_at.is_(None),
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
