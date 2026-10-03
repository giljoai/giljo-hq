# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import BaseGiljoError, ResourceNotFoundError
from giljo_mcp.models import Product
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository
from giljo_mcp.schemas.service_responses import CascadeImpact, ProductStatistics
from giljo_mcp.services._session_helpers import tenant_scoped_session
from giljo_mcp.services.dto import MemoryEntryCreateParams

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

SEARCH_MEMORY_LIMIT_DEFAULT = 10
SEARCH_MEMORY_LIMIT_MAX = 50


def _keyword_score(query: str, haystack: str) -> float:
    tokens = {t for t in query.lower().split() if t}
    if not tokens:
        return 0.0
    hay = haystack.lower()
    matched = sum(1 for t in tokens if t in hay)
    return round(matched / len(tokens), 3)


class ProductMemoryService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        test_session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._test_session = test_session
        self._repo = ProductMemoryRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self):
        return tenant_scoped_session(self.db_manager, self.tenant_key, self._test_session)

    async def get_product_statistics(self, product_id: str) -> ProductStatistics:
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
        except Exception as e:
            self._logger.exception("Failed to get product statistics")
            raise BaseGiljoError(
                message=f"Failed to get product statistics: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def get_product_statistics_bulk(self, product_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not product_ids:
            return {}
        ids = [str(pid) for pid in product_ids]
        try:
            async with self._get_session() as session:
                return await self._get_product_metrics_bulk(session, ids)
        except Exception as e:
            self._logger.exception("Failed to get bulk product statistics")
            raise BaseGiljoError(
                message=f"Failed to get bulk product statistics: {e!s}",
                context={"product_count": len(ids), "tenant_key": self.tenant_key},
            ) from e

    async def get_vision_summary_bulk(self, product_ids: list[str]) -> dict[str, dict[str, int]]:
        if not product_ids:
            return {}
        ids = [str(pid) for pid in product_ids]
        try:
            async with self._get_session() as session:
                return await self._repo.vision_summary_bulk(session, ids, self.tenant_key)
        except Exception as e:
            self._logger.exception("Failed to get bulk vision summary")
            raise BaseGiljoError(
                message=f"Failed to get bulk vision summary: {e!s}",
                context={"product_count": len(ids), "tenant_key": self.tenant_key},
            ) from e

    async def get_cascade_impact(self, product_id: str) -> CascadeImpact:
        try:
            async with self._get_session() as session:
                product = await self._repo.get_product_by_id(session, product_id, self.tenant_key)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

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
        except Exception as e:
            self._logger.exception("Failed to get cascade impact")
            raise BaseGiljoError(
                message=f"Failed to get cascade impact: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def _build_product_memory_response(
        self, session: AsyncSession, product: Product, include_deleted: bool = False
    ) -> dict:
        base_memory = product.product_memory or {}
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
            await self._repo.refresh_product(session, product)
            self._logger.info(f"Product {product.id}: Updated product_memory structure")

    async def _get_product_metrics(self, session: AsyncSession, product_id: str) -> dict[str, Any]:
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
        async with self._get_session() as session:
            product = await self._repo.get_product_by_id(session, product_id, self.tenant_key)

            if not product:
                raise ResourceNotFoundError(
                    message=f"Product {product_id} not found or not accessible",
                    context={"product_id": product_id},
                )

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
        from giljo_mcp.tools.context_tools.get_360_memory import _apply_legacy_tag_mapping

        limit = max(1, min(limit, SEARCH_MEMORY_LIMIT_MAX))
        clean_query = (query or "").strip()

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


    async def get_entries_by_last_n_projects(
        self,
        product_id: str,
        last_n_projects: int = 3,
        offset: int = 0,
        include_deleted: bool = False,
        session: AsyncSession | None = None,
    ) -> tuple[list, int]:
        async with nullcontext(session) if session is not None else self._get_session() as active:
            return await self._repo.get_entries_by_last_n_projects(
                session=active,
                product_id=product_id,
                tenant_key=self.tenant_key,
                last_n_projects=last_n_projects,
                offset=offset,
                include_deleted=include_deleted,
            )


    async def get_git_history(
        self,
        product_id: str,
        limit: int = 25,
        session: AsyncSession | None = None,
    ) -> list:
        async with nullcontext(session) if session is not None else self._get_session() as active:
            return await self._repo.get_git_history(
                session=active,
                product_id=product_id,
                tenant_key=self.tenant_key,
                limit=limit,
            )

    async def get_closeout_entry_for_project(
        self,
        project_id: str,
        session: AsyncSession | None = None,
    ) -> ProductMemoryEntry | None:
        stmt = (
            select(ProductMemoryEntry)
            .where(
                ProductMemoryEntry.tenant_key == self.tenant_key,
                ProductMemoryEntry.project_id == project_id,
                ProductMemoryEntry.entry_type == "project_closeout",
                ProductMemoryEntry.user_deleted_at.is_(None),
            )
            .order_by(ProductMemoryEntry.sequence.asc())
            .limit(1)
        )
        async with nullcontext(session) if session is not None else self._get_session() as active:
            with tenant_session_context(active, self.tenant_key):
                return (await active.execute(stmt)).scalar_one_or_none()

    async def get_next_sequence(
        self,
        product_id: str | Any,
        session: AsyncSession | None = None,
    ) -> int:
        async with nullcontext(session) if session is not None else self._get_session() as active:
            return await self._repo.get_next_sequence(
                session=active,
                product_id=product_id,
                tenant_key=self.tenant_key,
            )

    async def create_entry(
        self,
        params: MemoryEntryCreateParams,
        session: AsyncSession | None = None,
    ) -> ProductMemoryEntry:
        async with nullcontext(session) if session is not None else self._get_session() as active:
            return await self._create_entry_verified(active, params)

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

