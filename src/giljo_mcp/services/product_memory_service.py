# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductMemoryService - Product metrics, statistics, and memory management

Handover 0950n: Extracted from ProductService to keep all files under 1000 lines.

Responsibilities:
- Product statistics (project/task/vision document counts)
- Cascade impact analysis for deletion previews
- Product memory JSONB initialization and backward-compat repair
- Building product_memory response structures from the table + JSONB
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import BaseGiljoError, ResourceNotFoundError
from giljo_mcp.models import Product
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository
from giljo_mcp.schemas.service_responses import CascadeImpact, ProductStatistics
from giljo_mcp.services._session_helpers import tenant_scoped_session
from giljo_mcp.services.dto import MemoryEntryCreateParams

# INF-WriteShape: shared write-side validator lives in its own module (file
# size budget). Re-exported here so existing callers can keep importing from
# ``giljo_mcp.services.product_memory_service``.
from giljo_mcp.services.memory_entry_write_validator import (  # noqa: F401 -- re-exported for back-compat
    MEMORY_DECISION_MAX,
    MEMORY_DECISIONS_COUNT,
    MEMORY_DELIVERABLE_MAX,
    MEMORY_DELIVERABLES_COUNT,
    MEMORY_KEY_OUTCOME_MAX,
    MEMORY_KEY_OUTCOMES_COUNT,
    MEMORY_SUMMARY_MAX,
    MEMORY_TAG_MAX_LEN,
    MEMORY_TAGS_COUNT,
    MemoryEntryWriteSchema,
    MemoryEntryWriteValidationError,
    validate_memory_entry_write,
)


logger = logging.getLogger(__name__)

# BE-6225b: search_memory result-cap. Default keeps the headline payload small;
# the hard max bounds a runaway agent. The @mcp.tool boundary advertises + enforces
# the same MAX (Field le=...), so the advertised cap can never drift from this one.
SEARCH_MEMORY_LIMIT_DEFAULT = 10
SEARCH_MEMORY_LIMIT_MAX = 50


def _keyword_score(query: str, haystack: str) -> float:
    """BE-6225b: deterministic keyword-overlap score in [0.0, 1.0].

    Fraction of the query's distinct whitespace tokens that appear (case-
    insensitive substring) in the entry's searchable haystack. Cheap, dependency-
    free, and explainable — a transparency signal layered on top of the DB's own
    relevance ordering (Postgres ts_rank), NOT a replacement for it.

    SEAM: this is the single swap-point for future semantic/embedding ranking —
    replace this function with a vector-similarity score and the headline contract
    (and every caller) stays identical. Do NOT pull an embedding dependency in here
    now (solo-maintainable; no heavy infra).
    """
    tokens = {t for t in query.lower().split() if t}
    if not tokens:
        return 0.0
    hay = haystack.lower()
    matched = sum(1 for t in tokens if t in hay)
    return round(matched / len(tokens), 3)


class ProductMemoryService:
    """
    Service for product statistics, cascade analysis, and memory management.

    Encapsulates read-heavy analytics and JSONB memory initialization logic
    that was previously co-located with lifecycle state management.

    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        test_session: AsyncSession | None = None,
    ):
        """
        Initialize ProductMemoryService.

        Args:
            db_manager: Database manager for async database operations
            tenant_key: Tenant key for multi-tenant isolation
            test_session: Optional AsyncSession for tests to share the same transaction
        """
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._test_session = test_session
        self._repo = ProductMemoryRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return tenant_scoped_session(self.db_manager, self.tenant_key, self._test_session)

    async def get_product_statistics(self, product_id: str) -> ProductStatistics:
        """
        Get comprehensive statistics for a product.

        Args:
            product_id: Product UUID

        Returns:
            ProductStatistics Pydantic model

        Raises:
            ResourceNotFoundError: If product not found
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                product = await self._repo.get_product_by_id(session, product_id, self.tenant_key)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                metrics = await self._get_product_metrics(session, product_id)

                return ProductStatistics(
                    product_id=product_id,
                    name=product.name,
                    is_active=product.is_active,
                    project_count=metrics["project_count"],
                    unfinished_projects=metrics["unfinished_projects"],
                    task_count=metrics["task_count"],
                    unresolved_tasks=metrics["unresolved_tasks"],
                    vision_documents_count=metrics["vision_documents_count"],
                    has_vision=metrics["has_vision"],
                    created_at=product.created_at,
                    updated_at=product.updated_at,
                )

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get product statistics")
            raise BaseGiljoError(
                message=f"Failed to get product statistics: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def get_product_statistics_bulk(self, product_ids: list[str]) -> dict[str, dict[str, Any]]:
        """
        Batched per-product metrics for many products in a fixed number of queries.

        BE-6066 P1: replaces the O(N) per-product ``get_product_statistics`` loop
        on the products list. Computes all five counts for ALL ``product_ids`` in
        grouped (GROUP BY product FK) queries — the query count is independent of
        N. Does NOT re-SELECT the products (the caller already holds them), which
        also drops the redundant per-product SELECT the old path issued.

        Args:
            product_ids: Product UUIDs (as strings) to compute metrics for.

        Returns:
            Dict keyed by product_id. Each value is the same metrics dict shape as
            ``_get_product_metrics``: project_count, unfinished_projects,
            task_count, unresolved_tasks, vision_documents_count, has_vision.
            Every supplied product_id is present (zero-filled when it has no rows).

        Raises:
            BaseGiljoError: If the database operation fails.
        """
        if not product_ids:
            return {}
        ids = [str(pid) for pid in product_ids]
        try:
            async with self._get_session() as session:
                return await self._get_product_metrics_bulk(session, ids)
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get bulk product statistics")
            raise BaseGiljoError(
                message=f"Failed to get bulk product statistics: {e!s}",
                context={"product_count": len(ids), "tenant_key": self.tenant_key},
            ) from e

    async def get_vision_summary_bulk(self, product_ids: list[str]) -> dict[str, dict[str, int]]:
        """
        BE-6066 P4: batched vision-document aggregates for the products LIST.

        ONE grouped query returning the four card aggregates (doc_count,
        chunked_count, chunk_total, embedded_count) per product_id. Backs the lean
        ``ProductListResponse.vision_summary`` so the list no longer ships the full
        ``vision_documents`` array. See
        :meth:`ProductMemoryRepository.vision_summary_bulk`.

        Args:
            product_ids: Product UUIDs (as strings) to aggregate vision docs for.

        Returns:
            Dict keyed by product_id; each value is
            ``{doc_count, chunked_count, chunk_total, embedded_count}``. Products
            with no vision docs are absent (callers zero-fill).

        Raises:
            BaseGiljoError: If the database operation fails.
        """
        if not product_ids:
            return {}
        ids = [str(pid) for pid in product_ids]
        try:
            async with self._get_session() as session:
                return await self._repo.vision_summary_bulk(session, ids, self.tenant_key)
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get bulk vision summary")
            raise BaseGiljoError(
                message=f"Failed to get bulk vision summary: {e!s}",
                context={"product_count": len(ids), "tenant_key": self.tenant_key},
            ) from e

    async def get_cascade_impact(self, product_id: str) -> CascadeImpact:
        """
        Get cascade impact analysis for product deletion.

        Shows what entities would be affected by deleting this product.

        Args:
            product_id: Product UUID

        Returns:
            CascadeImpact Pydantic model

        Raises:
            ResourceNotFoundError: If product not found
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                product = await self._repo.get_product_by_id(session, product_id, self.tenant_key)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                # Count related entities (defense-in-depth: explicit tenant_key on all child queries)
                total_projects = await self._repo.count_projects(session, product_id, self.tenant_key)
                total_tasks = await self._repo.count_tasks(session, product_id, self.tenant_key)
                total_vision_docs = await self._repo.count_vision_documents(session, product_id, self.tenant_key)

                return CascadeImpact(
                    product_id=product_id,
                    product_name=product.name,
                    total_projects=total_projects,
                    total_tasks=total_tasks,
                    total_vision_documents=total_vision_docs,
                    warning=(
                        "These related items are kept unchanged while the product is in the "
                        "trash. They are permanently deleted only when the product itself is — "
                        "either when you delete it permanently from the trash, or automatically "
                        "after 10 days."
                    ),
                )

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get cascade impact")
            raise BaseGiljoError(
                message=f"Failed to get cascade impact: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def _build_product_memory_response(
        self, session: AsyncSession, product: Product, include_deleted: bool = False
    ) -> dict:
        """
        Build product_memory response with sequential_history from the table (Handover 0390b).

        Maintains backward compatibility by returning the same structure as before,
        but populates sequential_history from product_memory_entries table instead
        of the JSONB column.

        Args:
            session: Async database session
            product: Product instance
            include_deleted: Include soft-deleted memory entries (default: False)

        Returns:
            Dict with keys: git_integration, sequential_history, context
        """
        base_memory = product.product_memory or {}
        # BE-9261: seed key renamed github -> git_integration. Rows written before
        # the rename only carry "github"; this is the single production reader of
        # that config, so the legacy-key tolerance lives here (folded in from the
        # now-deleted _get_git_config helper, which had no callers).
        git_integration = base_memory.get("git_integration") or base_memory.get("github") or {}
        context = base_memory.get("context", {})

        entries = await self._repo.get_entries_by_product(
            session=session,
            product_id=product.id,
            tenant_key=self.tenant_key,
            include_deleted=include_deleted,
        )

        sequential_history = [entry.to_dict() for entry in entries]

        return {
            "git_integration": git_integration,
            "sequential_history": sequential_history,
            "context": context,
        }

    async def _ensure_product_memory_initialized(self, session: AsyncSession, product: Product) -> None:
        """
        Ensure product_memory is initialized with default structure (Handover 0136).

        Provides backward compatibility for products that may have NULL, empty,
        or partial product_memory JSONB. The method is idempotent.

        Args:
            session: Async database session
            product: Product instance to check and initialize

        Side Effects:
            - Updates product.product_memory if incomplete
            - Commits changes to database when modifications are made
        """
        # BE-9261: seed key renamed github -> git_integration. This only ADDS
        # missing keys (never overwrites), so a legacy row's "github" data survives
        # untouched and stays readable via the fallback in
        # _build_product_memory_response above.
        default_structure = {
            "git_integration": {},
            "context": {},
        }

        needs_update = False

        if product.product_memory is None:
            product.product_memory = default_structure
            needs_update = True
            self._logger.debug(f"Product {product.id}: Initialized NULL product_memory")
        elif not isinstance(product.product_memory, dict):
            product.product_memory = default_structure
            needs_update = True
            self._logger.warning(
                f"Product {product.id}: Replaced invalid product_memory type "
                f"({type(product.product_memory)}) with default structure"
            )
        elif not product.product_memory:
            product.product_memory = default_structure
            needs_update = True
            self._logger.debug(f"Product {product.id}: Initialized empty dict product_memory")
        else:
            updated_memory = dict(product.product_memory)
            for key, default_value in default_structure.items():
                if key not in updated_memory:
                    updated_memory[key] = default_value
                    needs_update = True
                    self._logger.debug(f"Product {product.id}: Added missing '{key}' key to product_memory")

            if needs_update:
                product.product_memory = updated_memory

        if needs_update:
            product.updated_at = datetime.now(UTC)
            await session.commit()
            # Include relationships so refresh doesn't discard eager loads (Handover 0840h)
            await self._repo.refresh_product(session, product)
            self._logger.info(f"Product {product.id}: Updated product_memory structure")

    async def _get_product_metrics(self, session: AsyncSession, product_id: str) -> dict[str, Any]:
        """
        Get aggregated metrics for a product (projects, tasks, vision documents).

        All queries filter by tenant_key for defense-in-depth isolation.

        Args:
            session: Async database session
            product_id: Product UUID

        Returns:
            Dict with keys: project_count, unfinished_projects, task_count,
            unresolved_tasks, vision_documents_count, has_vision
        """
        project_count = await self._repo.count_projects(session, product_id, self.tenant_key)
        unfinished_projects = await self._repo.count_unfinished_projects(session, product_id, self.tenant_key)
        task_count = await self._repo.count_tasks(session, product_id, self.tenant_key)
        unresolved_tasks = await self._repo.count_unresolved_tasks(session, product_id, self.tenant_key)
        vision_documents_count = await self._repo.count_vision_documents(session, product_id, self.tenant_key)

        return {
            "project_count": project_count,
            "unfinished_projects": unfinished_projects,
            "task_count": task_count,
            "unresolved_tasks": unresolved_tasks,
            "vision_documents_count": vision_documents_count,
            "has_vision": vision_documents_count > 0,
        }

    async def _get_product_metrics_bulk(
        self, session: AsyncSession, product_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        Batched variant of :meth:`_get_product_metrics` for many products.

        Issues one grouped query per metric (five total) regardless of how many
        products are supplied. Each per-product result is byte-identical to the
        per-product ``_get_product_metrics`` because the underlying repository
        bulk counts reuse the EXACT same tenant_key + status/soft-delete filters.

        Args:
            session: Async database session
            product_ids: Product UUIDs (as strings)

        Returns:
            Dict keyed by product_id; each value matches ``_get_product_metrics``
            output. Every supplied product_id is present (zero-filled when empty).
        """
        project_counts = await self._repo.count_projects_bulk(session, product_ids, self.tenant_key)
        unfinished = await self._repo.count_unfinished_projects_bulk(session, product_ids, self.tenant_key)
        task_counts = await self._repo.count_tasks_bulk(session, product_ids, self.tenant_key)
        unresolved = await self._repo.count_unresolved_tasks_bulk(session, product_ids, self.tenant_key)
        vision_counts = await self._repo.count_vision_documents_bulk(session, product_ids, self.tenant_key)

        metrics: dict[str, dict[str, Any]] = {}
        for product_id in product_ids:
            vision_documents_count = vision_counts.get(product_id, 0)
            metrics[product_id] = {
                "project_count": project_counts.get(product_id, 0),
                "unfinished_projects": unfinished.get(product_id, 0),
                "task_count": task_counts.get(product_id, 0),
                "unresolved_tasks": unresolved.get(product_id, 0),
                "vision_documents_count": vision_documents_count,
                "has_vision": vision_documents_count > 0,
            }
        return metrics

    async def get_memory_entries(
        self,
        product_id: str,
        project_id: str | None = None,
        limit: int = 10,
        search_query: str | None = None,
    ) -> dict[str, Any]:
        """Fetch 360 memory entries for a product from the normalized table.

        BE-5022a: Extracted from api/endpoints/products/memory.py to keep
        all DB access in the service layer.

        Args:
            product_id: Product UUID (already validated by caller)
            project_id: Optional project UUID filter
            limit: Maximum entries to return (1-100)
            search_query: Optional full-text search term (BE-6082). When present,
                the repository filters + relevance-ranks via tsquery (ILIKE
                substring fallback). tenant_key + product scoped.

        Returns:
            Dict with entries list, total_count, and filtered_count

        Raises:
            ResourceNotFoundError: Product not found or not accessible
        """
        async with self._get_session() as session:
            # Verify product exists and belongs to tenant
            product = await self._repo.get_product_by_id(session, product_id, self.tenant_key)

            if not product:
                raise ResourceNotFoundError(
                    message=f"Product {product_id} not found or not accessible",
                    context={"product_id": product_id},
                )

            # Fetch entries with total count via repository
            entries, total_count = await self._repo.get_memory_entries_paginated(
                session=session,
                product_id=product_id,
                tenant_key=self.tenant_key,
                project_id=project_id,
                limit=limit,
                search_query=search_query,
            )

            return {
                "entries": entries,
                "total_count": total_count,
                "filtered_count": len(entries),
            }

    async def search_memory(
        self,
        product_id: str,
        query: str,
        tag: str | None = None,
        limit: int = SEARCH_MEMORY_LIMIT_DEFAULT,
    ) -> dict[str, Any]:
        """BE-6225b: keyword (+ optional tag) search over 360 memory headlines.

        Answers "have we solved X before?" against accumulated project history.
        REUSES the existing BE-6082 search read path
        (``ProductMemoryRepository.get_memory_entries_paginated`` — FTS over
        summary/project_name/key_outcomes/decisions_made/tags/git_commits with
        an ILIKE substring fallback); no parallel store, no new table. BE-9469
        added git_commits -- a closeout's commit messages are searchable too
        (e.g. "when did we fix the redirect bug").

        Tenant + product scoped (the caller resolves the active product, same
        contract as list_projects). An empty query and a no-match query both
        return a clean empty result — never an error.

        Args:
            product_id: Product UUID (already resolved/validated by the caller).
            query: Case-insensitive keyword/substring search term.
            tag: Optional exact-tag filter (controlled vocabulary).
            limit: Max headlines to return (clamped to SEARCH_MEMORY_LIMIT_MAX).

        Returns:
            ``{"results": [{sequence, project_id, project_alias, project_name,
            summary, tags, type, score}], "count": int, "query": str,
            "tag": str | None}`` — relevance-ordered (DB ts_rank), each carrying a
            transparency ``score`` (see ``_keyword_score``).

        Raises:
            ResourceNotFoundError: Product not found or not accessible.
        """
        from giljo_mcp.tools.context_tools.get_360_memory import _apply_legacy_tag_mapping

        limit = max(1, min(limit, SEARCH_MEMORY_LIMIT_MAX))
        clean_query = (query or "").strip()

        # Empty query -> clean empty result (never an error). A blank search has
        # no keyword to rank by; an agent should pass a real term.
        if not clean_query:
            return {"results": [], "count": 0, "query": "", "tag": tag or None}

        async with self._get_session() as session:
            product = await self._repo.get_product_by_id(session, product_id, self.tenant_key)
            if not product:
                raise ResourceNotFoundError(
                    message=f"Product {product_id} not found or not accessible",
                    context={"product_id": product_id},
                )

            entries, _total = await self._repo.get_memory_entries_paginated(
                session=session,
                product_id=product_id,
                tenant_key=self.tenant_key,
                limit=limit,
                search_query=clean_query,
                tag=tag or None,
            )

            alias_map = await self._repo.get_project_aliases(
                session=session,
                project_ids=[e.project_id for e in entries],
                tenant_key=self.tenant_key,
            )

        results: list[dict[str, Any]] = []
        for entry in entries:
            haystack = " ".join(
                [
                    entry.summary or "",
                    entry.project_name or "",
                    " ".join(entry.key_outcomes or []),
                    " ".join(entry.decisions_made or []),
                    " ".join(str(t) for t in (entry.tags or [])),
                ]
            )
            results.append(
                {
                    "sequence": entry.sequence,
                    "project_id": str(entry.project_id) if entry.project_id else None,
                    "project_alias": alias_map.get(str(entry.project_id)) if entry.project_id else None,
                    "project_name": entry.project_name,
                    "summary": entry.summary or "",
                    "tags": _apply_legacy_tag_mapping(entry.tags or []),
                    "type": entry.entry_type,
                    "score": _keyword_score(clean_query, haystack),
                }
            )

        return {"results": results, "count": len(results), "query": clean_query, "tag": tag or None}

    # ---- BE-5022b: Service wrappers for ProductMemoryRepository methods ----

    async def get_entries_by_last_n_projects(
        self,
        product_id: str,
        last_n_projects: int = 3,
        offset: int = 0,
        include_deleted: bool = False,
        session: AsyncSession | None = None,
    ) -> tuple[list, int]:
        """Fetch memory entries grouped by last N distinct projects.

        BE-5022b: Service wrapper for ProductMemoryRepository.get_entries_by_last_n_projects().

        Args:
            product_id: Product UUID
            last_n_projects: Number of distinct projects to consider
            offset: Number of projects to skip (pagination)
            include_deleted: Include soft-deleted entries
            session: Optional existing session (for callers that manage their own)

        Returns:
            Tuple of (entries list, total_projects count)
        """
        if session is not None:
            return await self._repo.get_entries_by_last_n_projects(
                session=session,
                product_id=product_id,
                tenant_key=self.tenant_key,
                last_n_projects=last_n_projects,
                offset=offset,
                include_deleted=include_deleted,
            )
        async with self._get_session() as new_session:
            return await self._repo.get_entries_by_last_n_projects(
                session=new_session,
                product_id=product_id,
                tenant_key=self.tenant_key,
                last_n_projects=last_n_projects,
                offset=offset,
                include_deleted=include_deleted,
            )

    # get_entries_by_tag_prefix removed in INF-5025b

    async def get_git_history(
        self,
        product_id: str,
        limit: int = 25,
        session: AsyncSession | None = None,
    ) -> list:
        """Fetch git commit history from memory entries.

        BE-5022b: Service wrapper for ProductMemoryRepository.get_git_history().

        Args:
            product_id: Product UUID
            limit: Max commits to return
            session: Optional existing session

        Returns:
            List of git commit dicts (newest first)
        """
        if session is not None:
            return await self._repo.get_git_history(
                session=session,
                product_id=product_id,
                tenant_key=self.tenant_key,
                limit=limit,
            )
        async with self._get_session() as new_session:
            return await self._repo.get_git_history(
                session=new_session,
                product_id=product_id,
                tenant_key=self.tenant_key,
                limit=limit,
            )

    async def get_next_sequence(
        self,
        product_id: str | Any,
        session: AsyncSession | None = None,
    ) -> int:
        """Get the next sequence number for a product's memory entries.

        BE-5022b: Service wrapper for ProductMemoryRepository.get_next_sequence().

        Args:
            product_id: Product UUID (str or UUID)
            session: Optional existing session

        Returns:
            Next available sequence number
        """
        if session is not None:
            return await self._repo.get_next_sequence(
                session=session,
                product_id=product_id,
                tenant_key=self.tenant_key,
            )
        async with self._get_session() as new_session:
            return await self._repo.get_next_sequence(
                session=new_session,
                product_id=product_id,
                tenant_key=self.tenant_key,
            )

    async def create_entry(
        self,
        params: MemoryEntryCreateParams,
        session: AsyncSession | None = None,
    ) -> ProductMemoryEntry:
        """Create a new product memory entry.

        BE-5022b: Service wrapper for ProductMemoryRepository.create_entry().

        TSK-9022: cross-checks that ``params.product_id`` is actually owned by
        ``params.tenant_key`` before writing — the DTO's ``tenant_key`` is
        caller-supplied and must not be trusted for the write on its own.

        Args:
            params: MemoryEntryCreateParams with all required fields
            session: Optional existing session

        Returns:
            Created ProductMemoryEntry instance

        Raises:
            ResourceNotFoundError: If product_id is not owned by tenant_key
        """
        if session is not None:
            return await self._create_entry_verified(session, params)
        async with self._get_session() as new_session:
            return await self._create_entry_verified(new_session, params)

    async def _create_entry_verified(
        self, session: AsyncSession, params: MemoryEntryCreateParams
    ) -> ProductMemoryEntry:
        product = await self._repo.get_product_by_id(session, str(params.product_id), params.tenant_key)
        if not product:
            raise ResourceNotFoundError(
                message="Product not found",
                context={"product_id": str(params.product_id), "tenant_key": params.tenant_key},
            )
        return await self._repo.create_entry(session=session, params=params)

    # _create_action_required_tasks removed in INF-5025b
