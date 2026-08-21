# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProjectRepository - Data access layer for core project CRUD and query operations.

BE-5022d: Extracted session operations from ProjectService, ProjectQueryService,
ProjectSummaryService, and ConsolidatedVisionService into repository methods.

All methods enforce tenant_key isolation. Session is passed by the caller.
"""

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
from giljo_mcp.repositories._project_enrichment_reads_mixin import ProjectEnrichmentReadsMixin
from giljo_mcp.repositories._project_keyset import (
    completion_recency_order_clauses,
    keyset_axis_for_sort_key,
    project_keyset_after,
)


logger = logging.getLogger(__name__)

# The 4-digit serial domain (decision D). The shared allocator is the single
# source of truth for this cap: when the next auto-assigned series_number would
# exceed this, the product has exhausted its serial space and allocation fails.
MAX_SERIES_NUMBER = 9999


class ProjectRepository(ProjectEnrichmentReadsMixin):
    """
    Repository for core project database operations.

    Covers: ProjectService CRUD, ProjectQueryService reads,
    ProjectSummaryService aggregation, ConsolidatedVisionService reads.

    All methods enforce tenant_key isolation.
    Session is passed in by the caller (service layer).
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ============================================================================
    # Core CRUD
    # ============================================================================

    async def add(self, session: AsyncSession, project: Project) -> None:
        """Add a project to the session."""
        session.add(project)

    async def refresh(self, session: AsyncSession, entity: Project) -> None:
        """Refresh an entity from the database."""
        await session.refresh(entity)

    async def flush(self, session: AsyncSession) -> None:
        """Flush pending changes."""
        await session.flush()

    # ============================================================================
    # Read Operations — ProjectService
    # ============================================================================

    async def lock_rows_for_series_shared(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None,
    ) -> None:
        """Serialize series_number assignment for a (tenant, product) bucket.

        BE-6049b: tasks and projects share ONE global monotonic series_number
        counter per ``(tenant_key, product_id)`` — the tag (``FE``/``BE``/``TSK``)
        is decoupled from the number, so every tag draws from a single
        continue-upward sequence. (Widened from the BE-5065 per-type
        ``(tenant, product, taxonomy_type_id)`` bucket.)

        Uses ``pg_advisory_xact_lock`` keyed on a deterministic hash of the
        bucket identifier. ``SELECT ... FOR UPDATE`` is insufficient on its own:
        when the bucket has no rows yet, two concurrent transactions both lock
        empty result sets and proceed to ``max(...) = 0``, producing duplicate
        ``series_number = 1`` values. The advisory lock is acquired BEFORE the
        max-aggregate and released automatically when the transaction commits
        or rolls back.

        FOR UPDATE is still applied to existing rows so any concurrent UPDATE
        on a bucket row blocks until we commit (defends against series mutation
        outside this path).

        ``tenant_key`` is the lock partition and is NEVER NULL — guard it so a
        missing tenant context can't collapse every tenant onto one bucket.
        """
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
        """Get next series_number across BOTH projects and tasks for a product.

        BE-6049b: ONE global ``max(projects.series_number, tasks.series_number) + 1``
        per ``(tenant_key, product_id)`` — every tag (``FE``/``BE``/``TSK``) shares
        this continue-upward sequence. Returns 1 when both tables are empty for the
        product. (Widened from the BE-5065 per-type bucket.)

        Soft-deleted projects are excluded from the high-water mark (decision C:
        compute over the ACTIVE pool). A soft-deleted ``9999`` left in the max
        would mint ``10000`` — the root cause of the 5-digit serials in prod.
        BE-6130b: tasks now ALSO soft-delete (trash/recover), so a trashed task's
        row survives and would inflate the max — both sides therefore exclude
        ``deleted_at IS NOT NULL`` rows. A restored task re-mints a fresh serial
        through this same allocator (decision C parity).

        BE-6079: the ``> MAX_SERIES_NUMBER`` exhaustion cap (decision D) lives
        HERE — the single allocator every auto-assign path funnels through
        (project create, task create-for-mcp, REST ``POST /api/v1/tasks``, the
        task→project conversion untyped-fallback, and restore). Centralizing it
        means no auto-assign caller can mint a 5-digit serial, so the inline
        per-service caps were removed.
        """
        project_max_q = select(func.coalesce(func.max(Project.series_number), 0)).where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            Project.deleted_at.is_(None),
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
        """Check if a taxonomy combination already exists. Returns True if duplicate."""
        dup_query = select(Project.id).where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            Project.series_number == series_number,
            Project.deleted_at.is_(None),
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
        """Get a project with eagerly loaded project_type relationship."""
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
        """Get a project by ID with tenant isolation and eagerly loaded project_type."""
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
        """Get a project by ID with tenant isolation (no relationship loading)."""
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
        """Resolve a project type by label (case-insensitive)."""
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
        """Resolve a project type by abbreviation (case-insensitive)."""
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
        """Get agent job/execution pairs for a project."""
        agent_query = (
            select(AgentJob, AgentExecution)
            .join(AgentExecution, AgentJob.job_id == AgentExecution.job_id)
            .where(AgentJob.project_id == project_id, AgentJob.tenant_key == tenant_key)
            .order_by(AgentJob.created_at)
        )
        agent_result = await session.execute(agent_query)
        return agent_result.all()

    # BE-6076: columns the dashboard projects-list may sort on server-side. Keys
    # match the v-data-table column ``key`` the frontend emits; values are the
    # SQL columns (``taxonomy_alias``/``status`` are SELECT-time column_property /
    # enum columns, both legal in ORDER BY). No key outside this map is honored —
    # an unknown sort_key falls through to the deterministic default order.
    # FE-6179: a non-column sort key. "roadmap" orders the list by each project's
    # position on the product roadmap (``roadmap_items.sort_order``) -- the SAME
    # ordering /roadmap renders -- via a correlated subquery, not a plain column,
    # so it lives outside ``_SORT_COLUMNS`` and is handled explicitly in
    # ``list_projects`` (see ``_roadmap_order_clauses``).
    ROADMAP_SORT_KEY: ClassVar[str] = "roadmap"

    # BE-9455 Symptom A: completion recency, with unfinished work FIRST. Also not a
    # plain column sort -- ``_SORT_COLUMNS`` orders NULLS LAST for every key, and this
    # ordering needs NULLS FIRST, so it lives outside that map and is handled
    # explicitly in ``list_projects`` (see ``_project_keyset``).
    COMPLETION_RECENCY_SORT_KEY: ClassVar[str] = "completion_recency"

    _SORT_COLUMNS: ClassVar[dict] = {
        "series_number": Project.series_number,
        "name": Project.name,
        "created_at": Project.created_at,
        "completed_at": Project.completed_at,
        "status": Project.status,
        "staging_status": Project.staging_status,
    }

    # BE-9354: parent-product liveness is DELIBERATELY not a project-visibility
    # criterion. This module holds no reference to ``Product`` and never filters
    # on one, and that is the rule the rest of the app follows: ``task_repository``
    # lists tasks off a plain ``select(Task)`` with no ``Product`` join, and
    # ``sequence_run_live_filter`` resolves chain members straight from ``Project``
    # without passing through this repository at all. Soft-deleting a product does
    # not cascade, so adding the predicate HERE alone would hide a trashed
    # product's projects while its tasks, chain runs, roadmap items and jobs all
    # stayed visible — one surface disagreeing with four. If a trashed product's
    # children should ever disappear, that is a cascade decision made at the
    # delete writer, not a WHERE clause bolted onto one reader.
    def _build_list_conditions(
        self,
        tenant_key: str,
        status: str | list[str] | None,
        include_cancelled: bool,
        product_id: str | None,
        hidden: bool | None,
        search: str | None,
    ) -> list:
        """Build the shared WHERE conditions for list + count (BE-6076).

        Factored so ``list_projects`` (the page query) and ``count_projects``
        (the filtered total) apply byte-identical predicates — the count can
        NEVER drift from the page it describes. With every optional arg at its
        default (``search=None`` etc.) the produced conditions are identical to
        the pre-BE-6076 ``list_projects`` WHERE clause (backward-compat).
        """
        conditions: list = [Project.tenant_key == tenant_key]

        if product_id:
            conditions.append(Project.product_id == product_id)

        if hidden is True:
            conditions.append(Project.hidden.is_(true()))
        elif hidden is False:
            # NULL-safe exclusion: legacy rows with hidden=NULL are visible.
            conditions.append(Project.hidden.isnot(true()))

        if status:
            status_list = [status] if isinstance(status, str) else list(status)
            if len(status_list) == 1:
                only = status_list[0]
                conditions.append(Project.status == only)
                if only == "deleted":
                    conditions.append(Project.deleted_at.isnot(None))
                else:
                    conditions.append(Project.deleted_at.is_(None))
            else:
                conditions.append(Project.status.in_(status_list))
                conditions.append(Project.deleted_at.is_(None))
        else:
            conditions.append(Project.deleted_at.is_(None))
            if not include_cancelled:
                conditions.append(Project.status != ProjectStatus.CANCELLED)

        if search:
            # BE-6076: server-side search mirrors the prior client-side matcher
            # (IMP-1002 trimmed row): case-insensitive substring across name, the
            # raw id, and the computed taxonomy_alias (e.g. "BE-50"). ``id`` is
            # cast to text so a UUID column still matches a substring query.
            #
            # BE-9469: also description and alias (project_alias), matching
            # list_tasks (title/description/taxonomy_alias) -- U8-F1/F2.
            # BE-9468 QA followup: ``%``/``_`` are SQL LIKE metacharacters, escaped
            # below (backslash first) so they act as literals, not live wildcards.
            # New fields share this SAME escaped needle.
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
        """Resolve a (sort_key, sort_dir) pair to ORDER BY clauses (BE-6076).

        Returns ``[]`` when ``sort_key`` is unknown/None — the caller then either
        leaves the query unordered (default/backward-compat path) or applies a
        deterministic fallback when paginating. Sorts NULLS-last and adds an
        ``id`` tiebreak so a page boundary is stable across requests.
        """
        col = self._SORT_COLUMNS.get(sort_key or "")
        if col is None:
            return []
        descending = (sort_dir or "asc").lower() == "desc"
        ordering = (desc(col) if descending else asc(col)).nulls_last()
        return [ordering, Project.id.asc()]

    def _roadmap_order_clauses(self, tenant_key: str, sort_dir: str | None) -> list:
        """ORDER BY the project's position on the product roadmap (FE-6179).

        Mirrors what /roadmap renders: ``RoadmapService.get_roadmap`` orders its
        items by ``roadmap_items.sort_order`` ASC, so this reuses the SAME column
        as the single source of truth -- no second ordering is invented. Resolved
        with a correlated scalar subquery (not a JOIN) so a project row is never
        multiplied. Projects absent from the roadmap have no item -> NULL ->
        sorted last (an ``id`` tiebreak keeps the page boundary stable). The
        subquery is tenant_key-scoped (ADR-009); ordering is per-product because
        the page query already filters by ``product_id`` and a roadmap is 1:1 with
        a product -- so each project matches at most one item. No per-user
        assumption.
        """
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
        """List projects for a tenant with optional filters.

        ``status`` accepts a single value or a list (SQL ``IN`` pushdown). When a
        list contains ``"deleted"``, the soft-delete clause widens to
        ``deleted_at IS NOT NULL`` for that bucket only when ``status`` is
        exactly ``["deleted"]``; mixed lists keep the default ``IS NULL``
        guard (mirrors the pre-existing single-string semantics).

        ``hidden`` is the per-row UI declutter flag (BE-6078 server-side
        offload). ``None`` (default) applies no hidden filter — both visible and
        hidden rows are returned, preserving the prior behavior for every
        existing caller (the MCP adapter filters hidden in Python). ``False``
        excludes hidden rows at the SQL layer (``hidden IS NOT TRUE`` — NULL-safe
        so legacy NULLs count as visible). ``True`` returns only hidden rows.

        BE-6076 added server-side ``search`` (substring across name/id/alias),
        ``sort_key``/``sort_dir`` (whitelisted columns), and ``limit``/``offset``
        pagination. ALL default to ``None`` so the existing callers (MCP adapter,
        ``/deleted``) get the pre-BE-6076 behavior byte-for-byte: no search
        predicate, no ORDER BY, and the full result set (no slice). ORDER BY is
        only emitted when ``sort_key`` is given OR pagination is requested (a
        deterministic ``created_at DESC`` fallback so paged boundaries are
        stable).

        BE-9469 added ``after_key``: a ``(sort_value, row_id)`` continuation position on
        whichever axis ``sort_key`` chose. ``None`` (the default) emits no extra predicate,
        so every existing caller is byte-identical.

        BE-9455 Symptom A added ``sort_key="completion_recency"``
        (``COMPLETION_RECENCY_SORT_KEY``) for a completion-oriented read: it is the
        only ordering here with NULLS FIRST, so it cannot come from
        ``_SORT_COLUMNS``. Purely additive -- every existing key, and the fallback,
        behave exactly as before.
        """
        conditions = self._build_list_conditions(tenant_key, status, include_cancelled, product_id, hidden, search)
        query = select(Project).options(selectinload(Project.project_type)).where(*conditions)

        if sort_key == self.ROADMAP_SORT_KEY:
            # FE-6179: order by roadmap position (correlated subquery on
            # roadmap_items.sort_order) -- the same ordering /roadmap uses.
            query = query.order_by(*self._roadmap_order_clauses(tenant_key, sort_dir))
        elif sort_key == self.COMPLETION_RECENCY_SORT_KEY:
            # BE-9455 Symptom A: completion recency, unfinished first (NULLS FIRST).
            query = query.order_by(*completion_recency_order_clauses())
        elif order_clauses := self._resolve_order(sort_key, sort_dir):
            query = query.order_by(*order_clauses)
        elif limit is not None or offset is not None:
            # Paginating without an explicit sort: pick a deterministic order so
            # the page boundary is stable. (The unpaginated default path stays
            # unordered — byte-compatible with pre-BE-6076.)
            query = query.order_by(Project.created_at.desc(), Project.id.asc())

        if after_key is not None:
            # BE-9469: the continuation keyset, applied BEFORE the limit so each page
            # fetches the next window FROM the cursor instead of re-fetching the first
            # one. Why that distinction matters, and why a POSITION filter is safe where
            # a SQL LIMIT is not, is recorded in _project_keyset.
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
        """Count projects matching the same filters as ``list_projects`` (BE-6076).

        The filtered TOTAL for v-data-table ``:items-length``. Reuses
        ``_build_list_conditions`` so the count and the paginated page can never
        diverge. Takes no sort/limit/offset — a COUNT over the whole filtered set.
        """
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
        """Board-wide counts for the agent-facing list (BE-9468). ONE grouped round trip.

        Returns raw ``(status, type_abbreviation, min_created, max_created, row_count)``
        tuples plus completion bounds -- deliberately unfolded, so the caller owns the
        response shape and this stays a pure read.

        **It takes NO caller filters, and that is the whole point.** ``list_projects``
        defaults to active-lifecycle rows only, so a counts block scoped to what was
        returned would report the two inactive projects and never mention the thousand
        completed ones. That is derivable from the rows the caller is already holding,
        which makes it an echo rather than a signal. The agent needs to know the archive
        is there BEFORE it decides what to ask for -- so this describes the whole board
        and the response carries ``returned`` separately.

        Scope is **tenant + product**, matching the surface it describes: ``tenant_key``
        because every query filters by it without exception (ADR-009), and ``product_id``
        because ``list_projects`` is active-product-scoped, not tenant-wide.

        Soft-deleted rows are excluded (``deleted_at IS NULL``) -- they are the trash,
        not the board, and the list's own visibility base excludes them before any
        caller filter is applied. Counting them in ``total`` would describe a population
        no query on this surface can return.

        One statement, not three: grouping by ``(status, abbreviation)`` while
        aggregating the date bounds in the same pass, folded by the caller.
        """
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
            .where(Project.tenant_key == tenant_key, Project.deleted_at.is_(None))
            .group_by(Project.status, TaxonomyType.abbreviation)
        )
        if product_id:
            query = query.where(Project.product_id == product_id)
        result = await session.execute(query)
        return list(result.all())

    # ============================================================================
    # Write Operations — ProjectDeletionService
    # ============================================================================

    async def get_not_deleted(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        """Get a non-deleted project by ID."""
        stmt = select(Project).where(
            and_(
                Project.id == project_id,
                Project.tenant_key == tenant_key,
                Project.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_executions_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[AgentExecution]:
        """Get non-completed/non-decommissioned executions for a project."""
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
        """Get all agent jobs for a project."""
        stmt = select(AgentJob).where(and_(AgentJob.project_id == project_id, AgentJob.tenant_key == tenant_key))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_user_approvals_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[UserApproval]:
        """Get all user_approval rows for a project (for deletion).

        ``user_approvals`` carries RESTRICT foreign keys to ``agent_executions``,
        ``agent_jobs`` AND ``projects`` (BE-5029), so these rows MUST be deleted
        before the project's jobs/executions/itself or the cascade is blocked
        with a RestrictViolationError and the project is never purged (BE-6238).
        """
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
        """Get all tasks for a project."""
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
        """Get all messages for a project (for deletion)."""
        stmt = select(Message).where(and_(Message.project_id == project_id, Message.tenant_key == tenant_key))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def delete_entity(self, session: AsyncSession, entity) -> None:
        """Delete an entity from the session."""
        await session.delete(entity)

    async def bulk_delete_user_approvals_for_project(
        self, session: AsyncSession, tenant_key: str, project_id: str
    ) -> int:
        """Bulk-delete a project's user_approvals in ONE statement (BE-9144).

        Replaces the SELECT-then-per-row ORM delete. ``user_approvals`` is a leaf
        table but itself holds RESTRICT FKs to agent_executions/agent_jobs/
        projects, so it MUST be cleared before those (BE-5029/BE-6238). Returns
        the row count deleted (== the former ``len(get_user_approvals_for_project)``).
        """
        result = await session.execute(
            delete(UserApproval)
            .where(and_(UserApproval.project_id == project_id, UserApproval.tenant_key == tenant_key))
            .execution_options(synchronize_session=False)
        )
        return result.rowcount or 0

    async def bulk_delete_agent_jobs_for_project(self, session: AsyncSession, tenant_key: str, project_id: str) -> int:
        """Bulk-delete a project's agent_jobs (and their executions) in TWO
        statements (BE-9144), replacing the per-row ORM delete loop.

        ``agent_executions.job_id`` has NO DB ondelete (the ``AgentJob.executions``
        ``cascade='all, delete-orphan'`` is ORM-level only), so a bulk DELETE of
        agent_jobs alone would trip a FK RESTRICT — executions are deleted first,
        by job_id. ``agent_todo_items`` cascade at the DB level (ondelete=CASCADE).
        user_approvals (RESTRICT to executions/jobs) MUST already be cleared by
        the caller. Returns the agent_jobs count deleted.
        """
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
        """Bulk-delete a project's messages in ONE statement (BE-9144). The three
        child tables (message_recipients/acknowledgments/completions) carry
        DB-level ondelete=CASCADE, so they fall away with the parent. Returns the
        row count deleted.
        """
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
        """Get all soft-deleted projects for a tenant, optionally scoped to a product."""
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
        """Get projects deleted before a cutoff date."""
        stmt = select(Project).where(
            Project.deleted_at.isnot(None),
            Project.status == ProjectStatus.DELETED,
            Project.deleted_at < cutoff_date,
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
