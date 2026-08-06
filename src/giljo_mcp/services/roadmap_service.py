# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
RoadmapService — owning service for the Roadmapping Pane (FE-6022a).

Owns ALL writes to ``roadmaps`` + ``roadmap_items``. Mirrors ProjectService /
TaskService conventions: session handling, tenant scoping, exceptions-on-error
(post-0480 — never a success-dict). Every read and write filters ``tenant_key``
and scopes to the active product.

Responsibilities:
- Lazy-create the product's single roadmap on first write (race-safe via
  ``INSERT ... ON CONFLICT (product_id) DO NOTHING`` then re-select).
- Bulk upsert roadmap items (``INSERT ... ON CONFLICT ON CONSTRAINT
  uq_roadmap_item DO UPDATE``) — de-dupes on (roadmap, item_type, project/task).
- Reorder items by sort_order after a drag.
- Read the roadmap joined to project/task display fields, sorted by sort_order.

Validation discipline (no unvalidated agent input → DB): item_type / risk /
complexity membership and the sort_order cap are enforced here BEFORE any DB
write, raising ValidationError (→ 422) rather than letting a DB constraint
produce a 500. Items may only reference entities of the active product +
tenant (no cross-product leakage).

Edition Scope: CE.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import LIFECYCLE_FINISHED_STATUSES, ProjectStatus
from giljo_mcp.domain.task_status import TASK_LIFECYCLE_FINISHED_STATUSES
from giljo_mcp.exceptions import (
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Project, Task
from giljo_mcp.models.roadmaps import (
    Roadmap,
    RoadmapItem,
)
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.roadmap_validation import (
    validate_items,
    validate_remove,
    validate_reorder,
)
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class RoadmapService:
    """Service for the per-product roadmap. Session-scoped; do not share across requests."""

    def __init__(
        self,
        db_manager: DatabaseManager = None,
        tenant_manager: TenantManager = None,
        session: AsyncSession | None = None,
        websocket_manager: Any | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._session = session  # injected test session for transaction isolation
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(
            self.db_manager,
            tenant_key or (self.tenant_manager.get_current_tenant() if self.tenant_manager else None),
            self._session,
        )

    async def _resolve_active_product_id(self, tenant_key: str) -> str | None:
        from giljo_mcp.services.product_service import ProductService

        product_service = ProductService(
            db_manager=self.db_manager,
            tenant_key=tenant_key,
            test_session=self._session,
        )
        product = await product_service.get_active_product(eager_load=False)
        return str(product.id) if product else None

    # ------------------------------------------------------------------
    # Roadmap lazy-create (race-safe)
    # ------------------------------------------------------------------

    async def _get_or_create_roadmap(self, session: AsyncSession, tenant_key: str, product_id: str) -> Roadmap:
        """Return the product's roadmap, creating it on first write.

        Race-safe: ON CONFLICT (product_id) DO NOTHING then re-select, so a
        concurrent first write does not raise a unique violation.
        """
        from giljo_mcp.models.base import generate_uuid

        insert_stmt = (
            pg_insert(Roadmap)
            .values(id=generate_uuid(), tenant_key=tenant_key, product_id=product_id)
            .on_conflict_do_nothing(index_elements=["product_id"])
        )
        await session.execute(insert_stmt)

        result = await session.execute(
            select(Roadmap).where(Roadmap.tenant_key == tenant_key, Roadmap.product_id == product_id)
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def upsert_metadata(
        self,
        *,
        items: Any,
        summary: str | None = None,
        remove: Any = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Bulk upsert roadmap items for the active product's roadmap.

        Validates every item at the boundary, lazy-creates the roadmap, asserts
        each referenced project/task belongs to the active product + tenant,
        then upserts (de-duping on the uq_roadmap_item constraint).

        ``remove`` (0006) is an optional list of ``{item_type, project_id |
        task_id}`` refs to drop from the active roadmap IN THE SAME transaction.
        Removal is scoped to this product's roadmap + tenant and is idempotent:
        a ref that matches no row is a clean no-op (counted 0), never an error.
        When the same item appears in both ``items`` and ``remove``, removal
        runs last and wins. Returns ``items_upserted`` + ``items_removed``.
        """
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "upsert_roadmap_items"})

            validated = validate_items(items)
            validated_remove = validate_remove(remove)

            product_id = await self._resolve_active_product_id(effective_tenant_key)
            if not product_id:
                raise ValidationError(
                    message="No active product set. Please activate a product first.",
                    context={"operation": "upsert_roadmap_items", "tenant_key": effective_tenant_key},
                )

            async with self._get_session(effective_tenant_key) as session:
                roadmap = await self._get_or_create_roadmap(session, effective_tenant_key, product_id)
                await self._assert_items_in_product(session, effective_tenant_key, product_id, validated)

                await self._upsert_many(session, effective_tenant_key, roadmap.id, validated)

                # Removal runs AFTER the upsert so a contradictory same-item
                # (in both lists) ends removed — predictable last-write-wins.
                items_removed = await self._remove_refs(session, effective_tenant_key, roadmap.id, validated_remove)

                roadmap.last_generated_at = datetime.now(UTC)
                if summary is not None:
                    roadmap.summary = summary

                await session.commit()
                roadmap_id = roadmap.id

            self._logger.info(
                "Upserted %d / removed %d roadmap item(s) for product %s (tenant=%s)",
                len(validated),
                items_removed,
                product_id,
                effective_tenant_key,
            )

            # FE-6022c: broadcast a tenant-scoped event so the Roadmap pane
            # re-fetches live and clears its "Waiting for your agent…" indicator
            # without a manual refresh. Mirrors TaskService's task:updated emit
            # (task_service.py:599-613). Pass tenant_key EXPLICITLY — the
            # ToolAccessor RoadmapService is a long-lived singleton, so we must
            # not rely on ambient tenant context here. Non-critical: a broadcast
            # failure is logged but never blocks the write.
            ws = self._websocket_manager
            if ws:
                try:
                    await ws.broadcast_to_tenant(
                        tenant_key=effective_tenant_key,
                        event_type="roadmap:updated",
                        data={
                            "product_id": product_id,
                            "roadmap_id": roadmap_id,
                            "items_upserted": len(validated),
                            "items_removed": items_removed,
                        },
                    )
                except (RuntimeError, ValueError, OSError) as ws_error:
                    self._logger.warning("Failed to broadcast roadmap:updated event: %s", ws_error)

            return {
                "roadmap_id": roadmap_id,
                "product_id": product_id,
                "items_upserted": len(validated),
                "items_removed": items_removed,
                "summary": summary,
            }
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to upsert roadmap metadata")
            raise BaseGiljoError(message=str(e), context={"operation": "upsert_roadmap_items"}) from e

    async def _assert_items_in_product(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
        validated: list[dict[str, Any]],
    ) -> None:
        """Reject any item whose project/task is not in the active product + tenant."""
        project_ids = {v["project_id"] for v in validated if v["item_type"] == "project"}
        task_ids = {v["task_id"] for v in validated if v["item_type"] == "task"}

        if project_ids:
            rows = await session.execute(
                select(Project.id).where(
                    Project.tenant_key == tenant_key,
                    Project.product_id == product_id,
                    Project.id.in_(project_ids),
                )
            )
            found = {r[0] for r in rows}
            missing = project_ids - found
            if missing:
                raise ValidationError(
                    message=f"project(s) not found in the active product: {sorted(missing)}",
                    context={"operation": "upsert_roadmap_items", "missing_project_ids": sorted(missing)},
                )

        if task_ids:
            rows = await session.execute(
                select(Task.id).where(
                    Task.tenant_key == tenant_key,
                    Task.product_id == product_id,
                    Task.deleted_at.is_(None),  # BE-6130b: can't roadmap a trashed task
                    Task.id.in_(task_ids),
                )
            )
            found = {r[0] for r in rows}
            missing = task_ids - found
            if missing:
                raise ValidationError(
                    message=f"task(s) not found in the active product: {sorted(missing)}",
                    context={"operation": "upsert_roadmap_items", "missing_task_ids": sorted(missing)},
                )

    async def _upsert_many(
        self,
        session: AsyncSession,
        tenant_key: str,
        roadmap_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        """Batch-upsert roadmap items in ONE multi-row statement (BE-9144).

        Replaces the former per-item insert loop. Items are de-duped on the
        ``uq_roadmap_item`` key (item_type, project_id, task_id) keeping the
        LAST occurrence: a single ``ON CONFLICT DO UPDATE`` cannot affect the
        same conflict target twice (Postgres cardinality violation), so this
        de-dup reproduces the last-write-wins the per-item loop got for free
        (first row inserted, later duplicate updated it). ``items_upserted`` in
        the caller still reports the raw request length, unchanged.
        """
        if not items:
            return
        from giljo_mcp.models.base import generate_uuid

        deduped: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
        for v in items:
            deduped[(v["item_type"], v["project_id"], v["task_id"])] = v

        values = [
            {
                "id": generate_uuid(),
                "tenant_key": tenant_key,
                "roadmap_id": roadmap_id,
                "item_type": v["item_type"],
                "project_id": v["project_id"],
                "task_id": v["task_id"],
                "sort_order": v["sort_order"],
                "risk": v["risk"],
                "complexity": v["complexity"],
                "blocked": v["blocked"],
                "blocked_reason": v["blocked_reason"],
            }
            for v in deduped.values()
        ]
        stmt = pg_insert(RoadmapItem).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_roadmap_item",
            set_={
                "sort_order": stmt.excluded.sort_order,
                "risk": stmt.excluded.risk,
                "complexity": stmt.excluded.complexity,
                "blocked": stmt.excluded.blocked,
                "blocked_reason": stmt.excluded.blocked_reason,
                "updated_at": func.now(),
            },
        )
        await session.execute(stmt)

    async def _remove_refs(
        self,
        session: AsyncSession,
        tenant_key: str,
        roadmap_id: str,
        refs: list[dict[str, Any]],
    ) -> int:
        """Delete the roadmap_items matching ``{item_type, project_id|task_id}``
        refs in ONE statement (BE-9144), scoped to this roadmap + tenant.
        Returns the count actually deleted. A ref outside this roadmap (other
        tenant/product, or simply not on it) matches nothing — idempotent no-op,
        never a cross-scope delete. Removes ONLY the junction row; the underlying
        project/task is untouched.
        """
        if not refs:
            return 0

        project_ids = [r["project_id"] for r in refs if r["item_type"] == "project"]
        task_ids = [r["task_id"] for r in refs if r["item_type"] == "task"]

        clauses = []
        if project_ids:
            clauses.append(and_(RoadmapItem.item_type == "project", RoadmapItem.project_id.in_(project_ids)))
        if task_ids:
            clauses.append(and_(RoadmapItem.item_type == "task", RoadmapItem.task_id.in_(task_ids)))
        if not clauses:
            return 0

        stmt = delete(RoadmapItem).where(
            RoadmapItem.tenant_key == tenant_key,
            RoadmapItem.roadmap_id == roadmap_id,
            or_(*clauses),
        )
        result = await session.execute(stmt)
        return result.rowcount or 0

    async def reorder(
        self,
        *,
        updates: Any,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Bulk sort_order update for the active product's roadmap items.

        Only items belonging to the active product's roadmap (tenant-scoped) are
        updated; unknown / cross-tenant / cross-product ids are silently skipped
        (the count reflects what was actually changed).
        """
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "reorder_roadmap"})

            normalized = validate_reorder(updates)

            product_id = await self._resolve_active_product_id(effective_tenant_key)
            if not product_id:
                raise ResourceNotFoundError(message="No active product set.", context={"operation": "reorder_roadmap"})

            async with self._get_session(effective_tenant_key) as session:
                roadmap_res = await session.execute(
                    select(Roadmap).where(Roadmap.tenant_key == effective_tenant_key, Roadmap.product_id == product_id)
                )
                roadmap = roadmap_res.scalar_one_or_none()
                if roadmap is None:
                    raise ResourceNotFoundError(
                        message="No roadmap exists for the active product yet.",
                        context={"operation": "reorder_roadmap", "product_id": product_id},
                    )

                ids = [u["id"] for u in normalized]
                items_res = await session.execute(
                    select(RoadmapItem).where(
                        RoadmapItem.tenant_key == effective_tenant_key,
                        RoadmapItem.roadmap_id == roadmap.id,
                        RoadmapItem.id.in_(ids),
                    )
                )
                items_by_id = {it.id: it for it in items_res.scalars().all()}

                updated = 0
                for u in normalized:
                    item = items_by_id.get(u["id"])
                    if item is None:
                        continue
                    item.sort_order = u["sort_order"]
                    updated += 1

                await session.commit()
                roadmap_id = roadmap.id

            self._logger.info(
                "Reordered %d roadmap item(s) for product %s (tenant=%s)",
                updated,
                product_id,
                effective_tenant_key,
            )
            return {"roadmap_id": roadmap_id, "product_id": product_id, "items_reordered": updated}
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to reorder roadmap")
            raise BaseGiljoError(message=str(e), context={"operation": "reorder_roadmap"}) from e

    async def repoint_item_task_to_project(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        task_id: str,
        new_project_id: str,
    ) -> bool:
        """Re-point a roadmap item from a converted task to its new project, IN PLACE.

        Called from the task→project conversion flow (TaskConversionService)
        BEFORE the task row is hard-deleted, so the ON DELETE CASCADE on
        ``roadmap_items.task_id`` (ce_0047) does not silently remove the item.
        The item keeps its sort_order/position — only the discriminator flips
        (``item_type`` task→project, ``task_id``→NULL, ``project_id`` set). The
        user runs Refresh if they want a re-rank; conversion never reorders.

        Operates within the CALLER's session/transaction (flush only, no commit
        — the conversion owns the commit). Returns True if any item was
        re-pointed. Handles the rare ``uq_roadmap_item`` conflict where the new
        project is ALREADY on the same roadmap: the orphaned task item is
        deleted instead (the existing project item stands).
        """
        res = await session.execute(
            select(RoadmapItem).where(
                RoadmapItem.tenant_key == tenant_key,
                RoadmapItem.item_type == "task",
                RoadmapItem.task_id == task_id,
            )
        )
        items = list(res.scalars().all())
        if not items:
            return False

        repointed = False
        for item in items:
            # Would flipping collide with an existing project item on the same
            # roadmap (uq_roadmap_item, NULLS NOT DISTINCT)? If so, the project
            # is already roadmapped — drop the orphaned task item instead.
            existing = await session.execute(
                select(RoadmapItem.id).where(
                    RoadmapItem.tenant_key == tenant_key,
                    RoadmapItem.roadmap_id == item.roadmap_id,
                    RoadmapItem.item_type == "project",
                    RoadmapItem.project_id == new_project_id,
                )
            )
            if existing.first() is not None:
                await session.delete(item)
                continue
            item.item_type = "project"
            item.project_id = new_project_id
            item.task_id = None
            repointed = True

        await session.flush()
        if repointed:
            self._logger.info(
                "Re-pointed roadmap item(s) for converted task %s -> project %s (tenant=%s)",
                sanitize(task_id),
                new_project_id,
                tenant_key,
            )
        return repointed

    async def remove_item(
        self,
        *,
        item_id: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Remove ONE item from the active product's roadmap (FE-6022c-polish).

        Scoped to the caller's tenant_key AND the active product's roadmap: an
        ``item_id`` belonging to another tenant, or to a different product's
        roadmap, or simply unknown, is a clean no-op (``removed=0``) — never a
        500 and never a cross-tenant/cross-product delete. Removes ONLY the
        ``roadmap_item`` row; the underlying project/task is untouched. Raises
        ResourceNotFoundError (→ 404) only when no product is active (mirrors
        ``get_roadmap`` / ``reorder``).
        """
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "remove_roadmap_item"})
            if not item_id:
                raise ValidationError(message="item_id is required", context={"operation": "remove_roadmap_item"})

            product_id = await self._resolve_active_product_id(effective_tenant_key)
            if not product_id:
                raise ResourceNotFoundError(
                    message="No active product set.", context={"operation": "remove_roadmap_item"}
                )

            async with self._get_session(effective_tenant_key) as session:
                roadmap_res = await session.execute(
                    select(Roadmap).where(Roadmap.tenant_key == effective_tenant_key, Roadmap.product_id == product_id)
                )
                roadmap = roadmap_res.scalar_one_or_none()
                if roadmap is None:
                    return {"product_id": product_id, "roadmap_id": None, "removed": 0}

                # Tenant + active-product scoped lookup: an id outside this
                # roadmap (other tenant / other product / unknown) finds nothing.
                item_res = await session.execute(
                    select(RoadmapItem).where(
                        RoadmapItem.tenant_key == effective_tenant_key,
                        RoadmapItem.roadmap_id == roadmap.id,
                        RoadmapItem.id == str(item_id),
                    )
                )
                item = item_res.scalar_one_or_none()
                roadmap_id = roadmap.id
                if item is None:
                    return {"product_id": product_id, "roadmap_id": roadmap_id, "removed": 0}

                await session.delete(item)
                await session.commit()

            self._logger.info(
                "Removed roadmap item %s for product %s (tenant=%s)",
                sanitize(item_id),
                product_id,
                effective_tenant_key,
            )
            return {"product_id": product_id, "roadmap_id": roadmap_id, "removed": 1}
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to remove roadmap item")
            raise BaseGiljoError(message=str(e), context={"operation": "remove_roadmap_item"}) from e

    async def _broadcast_agent_active(self, tenant_key: str, product_id: str) -> None:
        """Best-effort "an agent just connected to work on the roadmap" signal.

        FE-6240: emitted from the MCP ``get_roadmap`` read path (the agent's
        first touch) so the Roadmap pane raises its "Waiting for your agent…"
        spinner on the REAL agent connection rather than the user's copy-prompt
        click. Non-critical: a broadcast failure is logged and never blocks the
        read. Pass ``tenant_key`` EXPLICITLY — the ToolAccessor RoadmapService is
        a long-lived singleton, so there is no ambient tenant context to rely on
        (mirrors the ``upsert_metadata`` broadcast).
        """
        ws = self._websocket_manager
        if not ws:
            return
        try:
            await ws.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="roadmap:agent_active",
                data={"product_id": product_id},
            )
        except (RuntimeError, ValueError, OSError) as ws_error:
            self._logger.warning("Failed to broadcast roadmap:agent_active event: %s", ws_error)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_roadmap(self, tenant_key: str | None = None, emit_agent_active: bool = False) -> dict[str, Any]:
        """Return the active product's roadmap + items joined to display fields.

        Shape: ``{product_id, roadmap: {...}|null, items: [...]}``. Items are
        sorted by sort_order (then created_at). 0006 (HARD AUTO-DROP): terminal
        projects/tasks are EXCLUDED from the active roadmap — this deliberately
        REVERSES the FE-6022c choice to surface them with a badge, because a
        terminal item with no actionable state pins/locks the plan. See
        ``_build_item_rows`` for the exact drop rule. Raises
        ResourceNotFoundError when no product is active.
        """
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "get_roadmap"})

            product_id = await self._resolve_active_product_id(effective_tenant_key)
            if not product_id:
                raise ResourceNotFoundError(message="No active product set.", context={"operation": "get_roadmap"})

            # FE-6240: the MCP read path (agent's first touch) passes
            # emit_agent_active=True so the Roadmap pane shows its waiting
            # spinner the moment the agent connects. The REST read (the user's
            # own page load) leaves it False, so a user visit never trips it.
            if emit_agent_active:
                await self._broadcast_agent_active(effective_tenant_key, product_id)

            async with self._get_session(effective_tenant_key) as session:
                roadmap_res = await session.execute(
                    select(Roadmap).where(Roadmap.tenant_key == effective_tenant_key, Roadmap.product_id == product_id)
                )
                roadmap = roadmap_res.scalar_one_or_none()
                if roadmap is None:
                    return {"product_id": product_id, "roadmap": None, "items": []}

                items_res = await session.execute(
                    select(RoadmapItem)
                    .where(
                        RoadmapItem.tenant_key == effective_tenant_key,
                        RoadmapItem.roadmap_id == roadmap.id,
                    )
                    .order_by(RoadmapItem.sort_order.asc(), RoadmapItem.created_at.asc())
                )
                items = list(items_res.scalars().all())
                rows = await self._build_item_rows(session, effective_tenant_key, items)

                return {
                    "product_id": product_id,
                    "roadmap": {
                        "id": roadmap.id,
                        "summary": roadmap.summary,
                        "last_generated_at": roadmap.last_generated_at.isoformat()
                        if roadmap.last_generated_at
                        else None,
                        "updated_at": roadmap.updated_at.isoformat() if roadmap.updated_at else None,
                    },
                    "items": rows,
                }
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to read roadmap")
            raise BaseGiljoError(message=str(e), context={"operation": "get_roadmap"}) from e

    async def _build_item_rows(
        self,
        session: AsyncSession,
        tenant_key: str,
        items: list[RoadmapItem],
    ) -> list[dict[str, Any]]:
        """Join items to project/task display fields in two batched queries.

        0006 (HARD AUTO-DROP): a project whose effective status is terminal
        (``LIFECYCLE_FINISHED_STATUSES`` = completed/cancelled/terminated/
        deleted, or soft-deleted via ``deleted_at``) and a task whose status is
        terminal (``TASK_LIFECYCLE_FINISHED_STATUSES`` = completed/cancelled) are
        DROPPED from the active roadmap — they no longer pin/lock the plan. The
        live ``active`` (ACTIVATED) project status is NOT terminal: it stays
        (reversible via Deactivate). Hard-deleted rows (project/task gone) drop
        as before. Reverses the FE-6022c surface-with-badge behavior on purpose.
        """
        project_ids = [it.project_id for it in items if it.item_type == "project" and it.project_id]
        task_ids = [it.task_id for it in items if it.item_type == "task" and it.task_id]

        projects: dict[str, Project] = {}
        if project_ids:
            res = await session.execute(
                select(Project)
                .options(joinedload(Project.project_type))
                .where(Project.tenant_key == tenant_key, Project.id.in_(project_ids))
            )
            projects = {p.id: p for p in res.scalars().all()}

        tasks: dict[str, Task] = {}
        if task_ids:
            res = await session.execute(
                select(Task)
                .options(joinedload(Task.task_type))
                # BE-6130b: trashed tasks drop off the roadmap (the row builder
                # below already skips a task_id that resolves to None).
                .where(Task.tenant_key == tenant_key, Task.deleted_at.is_(None), Task.id.in_(task_ids))
            )
            tasks = {t.id: t for t in res.scalars().all()}

        rows: list[dict[str, Any]] = []
        for it in items:
            if it.item_type == "project":
                proj = projects.get(it.project_id)
                # Project.status is a Postgres enum (ProjectStatus member); coerce
                # to its string value for the wire contract + the terminal check.
                proj_status = getattr(proj.status, "value", proj.status) if proj else None
                # Drop HARD-deleted projects (row gone — the roadmap_item is being
                # cascaded away too).
                if proj is None:
                    continue
                status = "deleted" if proj.deleted_at is not None else proj_status
                # 0006 HARD AUTO-DROP: a terminal project no longer pins the
                # active roadmap (reverses FE-6022c surfacing). `active` is NOT
                # terminal — an activated project stays (reversible).
                if status in LIFECYCLE_FINISHED_STATUSES:
                    continue
                # IMP-9258: `parked` is its OWN hidden-but-not-finished
                # exclusion -- deliberately NOT folded into
                # LIFECYCLE_FINISHED_STATUSES (it is resumable and stays
                # visible in normal project lists), but a parked project
                # should not pin the active roadmap plan either.
                if status == ProjectStatus.PARKED:
                    continue
                title = proj.name
                taxonomy_alias = proj.taxonomy_alias or ""
                # Per-taxonomy color (TaxonomyType.color) so the roadmap alias
                # chip matches the tinted serial badge in the project/task lists,
                # instead of a single static color. None falls back client-side.
                taxonomy_color = proj.project_type.color if proj.project_type else None
            else:
                task = tasks.get(it.task_id)
                if task is None:
                    continue
                status = task.status
                # 0006 HARD AUTO-DROP: a terminal task (completed/cancelled) is
                # excluded too — symmetric with projects, so it can't pin the plan.
                if status in TASK_LIFECYCLE_FINISHED_STATUSES:
                    continue
                title = task.title
                taxonomy_alias = task.taxonomy_alias or ""
                taxonomy_color = task.task_type.color if task.task_type else None

            rows.append(
                {
                    "id": it.id,
                    "item_type": it.item_type,
                    "project_id": it.project_id,
                    "task_id": it.task_id,
                    "title": title,
                    "taxonomy_alias": taxonomy_alias,
                    "taxonomy_color": taxonomy_color,
                    "status": status,
                    "sort_order": it.sort_order,
                    "risk": it.risk,
                    "complexity": it.complexity,
                    "blocked": bool(it.blocked),
                    "blocked_reason": it.blocked_reason,
                }
            )
        return rows
