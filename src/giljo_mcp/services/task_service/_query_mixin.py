# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Task read-path mixin for TaskService (BE-9073 item 2 split).

Holds the task lookup/list/summary operations (``list_tasks``, ``get_task``,
``list_deleted_tasks``, ``get_summary``) mirroring the ``project_service``
package precedent (``QueryMixin``). Composed into ``TaskService``; references
``self.*`` / ``self._*`` only. Behavior is byte-identical to the pre-split
single-file class -- methods moved verbatim.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.exceptions import (
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Task


class _TaskQueryMixin:
    """Task read-path methods (list/get/summary). Composed into TaskService."""

    # ============================================================================
    # Task Retrieval
    # ============================================================================

    async def list_tasks(
        self,
        status: str | None = None,
        assigned_to: str | None = None,
        project_id: str | None = None,
        product_id: str | None = None,
        priority: str | None = None,
        created_by_user_id: str | None = None,
        filter_type: str | None = None,
        tenant_key: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Task]:
        """List tasks with optional filters (enhanced for API endpoint support - Handover 0324).

        Args:
            status: Filter by task status (optional)
            assigned_to: Filter by assigned agent (not yet implemented)
            project_id: Filter by project ID (optional)
            product_id: Filter by product ID (optional)
            priority: Filter by priority level (optional)
            created_by_user_id: Filter by creator user ID (optional)
            filter_type: Special filter type ('product_tasks', 'all_tasks', or None)
            tenant_key: Tenant key for filtering (uses current if not provided)
            limit: BE-9141 opt-in row cap. ``None`` (default) returns the full set,
                byte-identical to the pre-pagination behavior.
            offset: BE-9141 opt-in row offset over the stable ``created_at`` DESC
                ordering. ``None`` (default) starts from the newest row.

        Returns:
            List of Task ORM models (0731c typed return)

        Raises:
            ValidationError: No tenant context
            DatabaseError: Database operation failed

        Example:
            >>> tasks = await service.list_tasks(status="pending", priority="high")
            >>> for task in tasks:
            ...     print(f"{task.id}: {task.description}")
        """
        try:
            # Use provided tenant_key or get from context
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"operation": "list_tasks"})

            async with self._get_session(tenant_key) as session:
                return await self._list_tasks_impl(
                    session,
                    tenant_key,
                    status,
                    project_id,
                    product_id,
                    priority,
                    created_by_user_id,
                    filter_type,
                    limit,
                    offset,
                )

        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to list tasks")
            raise BaseGiljoError(message=str(e), context={"operation": "list_tasks"}) from e

    async def _list_tasks_impl(
        self,
        session: AsyncSession,
        tenant_key: str,
        status: str | None,
        project_id: str | None,
        product_id: str | None,
        priority: str | None,
        created_by_user_id: str | None,
        filter_type: str | None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Task]:
        """Implementation of list_tasks with explicit session parameter.

        Returns:
            List of Task ORM models

        Raises:
            ValidationError: No tenant context
        """
        # Start with tenant-scoped base query, eager-load task_type so callers
        # can read task.task_type.abbreviation outside the session.
        # BE-6130b: exclude soft-deleted (trashed) tasks from live listings.
        query = (
            select(Task)
            .options(selectinload(Task.task_type))
            .where(Task.tenant_key == tenant_key, Task.deleted_at.is_(None))
        )

        # Handle special filter types (product-scoped filtering)
        if filter_type == "product_tasks":
            # Use explicit product_id if provided, otherwise fall back to the
            # tenant's DEFAULT product (FE-9524: not "the shown one" -- several
            # may be shown at once, is_default is the single-valued fallback).
            if product_id:
                query = query.where(Task.product_id == product_id)
            else:
                default_product = await self._repo.get_default_product(session, tenant_key)

                if default_product:
                    query = query.where(Task.product_id == default_product.id)
                else:
                    # No default product - return empty list
                    return []

        # Apply other filters
        if product_id and not filter_type:
            query = query.where(Task.product_id == product_id)

        if project_id:
            query = query.where(Task.project_id == project_id)

        if status:
            query = query.where(Task.status == status)

        if priority:
            query = query.where(Task.priority == priority)

        if created_by_user_id:
            query = query.where(Task.created_by_user_id == created_by_user_id)

        # Order by creation date (newest first)
        query = query.order_by(Task.created_at.desc())

        # BE-9141: opt-in pagination over the stable DESC ordering. Both default
        # to None -> no clause emitted -> the full set, byte-identical to the
        # pre-pagination read. offset without limit skips from the newest row.
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)

        # Execute query
        return await self._repo.list_tasks(session, query)

    # ============================================================================
    # Enhanced Operations (Handover 0322 Phase 3)
    # ============================================================================

    async def get_task(self, task_id: str) -> Task:
        """Retrieve a single task by ID.

        This method retrieves a task with full tenant isolation.
        Only tasks within the current tenant can be accessed.

        Args:
            task_id: Task UUID

        Returns:
            Task ORM model (0731c typed return)

        Raises:
            ValidationError: No tenant context
            ResourceNotFoundError: Task not found
            DatabaseError: Database operation failed

        Example:
            >>> task = await service.get_task("abc-123")
            >>> print(task.title)
        """
        try:
            async with self._get_session() as session:
                return await self._get_task_impl(session, task_id)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get task {task_id}")
            raise BaseGiljoError(message=str(e), context={"operation": "get_task", "task_id": task_id}) from e

    async def _get_task_impl(self, session: AsyncSession, task_id: str) -> Task:
        """Implementation of get_task with explicit session parameter.

        Returns:
            Task ORM model

        Raises:
            ValidationError: No tenant context
            ResourceNotFoundError: Task not found
        """
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available", context={"operation": "get_task", "task_id": task_id}
            )

        task = await self._repo.get_task_by_id(session, task_id, tenant_key)

        if not task:
            raise ResourceNotFoundError(
                message="Task not found", context={"task_id": task_id, "tenant_key": tenant_key}
            )

        return task

    async def list_deleted_tasks(self, product_id: str | None = None, tenant_key: str | None = None) -> list[Task]:
        """List soft-deleted (trashed) tasks for the recover dialog.

        Tenant-isolated; optionally scoped to a product.

        Raises:
            ValidationError: No tenant context
        """
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(
                    message="No tenant context available", context={"operation": "list_deleted_tasks"}
                )
            async with self._get_session(tenant_key) as session:
                return await self._repo.list_deleted_tasks(session, tenant_key, product_id)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to list deleted tasks")
            raise BaseGiljoError(message=str(e), context={"operation": "list_deleted_tasks"}) from e

    async def get_summary(self, product_id: str | None = None) -> dict[str, Any]:
        """Facade: delegates to TaskConversionService."""
        return await self._conversion.get_summary(product_id)
