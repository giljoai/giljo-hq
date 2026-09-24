# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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
from giljo_mcp.services.roadmap_references import (
    assert_items_in_product,
    resolve_refs,
)
from giljo_mcp.services.roadmap_upsert import upsert_many
from giljo_mcp.services.roadmap_validation import (
    validate_reorder,
    validate_upsert_payload,
)
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class RoadmapService:

    def __init__(
        self,
        db_manager: DatabaseManager = None,
        tenant_manager: TenantManager = None,
        session: AsyncSession | None = None,
        websocket_manager: Any | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._session = session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(
            self.db_manager,
            tenant_key or (self.tenant_manager.get_current_tenant() if self.tenant_manager else None),
            self._session,
        )

    async def _resolve_default_product_id(self, tenant_key: str) -> str | None:
        from giljo_mcp.services.product_service import ProductService

        product_service = ProductService(
            db_manager=self.db_manager,
            tenant_key=tenant_key,
            test_session=self._session,
        )
        product = await product_service.get_default_product(eager_load=False)
        return str(product.id) if product else None

    async def _resolve_scoped_product_id(
        self,
        tenant_key: str,
        product_id: str | None = None,
        *,
        operation: str,
        action: str = "read",
        write: bool,
    ) -> str:
        from giljo_mcp.services.product_service import ProductService

        product_service = ProductService(
            db_manager=self.db_manager,
            tenant_key=tenant_key,
            test_session=self._session,
        )
        product = await product_service.resolve_binding_product(
            product_id, operation=operation, action=action, write=write
        )
        return str(product.id)

    async def _resolve_product_for(
        self, tenant_key: str, product_id: str | None, *, operation: str, action: str
    ) -> str:
        if product_id:
            return await self._resolve_scoped_product_id(
                tenant_key, product_id, operation=operation, action=action, write=False
            )
        resolved = await self._resolve_default_product_id(tenant_key)
        if not resolved:
            raise ResourceNotFoundError(message="No active product set.", context={"operation": operation})
        return resolved


    async def _get_or_create_roadmap(self, session: AsyncSession, tenant_key: str, product_id: str) -> Roadmap:
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


    async def upsert_metadata(
        self,
        *,
        items: Any,
        summary: str | None = None,
        remove: Any = None,
        patch_fields: bool = False,
        tenant_key: str | None = None,
        product_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "upsert_roadmap_items"})

            validated, validated_remove = validate_upsert_payload(items, remove, patch_fields=patch_fields)

            resolved_product_id = await self._resolve_scoped_product_id(
                effective_tenant_key, product_id, operation="upsert_roadmap_items", action="written", write=True
            )
            product_id = resolved_product_id

            async with self._get_session(effective_tenant_key) as session:
                roadmap = await self._get_or_create_roadmap(session, effective_tenant_key, product_id)
                await resolve_refs(session, effective_tenant_key, product_id, validated, validated_remove)
                await assert_items_in_product(session, effective_tenant_key, product_id, validated)

                await upsert_many(session, effective_tenant_key, roadmap.id, validated, patch_fields=patch_fields)

                items_removed = await self._remove_refs(session, effective_tenant_key, roadmap.id, validated_remove)

                roadmap.last_generated_at = datetime.now(UTC)
                if summary is not None:
                    roadmap.summary = summary

                remaining = await session.scalar(
                    select(func.count())
                    .select_from(RoadmapItem)
                    .where(RoadmapItem.tenant_key == effective_tenant_key, RoadmapItem.roadmap_id == roadmap.id)
                )
                if remaining == 0:
                    roadmap.summary = None

                await session.commit()
                roadmap_id = roadmap.id

            self._logger.info(
                "Upserted %d / removed %d roadmap item(s) for product %s (tenant=%s)",
                len(validated),
                items_removed,
                product_id,
                effective_tenant_key,
            )

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
        except Exception as e:
            self._logger.exception("Failed to upsert roadmap metadata")
            raise BaseGiljoError(message=str(e), context={"operation": "upsert_roadmap_items"}) from e

    async def _remove_refs(
        self,
        session: AsyncSession,
        tenant_key: str,
        roadmap_id: str,
        refs: list[dict[str, Any]],
    ) -> int:
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
        product_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "reorder_roadmap"})

            normalized = validate_reorder(updates)

            product_id = await self._resolve_product_for(
                effective_tenant_key, product_id, operation="reorder_roadmap", action="reordered"
            )

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
        except Exception as e:
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
        product_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "remove_roadmap_item"})
            if not item_id:
                raise ValidationError(message="item_id is required", context={"operation": "remove_roadmap_item"})

            product_id = await self._resolve_product_for(
                effective_tenant_key, product_id, operation="remove_roadmap_item", action="removed"
            )

            async with self._get_session(effective_tenant_key) as session:
                roadmap_res = await session.execute(
                    select(Roadmap).where(Roadmap.tenant_key == effective_tenant_key, Roadmap.product_id == product_id)
                )
                roadmap = roadmap_res.scalar_one_or_none()
                if roadmap is None:
                    return {"product_id": product_id, "roadmap_id": None, "removed": 0}

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
        except Exception as e:
            self._logger.exception("Failed to remove roadmap item")
            raise BaseGiljoError(message=str(e), context={"operation": "remove_roadmap_item"}) from e

    async def _broadcast_agent_active(self, tenant_key: str, product_id: str) -> None:
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


    async def get_roadmap(
        self, tenant_key: str | None = None, emit_agent_active: bool = False, product_id: str | None = None
    ) -> dict[str, Any]:
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "get_roadmap"})

            product_id = await self._resolve_product_for(
                effective_tenant_key, product_id, operation="get_roadmap", action="read"
            )

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
        except Exception as e:
            self._logger.exception("Failed to read roadmap")
            raise BaseGiljoError(message=str(e), context={"operation": "get_roadmap"}) from e

    async def _build_item_rows(
        self,
        session: AsyncSession,
        tenant_key: str,
        items: list[RoadmapItem],
    ) -> list[dict[str, Any]]:
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
                .where(Task.tenant_key == tenant_key, Task.deleted_at.is_(None), Task.id.in_(task_ids))
            )
            tasks = {t.id: t for t in res.scalars().all()}

        rows: list[dict[str, Any]] = []
        for it in items:
            if it.item_type == "project":
                proj = projects.get(it.project_id)
                proj_status = getattr(proj.status, "value", proj.status) if proj else None
                if proj is None:
                    continue
                status = "deleted" if proj.deleted_at is not None else proj_status
                if status in LIFECYCLE_FINISHED_STATUSES:
                    continue
                if status == ProjectStatus.PARKED:
                    continue
                title = proj.name
                taxonomy_alias = proj.taxonomy_alias or ""
                taxonomy_color = proj.project_type.color if proj.project_type else None
            else:
                task = tasks.get(it.task_id)
                if task is None:
                    continue
                status = task.status
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
