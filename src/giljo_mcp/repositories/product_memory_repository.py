# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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


_FTS_DOCUMENT_SQL = (
    "to_tsvector('english', "
    "coalesce(summary, '') || ' ' || "
    "coalesce(project_name, '') || ' ' || "
    "coalesce(key_outcomes::text, '') || ' ' || "
    "coalesce(decisions_made::text, '') || ' ' || "
    "coalesce(tags::text, '') || ' ' || "
    "coalesce(git_commits::text, ''))"
)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ProductMemoryRepository:

    _GIT_HISTORY_ENTRY_WINDOW = 200

    async def create_entry(
        self,
        session: AsyncSession,
        params: MemoryEntryCreateParams,
    ) -> ProductMemoryEntry:
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
            product_id=str(params.product_id),
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
        base_filter = [
            ProductMemoryEntry.product_id == str(product_id),
            ProductMemoryEntry.tenant_key == tenant_key,
            ProductMemoryEntry.project_id.isnot(None),
        ]
        if not include_deleted:
            base_filter.append(ProductMemoryEntry.deleted_by_user == False)  # noqa: E712

        count_stmt = select(func.count(func.distinct(ProductMemoryEntry.project_id))).where(*base_filter)
        with tenant_session_context(session, tenant_key):
            count_result = await session.execute(count_stmt)
        total_distinct_projects = count_result.scalar() or 0

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

        all_commits.sort(key=lambda c: str(c.get("date") or ""), reverse=True)
        return all_commits[:limit]



    async def get_product_by_id(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> Product | None:
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


    async def count_projects(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> int:
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
        stmt = select(func.count(VisionDocument.id)).where(
            and_(
                VisionDocument.product_id == product_id,
                VisionDocument.tenant_key == tenant_key,
                VisionDocument.deleted_at.is_(None),
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
        stmt = select(func.count(Task.id)).where(
            and_(
                Task.product_id == product_id,
                Task.tenant_key == tenant_key,
                Task.deleted_at.is_(None),
                Task.status.in_(["pending", "in_progress", "on_hold"]),
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.scalar() or 0


    async def count_projects_bulk(
        self,
        session: AsyncSession,
        product_ids: list[str],
        tenant_key: str,
    ) -> dict[str, int]:
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
        if not product_ids:
            return {}
        stmt = (
            select(Task.product_id, func.count(Task.id))
            .where(
                and_(
                    Task.product_id.in_(product_ids),
                    Task.tenant_key == tenant_key,
                    Task.deleted_at.is_(None),
                    Task.status.in_(["pending", "in_progress", "on_hold"]),
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
        if not product_ids:
            return {}
        stmt = (
            select(VisionDocument.product_id, func.count(VisionDocument.id))
            .where(
                and_(
                    VisionDocument.product_id.in_(product_ids),
                    VisionDocument.tenant_key == tenant_key,
                    VisionDocument.deleted_at.is_(None),
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
        if not product_ids:
            return {}
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
                    VisionDocument.deleted_at.is_(None),
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
        base_filters = [
            ProductMemoryEntry.product_id == product_id,
            ProductMemoryEntry.tenant_key == tenant_key,
            ~ProductMemoryEntry.deleted_by_user,
        ]
        if project_id:
            base_filters.append(ProductMemoryEntry.project_id == project_id)
        if tag:
            base_filters.append(ProductMemoryEntry.tags.contains([tag]))

        entries = await self._fetch_memory_page(session, tenant_key, base_filters, limit, search_query)

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
        pattern = f"%{_escape_like(search_query)}%"
        match = or_(
            ProductMemoryEntry.summary.ilike(pattern, escape="\\"),
            ProductMemoryEntry.project_name.ilike(pattern, escape="\\"),
            cast(ProductMemoryEntry.key_outcomes, Text).ilike(pattern, escape="\\"),
            cast(ProductMemoryEntry.decisions_made, Text).ilike(pattern, escape="\\"),
            cast(ProductMemoryEntry.tags, Text).ilike(pattern, escape="\\"),
            cast(ProductMemoryEntry.git_commits, Text).ilike(pattern, escape="\\"),
        )
        return (
            select(ProductMemoryEntry)
            .where(*base_filters, match)
            .order_by(ProductMemoryEntry.sequence.desc())
            .limit(limit)
        )

    @staticmethod
    async def _scalars(session: AsyncSession, tenant_key: str, stmt) -> list[ProductMemoryEntry]:
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return list(result.scalars().all())

    async def refresh_product(
        self,
        session: AsyncSession,
        product: Product,
    ) -> None:
        await session.refresh(
            product,
            attribute_names=["tech_stack", "architecture", "test_config", "vision_documents"],
        )
