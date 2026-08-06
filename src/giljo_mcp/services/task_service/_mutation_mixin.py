# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Task write-path (core CRUD) mixin for TaskService (BE-9073 item 2 split).

Holds create / update / delete / restore plus the purge facade, mirroring the
``project_service`` package precedent (``MutationMixin``). The status-change /
conversion / completion-notes lifecycle methods live in the sibling
``_lifecycle_mixin`` (split further to keep both files under the 800-line
cap -- see that module's docstring). Composed into ``TaskService``; references
``self.*`` / ``self._*`` only. Behavior is byte-identical to the pre-split
single-file class -- methods moved verbatim.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.domain.soft_delete import RECOVER_WINDOW_DAYS, recover_window_expired
from giljo_mcp.exceptions import (
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Task
from giljo_mcp.schemas.service_responses import TaskUpdateResult
from giljo_mcp.utils.log_sanitizer import sanitize


# Field allowlist for task updates — only these fields may be set via
# update_task().  Replaces the previous hasattr() gate which allowed setting
# any model attribute including id, tenant_key, created_at, etc.
_ALLOWED_TASK_UPDATE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        # BE-6049c: ``task_type_id`` is intentionally EXCLUDED — tasks are
        # TSK-only and the tag is immutable. Attempts to rebind it via
        # update_task are rejected by the allowlist (logged + dropped).
        "status",
        "priority",
        "estimated_effort",
        "actual_effort",
        "due_date",
        "project_id",
        "parent_task_id",
        "converted_to_project_id",
        # FE-5046: UI declutter flag, mirrors Project.hidden write path.
        "hidden",
    }
)


class _TaskMutationMixin:
    """Task core CRUD methods (create/update/delete/restore/purge). Composed into TaskService."""

    async def log_task(
        self,
        content: str,
        task_type_id: str | None = None,
        priority: str = "medium",
        project_id: str | None = None,
        product_id: str | None = None,
        tenant_key: str | None = None,
        title: str | None = None,
        description: str | None = None,
        series_number: int | None = None,
        assign_shared_series: bool = False,
        _assigned_series_out: list[int | None] | None = None,
        *,
        status: str = "pending",
        parent_task_id: str | None = None,
        created_by_user_id: str | None = None,
        estimated_effort: float | None = None,
        actual_effort: float | None = None,
        due_date: Any = None,
        validate_product: bool = False,
    ) -> str:
        """Quick task capture - logs a task with minimal information.

        Args:
            content: Task content (used as fallback for title and description)
            task_type_id: Optional taxonomy_types FK (resolved upstream from abbreviation)
            priority: Task priority (default: "medium")
            project_id: Optional project ID to attach task to
            product_id: Required product ID (task must belong to a product)
            tenant_key: Required tenant key for multi-tenant isolation
            title: Optional explicit title (overrides content for Task.title)
            description: Optional explicit description (overrides content for Task.description)

        Returns:
            Task ID of created task

        Raises:
            ValidationError: Missing required parameters (product_id, tenant_key)
            ResourceNotFoundError: Project not found
            DatabaseError: Database operation failed

        Example:
            >>> task_id = await service.log_task(
            ...     content="Fix authentication bug",
            ...     task_type_id="abc-123",
            ...     priority="high",
            ...     product_id="prod-123",
            ...     tenant_key="tenant-abc"
            ... )
            >>> print(task_id)
        """
        try:
            async with self._get_session(tenant_key) as session:
                return await self._log_task_impl(
                    session,
                    content,
                    task_type_id,
                    priority,
                    project_id,
                    product_id,
                    tenant_key,
                    title=title,
                    description=description,
                    series_number=series_number,
                    assign_shared_series=assign_shared_series,
                    assigned_series_out=_assigned_series_out,
                    status=status,
                    parent_task_id=parent_task_id,
                    created_by_user_id=created_by_user_id,
                    estimated_effort=estimated_effort,
                    actual_effort=actual_effort,
                    due_date=due_date,
                    validate_product=validate_product,
                )
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to log task")
            raise BaseGiljoError(message=str(e), context={"operation": "log_task"}) from e

    async def _log_task_impl(
        self,
        session: AsyncSession,
        content: str,
        task_type_id: str | None,
        priority: str,
        project_id: str | None,
        product_id: str | None,
        tenant_key: str | None,
        title: str | None = None,
        description: str | None = None,
        series_number: int | None = None,
        assign_shared_series: bool = False,
        assigned_series_out: list[int | None] | None = None,
        status: str = "pending",
        parent_task_id: str | None = None,
        created_by_user_id: str | None = None,
        estimated_effort: float | None = None,
        actual_effort: float | None = None,
        due_date: Any = None,
        validate_product: bool = False,
    ) -> str:
        """Implementation of log_task with explicit session parameter.

        Args:
            session: Database session
            content: Task content (used as fallback for title and description)
            task_type_id: Optional taxonomy_types FK (resolved upstream from abbreviation)
            priority: Task priority
            project_id: Optional project ID
            product_id: Required product ID
            tenant_key: Required tenant key
            title: Optional explicit title (overrides content for Task.title)
            description: Optional explicit description (overrides content for Task.description)

        Returns:
            Task ID of created task

        Raises:
            ValidationError: Missing tenant_key or product_id
            ResourceNotFoundError: Project not found
        """
        # Use provided tenant_key or get from context
        if not tenant_key:
            tenant_key = self.tenant_manager.get_current_tenant()

        # Validate required parameters (Handover 0433 Phase 2)
        if not tenant_key:
            raise ValidationError(
                message="tenant_key is required for task creation",
                context={"operation": "log_task"},
            )

        if not product_id:
            raise ValidationError(
                message="product_id is required for task creation",
                context={"operation": "log_task"},
            )

        # BE-3006a single-writer rule: the REST task-create path used to validate
        # the product (exists, tenant-owned, not soft-deleted, active) inline and
        # then raw-write the row. That half now lives here so BOTH halves of the
        # formerly-diverged validation (product-active AND project-belonging) are
        # enforced in the owning service. Opt-in (the MCP path already resolves
        # the active product, so it does not re-validate).
        if validate_product:
            product = await self._repo.get_product_by_id(session, product_id, tenant_key)
            if not product:
                raise ResourceNotFoundError(
                    message="Product not found or does not belong to your tenant.",
                    context={"product_id": product_id, "tenant_key": tenant_key},
                )
            if not product.is_active:
                raise ValidationError(
                    message="No active product set. Please activate a product before creating tasks.",
                    context={"product_id": product_id, "operation": "log_task"},
                )

        project = None

        # Get project if specified
        if project_id:
            # Always filter by both tenant_key AND product_id for security
            project = await self._repo.get_project_by_id(session, project_id, product_id, tenant_key)

            # If project_id was provided but project not found, fail immediately
            if not project:
                raise ResourceNotFoundError(
                    message=f"Project {project_id} not found or access denied",
                    context={"project_id": project_id, "product_id": product_id, "tenant_key": tenant_key},
                )

        # SEC-9171 (#15): a parent-task reference must belong to the caller's
        # tenant — mirrors the project_id belonging check above. Without it a
        # tenant-A row could persist a cross-tenant FK to a tenant-B task.
        if parent_task_id:
            parent = await self._repo.get_task_by_id(session, parent_task_id, tenant_key)
            if not parent:
                raise ResourceNotFoundError(
                    message=f"Parent task {parent_task_id} not found or access denied",
                    context={"parent_task_id": parent_task_id, "tenant_key": tenant_key},
                )

        # Use title/description if provided, fall back to content for backwards compat
        task_title = title or content
        task_description = description or content

        # BE-6049b: assign the global shared task+project series_number inside this
        # tx so the FOR UPDATE lock + advisory lock held by lock_rows_for_series_shared
        # persist until the new task row is committed. The counter is ONE sequence per
        # (tenant_key, product_id) across every tag — not per-type.
        if assign_shared_series and task_type_id is not None and series_number is None:
            from giljo_mcp.repositories.project_repository import ProjectRepository

            project_repo = ProjectRepository()
            await project_repo.lock_rows_for_series_shared(session, tenant_key, product_id)
            # BE-6079: the >9999 exhaustion cap (decision D) now lives in the
            # allocator (get_next_series_number_shared) — one gate for every
            # auto-assign path, so no inline cap is needed here.
            series_number = await project_repo.get_next_series_number_shared(session, tenant_key, product_id)
        if assigned_series_out is not None:
            assigned_series_out[0] = series_number

        # Create task
        task = Task(
            tenant_key=tenant_key,
            product_id=product_id,
            project_id=str(project.id) if project else None,
            parent_task_id=parent_task_id,
            title=task_title,
            description=task_description,
            task_type_id=task_type_id,
            series_number=series_number,
            priority=priority,
            status=status,
            estimated_effort=estimated_effort,
            actual_effort=actual_effort,
            due_date=due_date,
            created_by_user_id=created_by_user_id,
        )

        await self._repo.add_and_flush(session, task)

        task_id = str(task.id)

        if project:
            self._logger.info(f"Logged task {task_id} in project {project.id}")
        else:
            self._logger.info(f"Logged task {sanitize(task_id)} for product {sanitize(product_id)}")

        return task_id

    async def create_task(
        self,
        title: str,
        description: str,
        priority: str = "medium",
        assigned_to: str | None = None,
        project_id: str | None = None,
        product_id: str | None = None,
        tenant_key: str | None = None,
        task_type_id: str | None = None,
    ) -> str:
        """
        Create a new task with full details.

        Delegates to log_task with separate title and description parameters
        so that both are preserved independently on the Task model.

        Args:
            title: Task title/summary
            description: Detailed task description
            priority: Task priority (default: "medium")
            assigned_to: Optional agent name to assign to (not implemented yet)
            project_id: Optional project ID
            product_id: Required product ID (task must belong to a product)
            tenant_key: Required tenant key for multi-tenant isolation

        Returns:
            Task ID string (delegated from log_task)

        Example:
            >>> task_id = await service.create_task(
            ...     title="Implement feature X",
            ...     description="Add new feature X with unit tests",
            ...     priority="high",
            ...     product_id="prod-123",
            ...     tenant_key="tenant-abc"
            ... )
        """
        return await self.log_task(
            content=title,
            title=title,
            description=description,
            priority=priority,
            project_id=project_id,
            product_id=product_id,
            tenant_key=tenant_key,
            task_type_id=task_type_id,
        )

    async def create_task_for_rest(
        self,
        *,
        title: str,
        description: str | None,
        product_id: str,
        tenant_key: str,
        created_by_user_id: str | None = None,
        project_id: str | None = None,
        parent_task_id: str | None = None,
        status: str = "pending",
        priority: str = "medium",
        estimated_effort: float | None = None,
        actual_effort: float | None = None,
        due_date: Any = None,
    ) -> Task:
        """Create a task from the REST dashboard, routed through the owning service.

        BE-3006a single-writer rule: the REST ``POST /tasks`` endpoint used to
        raw-write the Task row (``db.add`` + ``db.commit``). That write now lives
        here. This method enforces BOTH halves of the formerly-diverged
        validation — the product exists, is tenant-owned, is not soft-deleted and
        is active (``validate_product=True``) AND the ``project_id`` belongs to
        the product/tenant (inside ``log_task``) — forces the reserved ``TSK`` tag
        (tasks are TSK-only, matching ``create_task_for_mcp`` and the prior
        endpoint), assigns the shared global serial, then returns the persisted
        ``Task`` (eager-loaded ``task_type``) for the response.

        Args:
            title: Task title (also used as content fallback).
            description: Task description.
            product_id: Product the task belongs to (validated, required).
            tenant_key: Tenant key for isolation (resolve-or-raise; no silent default).
            created_by_user_id: Creator user id (task owner).
            project_id: Optional project to attach to (validated for belonging).
            parent_task_id: Optional parent task.
            status: Initial status (default "pending").
            priority: Task priority (default "medium").
            estimated_effort / actual_effort / due_date: Optional task metadata.

        Returns:
            The persisted ``Task`` ORM model.

        Raises:
            ValidationError: tenant missing, or product not active.
            ResourceNotFoundError: product or project not found / access denied.
        """
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not effective_tenant_key:
            raise ValidationError(
                message="tenant_key is required for task creation",
                context={"operation": "create_task_for_rest"},
            )

        # Tasks are TSK-only: force the reserved tag (race-safe ensure), exactly
        # as create_task_for_mcp and the prior REST endpoint did.
        from giljo_mcp.services.taxonomy_service import TaxonomyService

        taxonomy = TaxonomyService(db_manager=self.db_manager, session=self._session)
        reserved_type = await taxonomy.ensure_reserved_task_type(effective_tenant_key)
        task_type_id = reserved_type.id

        task_id = await self.log_task(
            content=title,
            title=title,
            description=description,
            task_type_id=task_type_id,
            priority=priority,
            project_id=project_id,
            product_id=product_id,
            tenant_key=effective_tenant_key,
            assign_shared_series=True,
            status=status,
            parent_task_id=parent_task_id,
            created_by_user_id=created_by_user_id,
            estimated_effort=estimated_effort,
            actual_effort=actual_effort,
            due_date=due_date,
            validate_product=True,
        )

        async with self._get_session(effective_tenant_key) as session:
            task = await self._repo.get_task_by_id(session, task_id, effective_tenant_key)
        if task is None:
            raise ResourceNotFoundError(
                message="Task not found after creation",
                context={"task_id": task_id, "tenant_key": effective_tenant_key},
            )

        # FE-9274: the REST create path had NO broadcast at all (unlike its MCP
        # twin create_task_for_mcp, which emits task:created) -- a task created
        # from the dashboard never appeared for other connected tabs without a
        # manual refresh. log_task above already committed durably, so this is
        # post-commit.
        ws = self._websocket_manager
        if ws:
            try:
                await ws.broadcast_to_tenant(
                    tenant_key=effective_tenant_key,
                    event_type="task:created",
                    data={"task_id": task_id, "title": title, "product_id": product_id},
                )
            except (RuntimeError, ValueError, OSError) as ws_error:
                self._logger.warning(f"Failed to broadcast task:created event: {ws_error}")

        return task

    # ============================================================================
    # Task Updates
    # ============================================================================

    async def update_task(self, task_id: str, **kwargs) -> TaskUpdateResult:
        """Update a task with arbitrary fields.

        Automatically handles timestamp updates based on status changes:
        - status -> "in_progress": Sets started_at if not already set
        - status -> "completed" or "cancelled": Sets completed_at if not already set

        Args:
            task_id: Task UUID (required)
            **kwargs: Field names and values to update

        Returns:
            TaskUpdateResult with task_id and list of updated field names

        Raises:
            ResourceNotFoundError: Task not found
            DatabaseError: Database operation failed

        Example:
            >>> result = await service.update_task(
            ...     task_id="abc-123",
            ...     status="in_progress",
            ...     priority="high"
            ... )
            >>> print(result.updated_fields)
        """
        try:
            async with self._get_session() as session:
                return await self._update_task_impl(session, task_id, **kwargs)

        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to update task")
            raise BaseGiljoError(message=str(e), context={"operation": "update_task", "task_id": task_id}) from e

    async def _update_task_impl(self, session: AsyncSession, task_id: str, **kwargs) -> TaskUpdateResult:
        """Implementation of update_task with explicit session parameter.

        Returns:
            TaskUpdateResult with task_id and list of updated field names

        Raises:
            ResourceNotFoundError: Task not found or access denied
            ValidationError: No tenant context available
        """
        # TENANT ISOLATION: Require tenant_key for all task updates
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available",
                context={"operation": "update_task", "task_id": task_id},
            )

        task = await self._repo.get_task_by_id(session, task_id, tenant_key)

        if not task:
            raise ResourceNotFoundError(
                message="Task not found or access denied",
                context={"task_id": task_id, "tenant_key": tenant_key},
            )

        # SEC-9171 (#15): re-validate cross-entity FK refs against the tenant
        # BEFORE applying them — the allowlist gates field NAMES, not row
        # OWNERSHIP, so a tenant-B UUID would otherwise land via setattr.
        new_parent_id = kwargs.get("parent_task_id")
        if new_parent_id and not await self._repo.get_task_by_id(session, new_parent_id, tenant_key):
            raise ResourceNotFoundError(
                message=f"Parent task {new_parent_id} not found or access denied",
                context={"parent_task_id": new_parent_id, "tenant_key": tenant_key},
            )
        new_project_id = kwargs.get("project_id")
        if new_project_id and not await self._repo.get_project_by_id(
            session, new_project_id, task.product_id, tenant_key
        ):
            raise ResourceNotFoundError(
                message=f"Project {new_project_id} not found or access denied",
                context={"project_id": new_project_id, "tenant_key": tenant_key},
            )

        # Update fields (allowlist-gated — see _ALLOWED_TASK_UPDATE_FIELDS)
        updated_fields = []
        for key, value in kwargs.items():
            if key in _ALLOWED_TASK_UPDATE_FIELDS:
                setattr(task, key, value)
                updated_fields.append(key)
            else:
                self._logger.warning(
                    f"Rejected update to disallowed field '{sanitize(key)}' on task {sanitize(task_id)}"
                )

        # Auto-update timestamps based on status changes (Handover 0324)
        if "status" in kwargs:
            new_status = kwargs["status"]
            now = datetime.now(UTC)

            if new_status == "in_progress" and not task.started_at:
                task.started_at = now
                updated_fields.append("started_at")
                self._logger.debug(f"Auto-set started_at for task {sanitize(task_id)}")

            elif new_status in ("completed", "cancelled") and not task.completed_at:
                task.completed_at = now
                updated_fields.append("completed_at")
                self._logger.debug(f"Auto-set completed_at for task {sanitize(task_id)}")

        # BE-6086: the repository now flushes; this entry point is the session
        # owner, so it commits EXPLICITLY here (Shape B) -- the task:updated
        # broadcast below MUST fire only after the write is durable, never
        # before, or a failed commit would leave phantom dashboard state.
        await session.commit()

        self._logger.info(f"Updated task {sanitize(task_id)}: {sanitize(updated_fields)}")

        # FE-5046: broadcast WS event so subscribed clients (FE task list)
        # see the change without a refresh. Non-critical: failures are logged
        # but never block the write path.
        ws = self._websocket_manager
        if ws and updated_fields:
            try:
                await ws.broadcast_to_tenant(
                    tenant_key=tenant_key,
                    event_type="task:updated",
                    data={
                        "task_id": task_id,
                        "updated_fields": list(updated_fields),
                        "hidden": bool(getattr(task, "hidden", False)),
                        "status": task.status,
                    },
                )
            except (RuntimeError, ValueError, OSError) as ws_error:
                self._logger.warning(f"Failed to broadcast task:updated event: {ws_error}")

        return TaskUpdateResult(task_id=task_id, updated_fields=updated_fields)

    async def delete_task(self, task_id: str, user_id: str) -> None:
        """Delete a task (with permission check).

        Only the task creator or an admin can delete tasks.
        This performs a soft delete (BE-6130b): it stamps ``deleted_at`` so the
        task drops out of live reads and frees its serial; ``restore_task``
        recovers it within the retention window.

        Args:
            task_id: Task UUID
            user_id: User performing deletion

        Returns:
            None on successful deletion

        Raises:
            ValidationError: No tenant context
            ResourceNotFoundError: Task or user not found
            AuthorizationError: User not authorized to delete task
            DatabaseError: Database operation failed

        Example:
            >>> await service.delete_task("abc-123", user.id)
        """
        try:
            async with self._get_session() as session:
                return await self._delete_task_impl(session, task_id, user_id)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to delete task {task_id}")
            raise BaseGiljoError(message=str(e), context={"operation": "delete_task", "task_id": task_id}) from e

    async def _delete_task_impl(self, session: AsyncSession, task_id: str, user_id: str) -> None:
        """Implementation of delete_task with explicit session parameter.

        Returns:
            None on successful deletion

        Raises:
            ValidationError: No tenant context
            ResourceNotFoundError: Task or user not found
            AuthorizationError: User not authorized to delete task
        """
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available", context={"operation": "delete_task", "task_id": task_id}
            )

        # Get task
        task = await self._repo.get_task_by_id(session, task_id, tenant_key)

        if not task:
            raise ResourceNotFoundError(
                message="Task not found", context={"task_id": task_id, "tenant_key": tenant_key}
            )

        # Get user for permission check
        user = await self._repo.get_user_by_id(session, tenant_key, user_id)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        # Permission check
        if not self._conversion.can_delete_task(task, user):
            raise AuthorizationError(
                message="Not authorized to delete this task. Only task creator or admin can delete.",
                context={"task_id": task_id, "user_id": user_id},
            )

        # BE-6130b: SOFT delete (trash). Stamp deleted_at so the task drops out
        # of every live read and frees its serial from the shared high-water mark;
        # restore_task recovers it within the retention window. (Was a hard delete.)
        task.deleted_at = datetime.now(UTC)
        await self._repo.flush(session)

        self._logger.info(f"Soft-deleted task {sanitize(task_id)} by user {sanitize(user_id)}")

    async def restore_task(self, task_id: str) -> Task:
        """Restore a soft-deleted (trashed) task.

        Re-mints a FRESH shared serial (the trashed task freed its old number,
        which may already have been reused — Project decision C / BE-6049b parity)
        and clears ``deleted_at``. Routes through the owning service + repository;
        tenant-isolated.

        Raises:
            ValidationError: No tenant context
            ResourceNotFoundError: No trashed task matched the id for the tenant
        """
        try:
            async with self._get_session() as session:
                return await self._restore_task_impl(session, task_id)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to restore task {task_id}")
            raise BaseGiljoError(message=str(e), context={"operation": "restore_task", "task_id": task_id}) from e

    async def _restore_task_impl(self, session: AsyncSession, task_id: str) -> Task:
        """Implementation of restore_task with explicit session parameter."""
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available", context={"operation": "restore_task", "task_id": task_id}
            )

        task = await self._repo.get_deleted_task_by_id(session, task_id, tenant_key)
        if not task:
            raise ResourceNotFoundError(
                message="Deleted task not found", context={"task_id": task_id, "tenant_key": tenant_key}
            )

        # BE-6130b decision A: recovery is gated by the 30-day window at this boundary.
        if recover_window_expired(task.deleted_at):
            raise ValidationError(
                message=(
                    f"This task was deleted more than {RECOVER_WINDOW_DAYS} days ago and can no longer be recovered."
                ),
                context={"task_id": task_id, "tenant_key": tenant_key},
            )

        # Re-mint a fresh shared serial only for typed (numbered) tasks; the old
        # number was freed on delete and may have been reused. Untyped/legacy
        # tasks (series_number IS NULL) keep their NULL — nothing to re-mint.
        if task.series_number is not None and task.product_id:
            from giljo_mcp.repositories.project_repository import ProjectRepository

            project_repo = ProjectRepository()
            await project_repo.lock_rows_for_series_shared(session, tenant_key, task.product_id)
            task.series_number = await project_repo.get_next_series_number_shared(session, tenant_key, task.product_id)

        task.deleted_at = None
        await self._repo.flush_and_refresh(session, task)
        self._logger.info(f"Restored task {sanitize(task_id)}")
        return task

    async def purge_expired_deleted_tasks(self, tenant_key: str | None = None) -> int:
        """Hard-delete trashed tasks past the recovery window (TSK-6132 reaper).

        Walks this tenant's soft-deleted tasks and permanently removes those whose
        ``deleted_at`` is past ``RECOVER_WINDOW_DAYS`` (the same boundary
        ``restore_task`` refuses to recover past). Child subtasks are re-parented
        to NULL in the repository to keep the delete FK-safe. Returns the count
        purged; tenant-isolated and idempotent (re-running finds none).
        """
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not effective_tenant_key:
            raise ValidationError(
                message="No tenant context available", context={"operation": "purge_expired_deleted_tasks"}
            )
        purged = 0
        async with self._get_session(effective_tenant_key) as session:
            for task in await self._repo.list_deleted_tasks(session, effective_tenant_key):
                if not recover_window_expired(task.deleted_at):
                    continue
                try:
                    if await self._repo.hard_delete_task(session, effective_tenant_key, task.id):
                        purged += 1
                except Exception:
                    self._logger.exception("Reaper failed to purge task %s", task.id)
        return purged
