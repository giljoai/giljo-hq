# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductMemoryEntry Repository (Handover 0390a)

CRUD operations for 360 memory entries with tenant isolation.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Text, and_, case, cast, func, literal_column, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project, Task, VisionDocument
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.services.dto import MemoryEntryCreateParams


logger = logging.getLogger(__name__)


# BE-6082: tsvector document expression for 360-memory full-text search. MUST
# stay byte-identical to ``_FTS_DOCUMENT`` in
# ``migrations/versions/ce_0052_pme_fts_be6082.py`` so this query's expression
# matches the ``idx_pme_fts`` GIN index and the planner uses it. Fields mirror
# the client-side ``_matchesSearch`` haystack in ``memoryStore.js`` for parity.
# JSONB columns (key_outcomes/decisions_made/tags) are cast with ``::text``
# (jsonb_out is IMMUTABLE), not array_to_string — they are JSONB, not text[].
_FTS_DOCUMENT_SQL = (
    "to_tsvector('english', "
    "coalesce(summary, '') || ' ' || "
    "coalesce(project_name, '') || ' ' || "
    "coalesce(key_outcomes::text, '') || ' ' || "
    "coalesce(decisions_made::text, '') || ' ' || "
    "coalesce(tags::text, ''))"
)


def _escape_like(value: str) -> str:
    """Escape LIKE/ILIKE wildcards so the ILIKE fallback does literal substring
    matching (parity with the client-side ``.includes()`` haystack)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ProductMemoryRepository:
    """Repository for ProductMemoryEntry CRUD operations."""

    # BE-6071: recent-entries window for get_git_history. Bounds the all-entries scan
    # that flattened JSONB git_commits across every entry. Far larger than the typical
    # commit `limit` (50) so the most recent commits are virtually always covered.
    _GIT_HISTORY_ENTRY_WINDOW = 200

    async def create_entry(
        self,
        session: AsyncSession,
        params: MemoryEntryCreateParams,
    ) -> ProductMemoryEntry:
        """
        Create a new 360 memory entry.

        Args:
            session: Database session
            params: DTO containing all entry fields (tenant_key, product_id, sequence, etc.)

        Returns:
            Created ProductMemoryEntry instance

        Raises:
            IntegrityError: If sequence is duplicate for product
        """
        # Validate JSONB list columns at the write boundary
        from giljo_mcp.schemas.jsonb_validators import (
            validate_git_commits,
            validate_string_list,
        )

        validated_key_outcomes = validate_string_list(params.key_outcomes, "key_outcomes") or []
        validated_decisions = validate_string_list(params.decisions_made, "decisions_made") or []
        validated_deliverables = validate_string_list(params.deliverables, "deliverables") or []
        validated_tags = validate_string_list(params.tags, "tags", max_items=100, max_length=200) or []
        validated_git_commits = validate_git_commits(params.git_commits) or []

        entry = ProductMemoryEntry(
            tenant_key=params.tenant_key,
            product_id=str(params.product_id),  # Convert UUID to string (column is String(36))
            project_id=str(params.project_id) if params.project_id else None,
            sequence=params.sequence,
            entry_type=params.entry_type,
            source=params.source,
            timestamp=params.timestamp,
            project_name=params.project_name,
            summary=params.summary,
            key_outcomes=validated_key_outcomes,
            decisions_made=validated_decisions,
            git_commits=validated_git_commits,
            deliverables=validated_deliverables,
            metrics=params.metrics or {},
            priority=params.priority,
            significance_score=params.significance_score,
            token_estimate=params.token_estimate,
            tags=validated_tags,
            author_job_id=str(params.author_job_id) if params.author_job_id else None,
            author_name=params.author_name,
            author_type=params.author_type,
        )
        session.add(entry)
        await session.flush()
        await session.refresh(entry)

        logger.info(
            f"Created memory entry {entry.id} for product {params.product_id} (seq={params.sequence})",
            extra={"tenant_key": params.tenant_key, "entry_type": params.entry_type},
        )
        return entry

    async def get_entries_by_product(
        self,
        session: AsyncSession,
        product_id: UUID,
        tenant_key: str,
        limit: int | None = None,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[ProductMemoryEntry]:
        """
        Get 360 memory entries for a product with pagination.

        Args:
            session: Database session
            product_id: Product ID to query
            tenant_key: Tenant isolation key
            limit: Maximum entries to return (None = all)
            offset: Number of entries to skip
            include_deleted: Include soft-deleted entries

        Returns:
            List of ProductMemoryEntry in descending sequence order
        """
        stmt = (
            select(ProductMemoryEntry)
            .where(
                ProductMemoryEntry.product_id == str(product_id),
                ProductMemoryEntry.tenant_key == tenant_key,
            )
            .order_by(ProductMemoryEntry.sequence.desc())
            .offset(offset)
        )

        if not include_deleted:
            stmt = stmt.where(ProductMemoryEntry.deleted_by_user == False)  # noqa: E712

        if limit:
            stmt = stmt.limit(limit)

        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_entries_by_last_n_projects(
        self,
        session: AsyncSession,
        product_id: UUID,
        tenant_key: str,
        last_n_projects: int,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> tuple[list[ProductMemoryEntry], int]:
        """
        Get 360 memory entries for the last N distinct projects.

        Unlike get_entries_by_product which limits by entry count, this limits
        by distinct project_id count. A project with 3 entries returns all 3
        within a single project slot.

        Args:
            session: Database session
            product_id: Product ID to query
            tenant_key: Tenant isolation key
            last_n_projects: Number of distinct projects to include
            offset: Number of distinct projects to skip
            include_deleted: Include soft-deleted entries

        Returns:
            Tuple of (entries list in descending sequence order, total distinct project count)
        """
        # Base filter shared by both queries
        base_filter = [
            ProductMemoryEntry.product_id == str(product_id),
            ProductMemoryEntry.tenant_key == tenant_key,
            ProductMemoryEntry.project_id.isnot(None),
        ]
        if not include_deleted:
            base_filter.append(ProductMemoryEntry.deleted_by_user == False)  # noqa: E712

        # Count total distinct projects
        count_stmt = select(func.count(func.distinct(ProductMemoryEntry.project_id))).where(*base_filter)
        with tenant_session_context(session, tenant_key):
            count_result = await session.execute(count_stmt)
        total_distinct_projects = count_result.scalar() or 0

        # Get the N most recent distinct project_ids (by max sequence)
        project_ids_stmt = (
            select(ProductMemoryEntry.project_id)
            .where(*base_filter)
            .group_by(ProductMemoryEntry.project_id)
            .order_by(func.max(ProductMemoryEntry.sequence).desc())
            .offset(offset)
            .limit(last_n_projects)
        )
        with tenant_session_context(session, tenant_key):
            project_ids_result = await session.execute(project_ids_stmt)
        project_ids = [row[0] for row in project_ids_result.all()]

        if not project_ids:
            return [], total_distinct_projects

        # Fetch all entries for those projects
        entries_stmt = (
            select(ProductMemoryEntry)
            .where(
                ProductMemoryEntry.product_id == str(product_id),
                ProductMemoryEntry.tenant_key == tenant_key,
                ProductMemoryEntry.project_id.in_(project_ids),
            )
            .order_by(ProductMemoryEntry.sequence.desc())
        )
        if not include_deleted:
            entries_stmt = entries_stmt.where(
                ProductMemoryEntry.deleted_by_user == False  # noqa: E712
            )

        with tenant_session_context(session, tenant_key):
            result = await session.execute(entries_stmt)
        return list(result.scalars().all()), total_distinct_projects

    async def get_next_sequence(
        self,
        session: AsyncSession,
        product_id: UUID,
        tenant_key: str,
    ) -> int:
        """
        Get the next available sequence number for a product.

        Uses SELECT MAX(sequence) + 1, returns 1 if no entries exist.

        Args:
            session: Database session
            product_id: Product ID
            tenant_key: Tenant isolation key (required, no default)

        Returns:
            Next sequence number (1-based)
        """
        filters = [
            ProductMemoryEntry.product_id == str(product_id),
            ProductMemoryEntry.tenant_key == tenant_key,
        ]
        stmt = select(func.max(ProductMemoryEntry.sequence)).where(*filters)
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        max_seq = result.scalar_one_or_none()
        return (max_seq or 0) + 1

    async def mark_entries_deleted(
        self,
        session: AsyncSession,
        project_id: UUID,
        tenant_key: str,
    ) -> int:
        """
        Soft-delete all entries associated with a project.

        Called when a project is deleted - marks entries as deleted
        but preserves them for historical reference.

        Args:
            session: Database session
            project_id: Project ID to mark entries for
            tenant_key: Tenant isolation key

        Returns:
            Number of entries marked as deleted
        """
        stmt = (
            update(ProductMemoryEntry)
            .where(
                ProductMemoryEntry.project_id == str(project_id),
                ProductMemoryEntry.tenant_key == tenant_key,
            )
            .values(
                deleted_by_user=True,
                user_deleted_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        await session.flush()

        count = result.rowcount
        if count > 0:
            logger.info(
                f"Marked {count} memory entries as deleted for project {project_id}",
                extra={"tenant_key": tenant_key},
            )
        return count

    async def get_entries_for_context(
        self,
        session: AsyncSession,
        product_id: UUID,
        tenant_key: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Get entries formatted for context (mission planning).

        Returns lightweight dicts suitable for agent context injection.

        Args:
            session: Database session
            product_id: Product ID
            tenant_key: Tenant isolation key
            limit: Max entries to return

        Returns:
            List of entry dicts
        """
        entries = await self.get_entries_by_product(
            session=session,
            product_id=product_id,
            tenant_key=tenant_key,
            limit=limit,
            include_deleted=False,
        )
        return [entry.to_dict() for entry in entries]

    async def get_git_history(
        self,
        session: AsyncSession,
        product_id: UUID,
        tenant_key: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get aggregated git commits from all entries.

        Args:
            session: Database session
            product_id: Product ID
            tenant_key: Tenant isolation key
            limit: Max commits to return

        Returns:
            List of git commit dicts
        """
        # BE-6071: bound the entries window instead of loading EVERY entry then Python-sorting.
        # git_commits is a JSONB array per entry, so commits cannot be SQL-LIMITed directly.
        # get_entries_by_product orders by sequence desc, so the most recent _ENTRY_WINDOW
        # entries carry the most recent commits; flatten+sort+slice on that bounded window.
        # _ENTRY_WINDOW (200) >> the typical `limit` (50) so the top commits are virtually
        # always covered even when entries hold several commits each.
        entries = await self.get_entries_by_product(
            session=session,
            product_id=product_id,
            tenant_key=tenant_key,
            limit=self._GIT_HISTORY_ENTRY_WINDOW,
            include_deleted=False,
        )

        all_commits = []
        for entry in entries:
            if entry.git_commits:
                all_commits.extend(entry.git_commits)

        # Sort by date descending, limit
        # ``or ""`` and str(): a commit dict can carry date=None (the key exists,
        # so a .get default never applies) or a non-string, and one such row
        # breaks the whole sort (Sentry GILJOAI-BACKEND-N: None < None raised).
        all_commits.sort(key=lambda c: str(c.get("date") or ""), reverse=True)
        return all_commits[:limit]

    # get_entries_by_tag_prefix and resolve_action_tags removed in INF-5025b

    # ========================================================================
    # Product lookups (BE-5022d: moved from product_memory_service.py)
    # ========================================================================

    async def get_product_by_id(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> Product | None:
        """
        Get a product by ID with tenant isolation (non-deleted only).

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Product ORM instance or None
        """
        stmt = select(Product).where(
            and_(
                Product.id == product_id,
                Product.tenant_key == tenant_key,
                Product.deleted_at.is_(None),
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ========================================================================
    # Cascade impact counts (BE-5022d: moved from product_memory_service.py)
    # ========================================================================

    async def count_projects(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> int:
        """
        Count non-deleted projects for a product.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Count of non-deleted projects
        """
        stmt = select(func.count(Project.id)).where(
            and_(
                Project.product_id == product_id,
                Project.tenant_key == tenant_key,
                or_(Project.status != ProjectStatus.DELETED, Project.status.is_(None)),
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.scalar() or 0

    async def count_tasks(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> int:
        """
        Count tasks for a product.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Count of tasks
        """
        stmt = select(func.count(Task.id)).where(
            and_(Task.product_id == product_id, Task.tenant_key == tenant_key, Task.deleted_at.is_(None))
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.scalar() or 0

    async def count_vision_documents(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> int:
        """
        Count vision documents for a product.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Count of vision documents
        """
        stmt = select(func.count(VisionDocument.id)).where(
            and_(
                VisionDocument.product_id == product_id,
                VisionDocument.tenant_key == tenant_key,
                VisionDocument.deleted_at.is_(None),  # BE-6130b: exclude trashed docs
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.scalar() or 0

    async def count_unfinished_projects(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> int:
        """
        Count active or inactive projects for a product.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Count of unfinished projects
        """
        stmt = select(func.count(Project.id)).where(
            and_(
                Project.product_id == product_id,
                Project.tenant_key == tenant_key,
                Project.status.in_(["active", "inactive"]),
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.scalar() or 0

    async def count_unresolved_tasks(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> int:
        """
        Count pending or in-progress tasks for a product.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Count of unresolved tasks
        """
        stmt = select(func.count(Task.id)).where(
            and_(
                Task.product_id == product_id,
                Task.tenant_key == tenant_key,
                Task.deleted_at.is_(None),
                Task.status.in_(["pending", "in_progress"]),
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.scalar() or 0

    # ========================================================================
    # BE-6066 P1: batched (GROUP BY) variants of the per-product count_* methods.
    # Each returns ``{product_id: count}`` for the supplied product_ids in a
    # SINGLE grouped query — a fixed query count regardless of how many products
    # are passed (O(1) in N, not O(N)). Filters mirror the singular ``count_*``
    # methods EXACTLY so the status / soft-delete semantics are byte-identical.
    # Products with zero matching rows are simply absent from the dict; callers
    # default missing keys to 0.
    # ========================================================================

    async def count_projects_bulk(
        self,
        session: AsyncSession,
        product_ids: list[str],
        tenant_key: str,
    ) -> dict[str, int]:
        """
        Batched non-deleted project counts keyed by product_id.

        Mirrors :meth:`count_projects` (status != DELETED OR status IS NULL),
        grouped by product FK across all ``product_ids``.
        """
        if not product_ids:
            return {}
        stmt = (
            select(Project.product_id, func.count(Project.id))
            .where(
                and_(
                    Project.product_id.in_(product_ids),
                    Project.tenant_key == tenant_key,
                    or_(Project.status != ProjectStatus.DELETED, Project.status.is_(None)),
                )
            )
            .group_by(Project.product_id)
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {str(pid): count for pid, count in result.all()}

    async def count_unfinished_projects_bulk(
        self,
        session: AsyncSession,
        product_ids: list[str],
        tenant_key: str,
    ) -> dict[str, int]:
        """
        Batched active/inactive project counts keyed by product_id.

        Mirrors :meth:`count_unfinished_projects` (status IN active, inactive).
        """
        if not product_ids:
            return {}
        stmt = (
            select(Project.product_id, func.count(Project.id))
            .where(
                and_(
                    Project.product_id.in_(product_ids),
                    Project.tenant_key == tenant_key,
                    Project.status.in_(["active", "inactive"]),
                )
            )
            .group_by(Project.product_id)
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {str(pid): count for pid, count in result.all()}

    async def count_tasks_bulk(
        self,
        session: AsyncSession,
        product_ids: list[str],
        tenant_key: str,
    ) -> dict[str, int]:
        """
        Batched task counts keyed by product_id.

        Mirrors :meth:`count_tasks` (all tasks for the product + tenant_key).
        """
        if not product_ids:
            return {}
        stmt = (
            select(Task.product_id, func.count(Task.id))
            .where(and_(Task.product_id.in_(product_ids), Task.tenant_key == tenant_key, Task.deleted_at.is_(None)))
            .group_by(Task.product_id)
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {str(pid): count for pid, count in result.all()}

    async def count_unresolved_tasks_bulk(
        self,
        session: AsyncSession,
        product_ids: list[str],
        tenant_key: str,
    ) -> dict[str, int]:
        """
        Batched pending/in_progress task counts keyed by product_id.

        Mirrors :meth:`count_unresolved_tasks` (status IN pending, in_progress).
        """
        if not product_ids:
            return {}
        stmt = (
            select(Task.product_id, func.count(Task.id))
            .where(
                and_(
                    Task.product_id.in_(product_ids),
                    Task.tenant_key == tenant_key,
                    Task.deleted_at.is_(None),
                    Task.status.in_(["pending", "in_progress"]),
                )
            )
            .group_by(Task.product_id)
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {str(pid): count for pid, count in result.all()}

    async def count_vision_documents_bulk(
        self,
        session: AsyncSession,
        product_ids: list[str],
        tenant_key: str,
    ) -> dict[str, int]:
        """
        Batched vision-document counts keyed by product_id.

        Mirrors :meth:`count_vision_documents` (all vision docs for the product
        + tenant_key).
        """
        if not product_ids:
            return {}
        stmt = (
            select(VisionDocument.product_id, func.count(VisionDocument.id))
            .where(
                and_(
                    VisionDocument.product_id.in_(product_ids),
                    VisionDocument.tenant_key == tenant_key,
                    VisionDocument.deleted_at.is_(None),  # BE-6130b: exclude trashed docs
                )
            )
            .group_by(VisionDocument.product_id)
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {str(pid): count for pid, count in result.all()}

    async def vision_summary_bulk(
        self,
        session: AsyncSession,
        product_ids: list[str],
        tenant_key: str,
    ) -> dict[str, dict[str, int]]:
        """BE-6066 P4: batched vision aggregates per product_id in ONE grouped query.

        The four values ``ProductCard.vue`` derived from ``vision_documents``:
        ``doc_count`` (== :meth:`count_vision_documents_bulk`), ``chunked_count``,
        ``chunk_total`` (sum ``chunk_count``), ``embedded_count`` (both summaries
        non-empty — the card's truthy ``getAnalyzedDocCount``). Products with no
        rows are absent (callers zero-fill).
        """
        if not product_ids:
            return {}
        # Mirror the card's truthy `summary_light && summary_medium` (excl. empty).
        analyzed = and_(
            func.coalesce(VisionDocument.summary_light, "") != "",
            func.coalesce(VisionDocument.summary_medium, "") != "",
        )
        stmt = (
            select(
                VisionDocument.product_id,
                func.count(VisionDocument.id),
                func.coalesce(func.sum(case((VisionDocument.chunked.is_(True), 1), else_=0)), 0),
                func.coalesce(func.sum(VisionDocument.chunk_count), 0),
                func.coalesce(func.sum(case((analyzed, 1), else_=0)), 0),
            )
            .where(
                and_(
                    VisionDocument.product_id.in_(product_ids),
                    VisionDocument.tenant_key == tenant_key,
                    VisionDocument.deleted_at.is_(None),  # BE-6130b: exclude trashed docs
                )
            )
            .group_by(VisionDocument.product_id)
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        keys = ("doc_count", "chunked_count", "chunk_total", "embedded_count")
        return {str(row[0]): {k: int(v) for k, v in zip(keys, row[1:], strict=True)} for row in result.all()}

    async def get_memory_entries_paginated(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
        project_id: str | None = None,
        limit: int = 10,
        search_query: str | None = None,
        tag: str | None = None,
    ) -> tuple[list[ProductMemoryEntry], int]:
        """
        Get memory entries with total count for a product.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation
            project_id: Optional project filter
            limit: Maximum entries to return
            search_query: Optional full-text search term (BE-6082). When present,
                entries are filtered + relevance-ranked via tsquery over summary,
                project_name, key_outcomes, decisions_made and tags (the same
                fields as the client-side browser haystack). If the tsquery
                matches nothing usable (e.g. partial-word or stop-word terms),
                falls back to an ILIKE substring scan over those same fields.
            tag: Optional exact-tag filter (BE-6225b). When present, restricts the
                result set to entries whose JSONB ``tags`` array contains this tag
                (``tags @> '[tag]'``). ANDs with ``search_query`` when both are set.

        Returns:
            Tuple of (entries list, total count). ``total_count`` is the
            product's overall entry count (unchanged by search/filter) so the
            response shape is stable across search and browse.
        """
        base_filters = [
            ProductMemoryEntry.product_id == product_id,
            ProductMemoryEntry.tenant_key == tenant_key,
            ~ProductMemoryEntry.deleted_by_user,
        ]
        if project_id:
            base_filters.append(ProductMemoryEntry.project_id == project_id)
        if tag:
            # JSONB containment: ``tags @> '["<tag>"]'`` — uses the GIN-eligible
            # containment operator, ANDs cleanly with the FTS/ILIKE search below.
            base_filters.append(ProductMemoryEntry.tags.contains([tag]))

        entries = await self._fetch_memory_page(session, tenant_key, base_filters, limit, search_query)

        # Total count: overall entries for product+tenant (search-independent).
        total_count_stmt = select(func.count(ProductMemoryEntry.id)).where(
            ProductMemoryEntry.product_id == product_id,
            ProductMemoryEntry.tenant_key == tenant_key,
        )
        with tenant_session_context(session, tenant_key):
            total_count_result = await session.execute(total_count_stmt)
        total_count = total_count_result.scalar_one()

        return entries, total_count

    async def get_project_aliases(
        self,
        session: AsyncSession,
        project_ids: list[str],
        tenant_key: str,
    ) -> dict[str, str]:
        """BE-6225b: batched ``{project_id: taxonomy_alias}`` for memory headlines.

        ONE tenant-scoped query resolves the human-facing alias (e.g. ``BE-6225b``)
        for each source project of a set of memory entries, so search_memory can
        return ``project_alias`` without an N+1 per-entry lookup. Projects with no
        alias (or since-deleted) are simply absent from the dict; callers fall back
        to the entry's stored ``project_name``.
        """
        ids = [pid for pid in project_ids if pid]
        if not ids:
            return {}
        stmt = select(Project.id, Project.taxonomy_alias).where(
            Project.id.in_(ids),
            Project.tenant_key == tenant_key,
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {str(pid): alias for pid, alias in result.all() if alias}

    async def _fetch_memory_page(
        self,
        session: AsyncSession,
        tenant_key: str,
        base_filters: list,
        limit: int,
        search_query: str | None,
    ) -> list[ProductMemoryEntry]:
        """Fetch one page of entries: relevance-ranked FTS when searching (with
        an ILIKE substring fallback if the tsquery matches nothing), else the
        existing newest-sequence-first ordering."""
        if not search_query:
            stmt = (
                select(ProductMemoryEntry)
                .where(*base_filters)
                .order_by(ProductMemoryEntry.sequence.desc())
                .limit(limit)
            )
            return await self._scalars(session, tenant_key, stmt)

        fts_entries = await self._scalars(session, tenant_key, self._fts_stmt(base_filters, limit, search_query))
        if fts_entries:
            return fts_entries
        return await self._scalars(session, tenant_key, self._ilike_stmt(base_filters, limit, search_query))

    @staticmethod
    def _fts_stmt(base_filters: list, limit: int, search_query: str):
        """tsquery SELECT over the ``idx_pme_fts`` document expression, ordered
        by relevance (ts_rank) then sequence. The document literal is byte-
        identical to the migration's index expression so the planner uses it."""
        fts_doc = literal_column(_FTS_DOCUMENT_SQL)
        tsquery = func.plainto_tsquery(literal_column("'english'"), search_query)
        return (
            select(ProductMemoryEntry)
            .where(*base_filters, fts_doc.op("@@")(tsquery))
            .order_by(func.ts_rank(fts_doc, tsquery).desc(), ProductMemoryEntry.sequence.desc())
            .limit(limit)
        )

    @staticmethod
    def _ilike_stmt(base_filters: list, limit: int, search_query: str):
        """ILIKE substring fallback over the same fields as the FTS document
        (JSONB columns cast to text), preserving the sequence ordering."""
        pattern = f"%{_escape_like(search_query)}%"
        match = or_(
            ProductMemoryEntry.summary.ilike(pattern, escape="\\"),
            ProductMemoryEntry.project_name.ilike(pattern, escape="\\"),
            cast(ProductMemoryEntry.key_outcomes, Text).ilike(pattern, escape="\\"),
            cast(ProductMemoryEntry.decisions_made, Text).ilike(pattern, escape="\\"),
            cast(ProductMemoryEntry.tags, Text).ilike(pattern, escape="\\"),
        )
        return (
            select(ProductMemoryEntry)
            .where(*base_filters, match)
            .order_by(ProductMemoryEntry.sequence.desc())
            .limit(limit)
        )

    @staticmethod
    async def _scalars(session: AsyncSession, tenant_key: str, stmt) -> list[ProductMemoryEntry]:
        """Execute a SELECT inside the tenant session context and return scalars."""
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return list(result.scalars().all())

    async def refresh_product(
        self,
        session: AsyncSession,
        product: Product,
    ) -> None:
        """
        Refresh a product with its relationships after commit.

        Args:
            session: Active database session
            product: Product ORM instance
        """
        await session.refresh(
            product,
            attribute_names=["tech_stack", "architecture", "test_config", "vision_documents"],
        )
