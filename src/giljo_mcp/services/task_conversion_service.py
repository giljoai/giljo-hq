# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TaskConversionService - Task-to-project conversion and summary operations.

Extracted from TaskService as part of the god-object refactoring (Handover 0950).

Responsibilities:
- Converting tasks to projects
- Summary statistics aggregation
- Deletion permission checks

Design Principles:
- Single Responsibility: Only conversion and summary domain logic
- Dependency Injection: Accepts DatabaseManager and TenantManager
- Async/Await: Full SQLAlchemy 2.0 async support
- Error Handling: Consistent exception handling and logging

Return Type Conventions (0731c):
- Conversion operations return ConversionResult
- Summary operations return dict (complex nested structure)
- Permission helpers return bool
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import (
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Project, Task
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.repositories.task_repository import TaskRepository
from giljo_mcp.schemas.service_responses import ConversionResult
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class TaskConversionService:
    """
    Service for task conversion and summary operations.

    Handles:
    - Converting tasks to projects
    - Task summary statistics
    - Task deletion permission checks

    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    def __init__(
        self,
        db_manager: DatabaseManager = None,
        tenant_manager: TenantManager = None,
        session: AsyncSession | None = None,
    ):
        """
        Initialize TaskConversionService with database and tenant management.

        Args:
            db_manager: Database manager for async database operations
            tenant_manager: Tenant manager for multi-tenancy support
            session: Optional AsyncSession for test transaction isolation (Handover 0324)
        """
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._session = session  # Store for test transaction isolation
        self._repo = TaskRepository()
        self._project_repo = ProjectRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._session
        )

    async def convert_to_project(
        self, task_id: str, project_name: str | None, strategy: str, include_subtasks: bool, user_id: str
    ) -> ConversionResult:
        """Convert task to project with optional subtask handling.

        This is a complex multi-entity operation involving:
        - Task retrieval
        - Product lookup
        - Project creation via ProjectService
        - Subtask conversion (if include_subtasks=True)
        - Task deletion/archival

        Args:
            task_id: Task UUID to convert
            project_name: Optional custom project name (defaults to task title)
            strategy: Conversion strategy ("create_new", "merge", etc.)
            include_subtasks: Whether to include child tasks
            user_id: User performing conversion

        Returns:
            ConversionResult with task_id, project_id, project_name, and the
            bound product (product_id + product_name, BE-9415) (0731c typed return)

        Raises:
            ValidationError: No tenant context, already converted, or the task's
                own product does not resolve for this tenant (BE-9415)
            ResourceNotFoundError: Task or user not found
            AuthorizationError: User not authorized
            DatabaseError: Database operation failed

        Example:
            >>> result = await service.convert_to_project(
            ...     task_id="abc-123",
            ...     project_name="New Project",
            ...     strategy="create_new",
            ...     include_subtasks=True,
            ...     user_id=user.id
            ... )
            >>> print(result.project_id)
        """
        try:
            async with self._get_session(self.tenant_manager.get_current_tenant()) as session:
                return await self._convert_to_project_impl(
                    session, task_id, project_name, strategy, include_subtasks, user_id
                )
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to convert task {task_id} to project")
            raise BaseGiljoError(message=str(e), context={"operation": "convert_to_project", "task_id": task_id}) from e

    async def _convert_to_project_impl(
        self,
        session: AsyncSession,
        task_id: str,
        project_name: str | None,
        strategy: str,
        include_subtasks: bool,
        user_id: str,
    ) -> ConversionResult:
        """Implementation of convert_to_project with explicit session parameter.

        Returns:
            ConversionResult with task_id, project_id, and project_name

        Raises:
            ValidationError: No tenant context, already converted, or the task's
                own product does not resolve for this tenant (BE-9415)
            ResourceNotFoundError: Task or user not found
            AuthorizationError: User not authorized
        """
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available", context={"operation": "convert_to_project", "task_id": task_id}
            )

        # Get task
        task = await self._repo.get_task_by_id(session, task_id, tenant_key)

        if not task:
            raise ResourceNotFoundError(
                message="Task not found", context={"task_id": task_id, "tenant_key": tenant_key}
            )

        # Check if already converted
        if task.converted_to_project_id:
            raise ValidationError(
                message=f"Task already converted to project {task.converted_to_project_id}",
                context={"task_id": task_id, "converted_to_project_id": task.converted_to_project_id},
            )

        # Get user for permission check
        user = await self._repo.get_user_by_id(session, tenant_key, user_id)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        # Permission check (only creator or admin can convert)
        if user.role != "admin" and task.created_by_user_id != user.id:
            raise AuthorizationError(
                message="Not authorized to convert this task. Only task creator or admin can convert.",
                context={"task_id": task_id, "user_id": user_id},
            )

        # BE-9415: the promoted project binds to the TASK's OWN product, never to
        # whichever product happens to be active. The active product is mutable
        # shared state -- another session, or the operator switching products in
        # the dashboard, changes it under a running conversion -- so resolving it
        # here filed the project wherever the server pointed at that instant.
        # ``tasks.product_id`` is NOT NULL (Handover 0433), so the task always
        # names exactly one product and no fallback is needed or wanted.
        #
        # Deliberately NOT copying the ``is_active`` check that the sibling
        # caller of this lookup applies (``task_service/_mutation_mixin`` on
        # create): binding to a product other than the active one is the entire
        # point here, so requiring active would reinstate this defect.
        bound_product = await self._repo.get_product_by_id(session, task.product_id, tenant_key)

        if not bound_product:
            # Mirrors BE-9411's contract: name the id, say nothing was created,
            # and NEVER fall back to the active product -- a silent fallback
            # would recreate the misfile while reporting success.
            raise ValidationError(
                message=(
                    f"Product '{task.product_id}' for this task was not found for your account, so "
                    "nothing was created. The task's product may have been deleted; restore it, or "
                    "move the task to a product you own before converting it."
                ),
                context={
                    "operation": "convert_to_project",
                    "task_id": task_id,
                    "product_id": task.product_id,
                    "tenant_key": tenant_key,
                },
            )

        # NOTE: The new project is created INACTIVE (see below), so promoting a
        # task must NOT touch any of the product's currently-active project(s).
        # BE-9525b (ruling 5 amended) dropped the one-active-project-per-product
        # limit, so this is no longer index-enforced either way -- it is simply
        # that conversion never activates anything. Only the user
        # activates/deactivates a project — conversion never does.

        # IMP-6262: a converted project is born UNTYPED. TSK is task-exclusive —
        # copying the task's TSK type onto the project would mint a TSK-typed
        # project and reopen the task/project alias ambiguity this harmonization
        # closes. Keep the task's title + serial as the project's identity (the
        # task row is hard-deleted below, freeing that product-wide-unique
        # number); the user re-tags the project's taxonomy later in the dashboard.
        # A serial-less task still needs a unique number under the (tenant,
        # product, NULL-type) bucket so the project satisfies
        # ``uq_project_taxonomy_active`` (NULLS NOT DISTINCT).
        project_type_id: str | None = None
        project_series_number: int | None = task.series_number
        if project_series_number is None:
            await self._project_repo.lock_rows_for_series_shared(session, tenant_key, bound_product.id)
            project_series_number = await self._project_repo.get_next_series_number_shared(
                session, tenant_key, bound_product.id
            )

        # Create project
        final_project_name = project_name or task.title
        new_project = Project(
            name=final_project_name,
            description=task.description or f"Project created from task: {task.title}",
            mission="",  # Leave empty - orchestrator will generate mission during staging
            product_id=bound_product.id,
            tenant_key=tenant_key,
            status=ProjectStatus.INACTIVE,  # Projects start inactive, user activates when ready
            project_type_id=project_type_id,
            series_number=project_series_number,
        )

        await self._repo.add_project(session, new_project)
        await self._repo.flush(session)  # Get project ID without committing

        # Mark task as converted (FK only; row is deleted at end of this flow)
        task.converted_to_project_id = new_project.id

        # Handle subtasks if requested
        if include_subtasks:
            # TENANT ISOLATION: Filter subtasks by tenant_key
            subtasks = await self._repo.get_subtasks(session, task_id, tenant_key)

            for subtask in subtasks:
                subtask.project_id = new_project.id

        # FE-6022c: re-point any roadmap item from this task to the new project
        # IN PLACE *before* the task row is hard-deleted — otherwise the
        # roadmap_items.task_id ON DELETE CASCADE (ce_0047) would silently drop
        # the item. Same priority/position; conversion never reorders.
        from giljo_mcp.services.roadmap_service import RoadmapService

        roadmap_service = RoadmapService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            session=session,
        )
        await roadmap_service.repoint_item_task_to_project(
            session,
            tenant_key=tenant_key,
            task_id=str(task_id),
            new_project_id=str(new_project.id),
        )

        # Delete the task after successful conversion
        await self._repo.delete_task(session, task)
        self._logger.info(
            f"Deleted task {sanitize(task_id)} after successful conversion to project {sanitize(new_project.id)}"
        )

        # BE-6086: repository flushes; this conversion scope is the session
        # owner and commits the WHOLE conversion (project insert + task delete +
        # roadmap re-point) atomically on clean scope exit. A failure anywhere
        # above rolls the entire unit back -- no half-converted state.
        await self._repo.flush(session)
        await self._repo.refresh(session, new_project)

        self._logger.info(
            f"Converted task {sanitize(task_id)} to project {sanitize(new_project.id)} (strategy: {sanitize(strategy)})"
        )

        return ConversionResult(
            task_id=str(task_id),
            project_id=str(new_project.id),
            project_name=new_project.name,
            # BE-9382: the refresh above loaded the ``taxonomy_alias``
            # column_property (deferred=False), so the promoted project's rendered
            # serial comes straight from the DB expression the dashboard reads.
            project_taxonomy_alias=new_project.taxonomy_alias or "",
            # BE-9415: echo the binding so the caller can see WHERE the promotion
            # landed without a second read.
            product_id=bound_product.id,
            product_name=bound_product.name,
        )

    # ============================================================================
    # Summary Statistics
    # ============================================================================

    async def get_summary(self, product_id: str | None = None) -> dict[str, Any]:
        """Get task summary statistics.

        Returns counts grouped by status, optionally filtered by product.

        Args:
            product_id: Optional product filter

        Returns:
            Summary data dictionary with:
            - summary: dict of product_id -> stats (total, by status, by priority)
            - total_products: count of products with tasks
            - total_tasks: total number of tasks

        Raises:
            ValidationError: No tenant context
            DatabaseError: Database operation failed

        Example:
            >>> summary = await service.get_summary()
            >>> print(summary["total_tasks"])
        """
        try:
            async with self._get_session(self.tenant_manager.get_current_tenant()) as session:
                return await self._get_summary_impl(session, product_id)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get task summary")
            raise BaseGiljoError(message=str(e), context={"operation": "get_summary"}) from e

    async def _get_summary_impl(self, session: AsyncSession, product_id: str | None = None) -> dict[str, Any]:
        """Implementation of get_summary with explicit session parameter.

        Returns:
            Summary data dictionary with task statistics

        Raises:
            ValidationError: No tenant context
        """
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={"operation": "get_summary"})

        # Build base query (BE-6130b: exclude trashed tasks from the summary counts)
        base_query = select(Task).where(Task.tenant_key == tenant_key, Task.deleted_at.is_(None))
        if product_id:
            base_query = base_query.where(Task.product_id == product_id)

        tasks = await self._repo.list_tasks(session, base_query)

        # Aggregate by product
        summary = {}
        for task in tasks:
            pid = task.product_id or "no-product"
            if pid not in summary:
                summary[pid] = {
                    "total": 0,
                    "pending": 0,
                    "in_progress": 0,
                    "completed": 0,
                    "blocked": 0,
                    "cancelled": 0,
                    "by_priority": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                }

            s = summary[pid]
            s["total"] += 1

            # Count by status
            status = task.status or "pending"
            if status in s:
                s[status] += 1

            # Count by priority
            priority = task.priority or "medium"
            if priority in s["by_priority"]:
                s["by_priority"][priority] += 1

        return {"summary": summary, "total_products": len(summary), "total_tasks": len(tasks)}

    # ============================================================================
    # Permission Helpers (Handover 0322 Phase 3)
    # ============================================================================

    def can_delete_task(self, task: Task, user) -> bool:
        """
        Check if user can delete task.

        Rules:
        - Admin: can delete any task in tenant
        - Developer: can delete own tasks
        - Viewer: cannot delete

        Args:
            task: Task to check
            user: User attempting deletion

        Returns:
            True if user can delete task, False otherwise

        Example:
            >>> if service.can_delete_task(task, current_user):
            ...     # Allow deletion
        """

        # Admin can delete any task in their tenant
        if user.role == "admin":
            return task.tenant_key == user.tenant_key

        # Developer can delete tasks they created
        return task.tenant_key == user.tenant_key and task.created_by_user_id == user.id
