# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import (
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Task
from giljo_mcp.schemas.service_responses import ConversionResult
from giljo_mcp.services.bulk_close import (
    REASON_NOT_AUTHORIZED,
    REASON_NOT_FOUND,
    REASON_PENDING_HANDOVER,
    BulkCloseOutcome,
    bulk_event_data,
    unique_ids,
)
from giljo_mcp.services.handover_validation import HANDOVER_TYPE_ABBR
from giljo_mcp.utils.log_sanitizer import sanitize


def _is_pending_handover(task: Task) -> bool:
    task_type = getattr(task, "task_type", None)
    return getattr(task_type, "abbreviation", None) == HANDOVER_TYPE_ABBR and task.status == "pending"


class _TaskLifecycleMixin:

    async def convert_to_project(self, *a, **kw) -> ConversionResult:
        return await self._conversion.convert_to_project(*a, **kw)

    async def change_status(self, task_id: str, new_status: str) -> Task:
        try:
            async with self._get_session() as session:
                task = await self._change_status_impl(session, task_id, new_status)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:
            self._logger.exception(f"Failed to change task {sanitize(task_id)} status")
            raise BaseGiljoError(message=str(e), context={"operation": "change_status", "task_id": task_id}) from e

        ws = self._websocket_manager
        if ws:
            await ws.broadcast_to_tenant(
                tenant_key=self.tenant_manager.get_current_tenant(),
                event_type="task:updated",
                data={
                    "task_id": task_id,
                    "updated_fields": ["status"],
                    "hidden": bool(getattr(task, "hidden", False)),
                    "status": task.status,
                    "product_id": task.product_id,
                },
            )

        return task

    async def bulk_close_tasks(self, action: str, task_ids: list[str], user_id: str) -> dict[str, Any]:
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={"operation": "bulk_close_tasks"})
        outcome = BulkCloseOutcome()
        async with self._get_session() as session:
            user = await self._repo.get_user_by_id(session, tenant_key, user_id)
            if not user:
                raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})
            for task_id in unique_ids(task_ids):
                task = await self._repo.get_task_by_id(session, task_id, tenant_key)
                if task is None:
                    outcome.skip(task_id, REASON_NOT_FOUND)
                elif not self._conversion.can_delete_task(task, user):
                    outcome.skip(task_id, REASON_NOT_AUTHORIZED)
                elif action == "archive" and _is_pending_handover(task):
                    outcome.skip(task_id, REASON_PENDING_HANDOVER)
                else:
                    if action == "delete":
                        await self._delete_task_impl(session, task_id, user_id)
                    else:
                        await self._update_task_impl(session, task_id, broadcast=False, hidden=action == "archive")
                    outcome.done.append(task_id)
        if outcome.done and self._websocket_manager:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="tasks:bulk_updated",
                data=bulk_event_data(action, outcome.done),
            )
        return outcome.as_dict()

    async def _change_status_impl(self, session: AsyncSession, task_id: str, new_status: str) -> Task:
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available", context={"operation": "change_status", "task_id": task_id}
            )

        task = await self._repo.get_task_by_id(session, task_id, tenant_key)

        if not task:
            raise ResourceNotFoundError(
                message="Task not found", context={"task_id": task_id, "tenant_key": tenant_key}
            )

        task.status = new_status

        now = datetime.now(UTC)
        if new_status == "in_progress" and not task.started_at:
            task.started_at = now
        elif new_status in ("completed", "cancelled") and not task.completed_at:
            task.completed_at = now

        await self._repo.flush_and_refresh(session, task)

        self._logger.info(f"Changed task {sanitize(task_id)} status to {sanitize(new_status)}")

        return task


    async def _change_status_with_tenant(self, task_id: str, new_status: str, tenant_key: str) -> Task:

        async def _do(session: AsyncSession) -> Task:
            task = await self._repo.get_task_by_id(session, task_id, tenant_key)
            if not task:
                raise ResourceNotFoundError(
                    message="Task not found",
                    context={"task_id": task_id, "tenant_key": tenant_key},
                )
            task.status = new_status
            now = datetime.now(UTC)
            if new_status == "in_progress" and not task.started_at:
                task.started_at = now
            elif new_status in ("completed", "cancelled") and not task.completed_at:
                task.completed_at = now
            await self._repo.flush_and_refresh(session, task)
            self._logger.info("Task %s status -> %s (tenant=%s)", task_id, new_status, tenant_key)
            return task

        async with self._get_session(tenant_key) as session:
            return await _do(session)

    async def append_completion_notes(self, task_id: str, notes: str) -> None:
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="tenant_key is required",
                context={"operation": "append_completion_notes", "task_id": task_id},
            )
        await self._append_completion_notes(task_id, tenant_key, notes)

    async def _append_completion_notes(self, task_id: str, tenant_key: str, notes: str) -> None:

        async def _do(session: AsyncSession) -> None:
            task = await self._repo.get_task_by_id(session, task_id, tenant_key)
            if not task:
                return
            stamped = f"\n\n[completed {datetime.now(UTC).isoformat()}] {notes}"
            task.description = (task.description or "") + stamped
            await self._repo.flush_and_refresh(session, task)

        async with self._get_session(tenant_key) as session:
            await _do(session)
