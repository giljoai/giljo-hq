# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.domain.task_status import VALID_TASK_STATUSES
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Task
from giljo_mcp.services._mcp_wire_bounds import worst_case_cursor_charge
from giljo_mcp.services.task_service._mcp_filter_validators import (
    resolve_active_product_for_list_tasks,
    resolve_list_mode,
    resolve_list_tasks_filters_and_cursor,
    resolve_task_type_id,
)
from giljo_mcp.services.task_service._mcp_read_layer import (
    TASK_CURSOR_AXIS,
    apply_bounds,
    apply_task_filters,
    mint_task_next_cursor,
    task_counts,
    task_keyset_after,
    task_to_index_row,
)
from giljo_mcp.tenant import current_tenant
from giljo_mcp.utils.taxonomy_alias import format_taxonomy_alias


_VALID_LIST_MODES = ("index", "summary", "full")


def _parse_due_date(value: Any, *, operation: str, field: str = "due_date", task_id: str = "") -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    context: dict[str, Any] = {"operation": operation}
    if task_id:
        context["task_id"] = task_id
    raise ValidationError(
        message=(
            f"Invalid {field} {value!r}. Pass an ISO 8601 date or datetime, "
            "e.g. '2026-07-15' or '2026-07-15T09:00:00+00:00'."
        ),
        context=context,
    )


class McpAdapterMixin:

    async def create_task_for_mcp(
        self,
        title: str,
        description: str,
        priority: str = "medium",
        task_type: str | None = None,
        assigned_to: str | None = None,
        product_id: str | None = None,
        tenant_key: str | None = None,
        db_manager: Any | None = None,
        websocket_manager: Any | None = None,
    ) -> dict[str, Any]:
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        effective_db = db_manager or self.db_manager

        from giljo_mcp.services.product_service import ProductService
        from giljo_mcp.services.taxonomy_service import TaxonomyService

        product_service = ProductService(
            db_manager=effective_db,
            tenant_key=effective_tenant_key,
            websocket_manager=websocket_manager,
            test_session=self._session,
        )
        bound_product = await product_service.resolve_binding_product(product_id, operation="create_task", write=True)
        product_id = bound_product.id
        product_name = bound_product.name

        taxonomy = TaxonomyService(db_manager=effective_db, session=self._session)
        reserved_type = await taxonomy.ensure_reserved_task_type(effective_tenant_key)
        task_type_id = reserved_type.id
        resolved_type_label = reserved_type.abbreviation

        assigned_series: list[int | None] = [None]
        task_id = await self.log_task(
            content=title,
            title=title,
            description=description,
            task_type_id=task_type_id,
            priority=priority,
            product_id=product_id,
            tenant_key=effective_tenant_key,
            assign_shared_series=True,
            _assigned_series_out=assigned_series,
        )

        self._logger.info(
            "Created task %s for tenant %s in product %s",
            task_id,
            effective_tenant_key,
            product_id,
        )

        if websocket_manager:
            try:
                await websocket_manager.broadcast_to_tenant(
                    tenant_key=effective_tenant_key,
                    event_type="task:created",
                    data={"task_id": task_id, "title": title, "product_id": product_id},
                )
            except (RuntimeError, ValueError, OSError) as e:
                self._logger.warning(f"Failed to broadcast task:created event: {e}")

        taxonomy_alias = ""
        if assigned_series[0] is not None:
            taxonomy_alias = format_taxonomy_alias(resolved_type_label, assigned_series[0])

        return {
            "success": True,
            "task_id": task_id,
            "title": title,
            "priority": priority,
            "task_type": resolved_type_label,
            "taxonomy_alias": taxonomy_alias,
            "product_id": product_id,
            "product_name": product_name,
            "message": f"Task '{title}' created successfully",
        }

    async def update_task_for_mcp(
        self,
        task_id: str,
        tenant_key: str | None = None,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        task_type: str | None = None,
        due_date: Any = None,
        project_id: str | None = None,
        estimated_effort: float | None = None,
        actual_effort: float | None = None,
        hidden: bool | None = None,
        completion_notes: str | None = None,
        convert_to_project: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not effective_tenant_key:
            raise ValidationError(
                message="tenant_key is required",
                context={"operation": "update_task_for_mcp", "task_id": task_id},
            )

        if convert_to_project:
            return await self._convert_task_for_mcp(
                task_id,
                effective_tenant_key,
                project_name=title,
                user_id=user_id,
                supplied={
                    "description": description,
                    "status": status,
                    "priority": priority,
                    "due_date": due_date,
                    "project_id": project_id,
                    "estimated_effort": estimated_effort,
                    "actual_effort": actual_effort,
                    "hidden": hidden,
                    "completion_notes": completion_notes,
                },
            )

        if status is not None and status not in VALID_TASK_STATUSES:
            valid_status_values = sorted(s.value for s in VALID_TASK_STATUSES)
            raise ValidationError(
                message=f"Unknown task status '{status}'. Valid statuses: {valid_status_values}",
                context={
                    "operation": "update_task_for_mcp",
                    "task_id": task_id,
                    "valid_statuses": valid_status_values,
                },
            )

        update_kwargs: dict[str, Any] = {}
        if title is not None:
            update_kwargs["title"] = title
        if description is not None:
            update_kwargs["description"] = description
        if status is not None:
            update_kwargs["status"] = status
        if priority is not None:
            update_kwargs["priority"] = priority
        if due_date is not None:
            update_kwargs["due_date"] = _parse_due_date(due_date, operation="update_task_for_mcp", task_id=task_id)
        if project_id is not None:
            update_kwargs["project_id"] = project_id
        if estimated_effort is not None:
            update_kwargs["estimated_effort"] = estimated_effort
        if actual_effort is not None:
            update_kwargs["actual_effort"] = actual_effort
        if hidden is not None:
            if not isinstance(hidden, bool):
                raise ValidationError(
                    message="hidden must be a boolean",
                    context={"operation": "update_task_for_mcp", "task_id": task_id},
                )
            update_kwargs["hidden"] = hidden


        will_append_notes = bool(completion_notes) and status == "completed"

        if not update_kwargs and not will_append_notes:
            return {
                "task_id": task_id,
                "updated_fields": [],
                "message": "No fields supplied; nothing to update.",
            }

        updated_fields: list[str] = []
        if update_kwargs:
            tenant_token = None
            if self.tenant_manager:
                tenant_token = self.tenant_manager.set_current_tenant(effective_tenant_key)
            try:
                result = await self.update_task(task_id, **update_kwargs)
            finally:
                if tenant_token is not None:
                    current_tenant.reset(tenant_token)
            updated_fields = list(result.updated_fields)

        response: dict[str, Any] = {
            "task_id": task_id,
            "updated_fields": updated_fields,
            "message": f"Task {task_id} updated: {sorted(updated_fields)}",
        }
        if will_append_notes:
            await self._append_completion_notes(task_id, effective_tenant_key, completion_notes)
            response["completion_notes"] = completion_notes
        return response

    async def _convert_task_for_mcp(
        self,
        task_id: str,
        tenant_key: str,
        *,
        project_name: str | None,
        user_id: str | None,
        supplied: dict[str, Any],
    ) -> dict[str, Any]:
        conflicting = sorted(name for name, value in supplied.items() if value is not None)
        if conflicting:
            return {
                "success": False,
                "error": "CONVERT_FIELD_CONFLICT",
                "task_id": task_id,
                "conflicting_fields": conflicting,
                "message": (
                    f"convert_to_project deletes the task row, so {conflicting} cannot be written in "
                    "the same call — they would be silently discarded. Nothing was changed. Either "
                    "convert on its own (pass only convert_to_project=true, plus title to name the "
                    "new project), or update those fields first and convert in a second call. To "
                    "record an outcome instead of promoting, drop convert_to_project and pass "
                    "status='completed'."
                ),
            }

        if not user_id:
            return {
                "success": False,
                "error": "USER_CONTEXT_REQUIRED",
                "task_id": task_id,
                "message": (
                    "Converting a task to a project runs as the authenticated user (only the task's "
                    "creator or an admin may convert), but this session's credential carries no user "
                    "identity. Nothing was changed. Re-connect with a current MCP key, or convert the "
                    "task from the dashboard."
                ),
            }

        tenant_token = None
        if self.tenant_manager:
            tenant_token = self.tenant_manager.set_current_tenant(tenant_key)
        try:
            result = await self.convert_to_project(
                task_id=task_id,
                project_name=project_name,
                strategy="single",
                include_subtasks=True,
                user_id=user_id,
            )
        finally:
            if tenant_token is not None:
                current_tenant.reset(tenant_token)

        alias = result.project_taxonomy_alias or ""
        self._logger.info(
            "Promoted task %s to project %s for tenant %s via MCP",
            task_id,
            result.project_id,
            tenant_key,
        )
        return {
            "success": True,
            "converted_to_project": True,
            "task_id": task_id,
            "task_deleted": True,
            "task_exists": False,
            "project_id": result.project_id,
            "project_name": result.project_name,
            "taxonomy_alias": alias,
            "product_id": result.product_id,
            "product_name": result.product_name,
            "project_status": "inactive",
            "project_type": None,
            "updated_fields": [],
            "message": (
                f"Task {task_id} was PROMOTED to project {result.project_id}"
                f"{f' ({alias})' if alias else ''} and the task row was DELETED — that task_id no "
                "longer resolves, and list_tasks will not return it. Subtasks and any roadmap card "
                "now point at the project (same roadmap position). The project is INACTIVE and "
                "UNTYPED: give it a taxonomy with update_project(project_id=..., "
                "project_type='BE'|'FE'|...), and the user activates or launches it from the "
                "dashboard."
            ),
        }

    async def list_tasks_for_mcp(
        self,
        tenant_key: str | None = None,
        mode: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        task_type: str | None = None,
        due_before: Any = None,
        summary_only: bool | None = None,
        memory_limit: int | None = None,
        hidden: bool | None = None,
        limit: int | None = None,
        query: str | None = None,
        cursor: str | None = None,
        product_id: str | None = None,
    ) -> dict[str, Any]:
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not effective_tenant_key:
            raise ValidationError(
                message="tenant_key is required",
                context={"operation": "list_tasks_for_mcp"},
            )

        active_product = await resolve_active_product_for_list_tasks(
            db_manager=self.db_manager,
            websocket_manager=self._websocket_manager,
            session=self._session,
            tenant_key=effective_tenant_key,
            product_id=product_id,
        )

        mode = resolve_list_mode(mode, summary_only, _VALID_LIST_MODES)

        if due_before is not None:
            due_before = _parse_due_date(due_before, operation="list_tasks_for_mcp", field="due_before")

        task_type_id = await resolve_task_type_id(
            task_type, db_manager=self.db_manager, session=self._session, tenant_key=effective_tenant_key
        )

        effective_limit, priority, cursor_fingerprint, after_key = resolve_list_tasks_filters_and_cursor(
            limit=limit,
            status=status,
            priority=priority,
            task_type_id=task_type_id,
            due_before=due_before,
            hidden=hidden,
            query=query,
            cursor=cursor,
            product_id=active_product.id,
        )

        async with self._get_session(effective_tenant_key) as session:
            tasks = await self._list_tasks_for_mcp_impl(
                session,
                effective_tenant_key,
                product_id=active_product.id,
                after_key=after_key,
                status=status,
                priority=priority,
                task_type_id=task_type_id,
                due_before=due_before,
                hidden=hidden,
                query=query,
                limit=effective_limit + 1,
            )
            counts = await task_counts(
                session,
                effective_tenant_key,
                product_id=active_product.id,
                status=status,
                priority=priority,
                task_type_id=task_type_id,
                due_before=due_before,
                hidden=hidden,
                query=query,
                after_key=after_key,
            )

        limit_cut = len(tasks) > effective_limit
        tasks = tasks[:effective_limit]

        if mode == "index":
            rows = [task_to_index_row(t) for t in tasks]
        elif mode == "summary":
            rows = [self._task_to_summary_row(t) for t in tasks]
        else:
            rows = [self._task_to_full_row(t, memory_limit=memory_limit) for t in tasks]

        response: dict[str, Any] = {
            "tasks": rows,
            "count": len(rows),
            "mode": mode,
            "tenant_key": effective_tenant_key,
            "counts": counts,
            "product_id": active_product.id,
        }
        apply_bounds(
            response,
            rows,
            limit_cut=limit_cut,
            effective_limit=effective_limit,
            cursor_charge=worst_case_cursor_charge(TASK_CURSOR_AXIS, cursor_fingerprint),
            mint_cursor=lambda kept: mint_task_next_cursor(
                returned_rows=kept, fetched_rows=tasks, fingerprint=cursor_fingerprint
            ),
            mode=mode,
        )
        counts["returned"] = response["count"]
        return response

    async def _list_tasks_for_mcp_impl(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        product_id: str,
        status: str | None,
        priority: str | None,
        task_type_id: str | None,
        due_before: Any,
        hidden: bool | None = None,
        query: str | None = None,
        limit: int | None = None,
        after_key: tuple[Any, str] | None = None,
    ) -> list[Task]:
        stmt = (
            select(Task)
            .options(selectinload(Task.task_type))
            .where(Task.tenant_key == tenant_key)
            .where(Task.product_id == product_id)
            .where(Task.deleted_at.is_(None))
            .order_by(Task.created_at.desc(), Task.id.asc())
        )
        stmt = apply_task_filters(
            stmt,
            status=status,
            priority=priority,
            task_type_id=task_type_id,
            due_before=due_before,
            hidden=hidden,
            query=query,
        )
        if after_key is not None:
            stmt = stmt.where(task_keyset_after(*after_key))
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _task_type_block(task: Task) -> dict[str, Any] | None:
        if not task.task_type:
            return None
        return {
            "id": task.task_type.id,
            "abbreviation": task.task_type.abbreviation,
            "label": task.task_type.label,
            "color": task.task_type.color,
        }

    @classmethod
    def _task_to_summary_row(cls, task: Task) -> dict[str, Any]:
        return {
            "task_id": str(task.id),
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "task_type": cls._task_type_block(task),
            "taxonomy_alias": task.taxonomy_alias or "",
            "series_number": task.series_number,
            "subseries": task.subseries,
            "hidden": bool(task.hidden),
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }

    @classmethod
    def _task_to_full_row(cls, task: Task, *, memory_limit: int | None) -> dict[str, Any]:
        description = task.description or ""
        if memory_limit and len(description) > memory_limit:
            description = description[:memory_limit] + "..."
        return {
            "task_id": str(task.id),
            "title": task.title,
            "description": description,
            "status": task.status,
            "priority": task.priority,
            "task_type": cls._task_type_block(task),
            "taxonomy_alias": task.taxonomy_alias or "",
            "series_number": task.series_number,
            "subseries": task.subseries,
            "hidden": bool(task.hidden),
            "task_type_id": task.task_type_id,
            "product_id": task.product_id,
            "project_id": task.project_id,
            "parent_task_id": task.parent_task_id,
            "estimated_effort": task.estimated_effort,
            "actual_effort": task.actual_effort,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }
