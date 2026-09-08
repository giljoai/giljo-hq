# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Task status/conversion/completion-notes mixin for TaskService (BE-9073 item 2 split).

Split out of ``_mutation_mixin`` (which would otherwise land at 836 lines,
over the 800-line cap -- INF-9059 permits no new grandfathered files) so both
write-path mixins stay under the cap with no ``size_budgets.txt`` entry. Holds
the conversion facade, status-change lifecycle, and completion-notes
audit-trail methods. Composed into ``TaskService``; references ``self.*`` /
``self._*`` only. Behavior is byte-identical to the pre-split single-file
class -- methods moved verbatim.
"""

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
    """Task status/conversion/completion-notes methods. Composed into TaskService."""

    async def convert_to_project(self, *a, **kw) -> ConversionResult:
        """Facade: delegates to TaskConversionService."""
        return await self._conversion.convert_to_project(*a, **kw)

    async def change_status(self, task_id: str, new_status: str) -> Task:
        """Change task status with automatic timestamp updates.

        Status transitions:
        - * -> "in_progress" (if unset): Set started_at
        - * -> "completed": Set completed_at
        - * -> "cancelled": Set completed_at

        Args:
            task_id: Task UUID
            new_status: New status value

        Returns:
            Task ORM model with updated status and timestamps (0731c typed return)

        Raises:
            ValidationError: No tenant context
            ResourceNotFoundError: Task not found
            DatabaseError: Database operation failed

        Example:
            >>> task = await service.change_status("abc-123", "in_progress")
            >>> print(task.status)
        """
        try:
            async with self._get_session() as session:
                task = await self._change_status_impl(session, task_id, new_status)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception(f"Failed to change task {sanitize(task_id)} status")
            raise BaseGiljoError(message=str(e), context={"operation": "change_status", "task_id": task_id}) from e

        # FE-9274: broadcast STRICTLY post-commit -- ``_get_session()`` (no
        # injected test session) commits on the ``async with`` block's clean
        # exit above, so the status change is durable by this point. This was
        # the one task-mutation path with NO broadcast at all (unlike
        # update_task's task:updated below it in _mutation_mixin) -- the FE
        # dashboard's status-change dropdown calls exactly this method via
        # PATCH /tasks/{id}/status/, so a stale task list never repainted.
        # Reuses the SAME task:updated shape update_task emits so the FE event
        # router needs only one handler for both mutation paths.
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
        """Implementation of change_status with explicit session parameter.

        Returns:
            Task ORM model with updated status and timestamps

        Raises:
            ValidationError: No tenant context
            ResourceNotFoundError: Task not found
        """
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

        # Update status
        task.status = new_status

        # Update timestamps based on status
        now = datetime.now(UTC)
        if new_status == "in_progress" and not task.started_at:
            task.started_at = now
        elif new_status in ("completed", "cancelled") and not task.completed_at:
            task.completed_at = now

        await self._repo.flush_and_refresh(session, task)

        self._logger.info(f"Changed task {sanitize(task_id)} status to {sanitize(new_status)}")

        return task

    # ------------------------------------------------------------------
    # MCP-task helpers (private)
    # ------------------------------------------------------------------

    async def _change_status_with_tenant(self, task_id: str, new_status: str, tenant_key: str) -> Task:
        """Tenant-explicit variant of change_status. Routes through repo."""

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
        """Public entry point for appending completion notes (REST PATCH path).

        Resolves tenant from TenantManager (matches the rest of the public
        TaskService surface). Delegates to ``_append_completion_notes`` so the
        REST and MCP paths share a single audit-trail format.
        """
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="tenant_key is required",
                context={"operation": "append_completion_notes", "task_id": task_id},
            )
        await self._append_completion_notes(task_id, tenant_key, notes)

    async def _append_completion_notes(self, task_id: str, tenant_key: str, notes: str) -> None:
        """Append completion notes to the task description (audit trail)."""

        async def _do(session: AsyncSession) -> None:
            task = await self._repo.get_task_by_id(session, task_id, tenant_key)
            if not task:
                return
            stamped = f"\n\n[completed {datetime.now(UTC).isoformat()}] {notes}"
            task.description = (task.description or "") + stamped
            await self._repo.flush_and_refresh(session, task)

        async with self._get_session(tenant_key) as session:
            await _do(session)
