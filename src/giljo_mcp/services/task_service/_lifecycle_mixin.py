# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import (
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Task
from giljo_mcp.schemas.service_responses import ConversionResult
from giljo_mcp.utils.log_sanitizer import sanitize


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
            try:
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
            except (RuntimeError, ValueError, OSError) as ws_error:
                self._logger.warning(f"Failed to broadcast task:updated event: {ws_error}")

        return task

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
