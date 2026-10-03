# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.endpoints._boundary_types import ID_MAX, IdPath, IdQuery
from api.endpoints.dependencies import get_task_service
from api.endpoints.mcp_tools._base import CONSTRAINT_INVALID_CHOICE, validation_rejection
from api.schemas.task import (
    ProjectConversionResponse,
    StatusUpdate,
    TaskConversionRequest,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Task, User
from giljo_mcp.services.handover_validation import HANDOVER_CONTENT_CONSTRAINT, HANDOVER_SHAPE_CONSTRAINT
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

_ARGUMENT_CONSTRAINTS = frozenset({HANDOVER_SHAPE_CONSTRAINT, HANDOVER_CONTENT_CONSTRAINT})

router = APIRouter()




def can_delete_task(task: Task, user: User) -> bool:
    if user.role == "admin":
        return task.tenant_key == user.tenant_key

    return task.tenant_key == user.tenant_key and task.created_by_user_id == user.id


def _argument_rejection(exc: ValidationError) -> HTTPException | None:
    context = exc.context or {}
    constraint = context.get("constraint")
    if constraint in _ARGUMENT_CONSTRAINTS:
        field = context["field"]
    elif context.get("field") == "task_type":
        field, constraint = "task_type", CONSTRAINT_INVALID_CHOICE
    else:
        return None
    rejection = validation_rejection(field=field, constraint=constraint, message=exc.message)
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "error_code": rejection["error"],
            "message": rejection["message"],
            "field": rejection["field"],
            "constraint": rejection["constraint"],
        },
    )


def task_to_response(task: Task) -> TaskResponse:
    task_type_abbr = task.task_type.abbreviation if task.task_type else None
    task_type_color = task.task_type.color if task.task_type else None
    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        task_type=task_type_abbr,
        task_type_id=task.task_type_id,
        task_type_color=task_type_color,
        series_number=task.series_number,
        subseries=task.subseries,
        taxonomy_alias=task.taxonomy_alias or None,
        hidden=bool(task.hidden),
        status=task.status,
        priority=task.priority,
        product_id=task.product_id,
        project_id=task.project_id,
        parent_task_id=task.parent_task_id,
        created_by_user_id=task.created_by_user_id,
        converted_to_project_id=task.converted_to_project_id,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        estimated_effort=task.estimated_effort,
        actual_effort=task.actual_effort,
        deleted_at=task.deleted_at,
    )




@router.get("/", response_model=list[TaskResponse])
async def list_tasks(
    filter_type: str | None = Query(None, max_length=ID_MAX, description="Filter: 'product_tasks' | 'all_tasks'"),
    created_by_me: bool | None = Query(None, description="Only tasks I created"),
    status: str | None = Query(None, max_length=ID_MAX, description="Filter by status"),
    priority: str | None = Query(None, max_length=ID_MAX, description="Filter by priority"),
    project_id: IdQuery = None,
    product_id: IdQuery = None,
    limit: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description="Opt-in page size (mirrors /jobs). When omitted the endpoint returns the full set.",
    ),
    offset: int | None = Query(
        default=None,
        ge=0,
        description="Opt-in row offset for pagination (pairs with limit).",
    ),
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
) -> list[TaskResponse]:
    """
    List tasks with product-scoped filtering.

    Filter types:
    - 'product_tasks': Tasks for active product only
    - 'all_tasks': Tasks with product_id = NULL

    Args:
        filter_type: Filter preset ('product_tasks' or 'all_tasks')
        created_by_me: Only tasks created by current user
        status: Filter by task status
        priority: Filter by task priority
        project_id: Filter by project
        product_id: Filter by product
        limit: Opt-in row cap (1-500); omitted returns the full set
        offset: Opt-in row offset over the newest-first ordering
        current_user: Current authenticated user
        task_service: Task service instance

    Returns:
        List of TaskResponse objects

    Raises:
        ValidationError: No tenant context
        DatabaseError: Database operation failed
    """
    logger.debug("User %s listing tasks (filter_type: %s)", sanitize(current_user.username), sanitize(str(filter_type)))

    created_by_user_id = str(current_user.id) if created_by_me else None

    result = await task_service.list_tasks(
        filter_type=filter_type,
        product_id=product_id,
        project_id=project_id,
        status=status,
        priority=priority,
        created_by_user_id=created_by_user_id,
        tenant_key=current_user.tenant_key,
        limit=limit,
        offset=offset,
    )

    logger.info("Found %d tasks for user %s", len(result), sanitize(current_user.username))

    return [task_to_response(task) for task in result]


@router.post("/", response_model=TaskResponse)
async def create_task(
    task_create: TaskCreate,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """
    Create a new task.

    The creator becomes the task owner. Product binding is required
    to ensure all tasks are isolated to a specific product.

    The row is written by ``TaskService.create_task_for_rest``, which validates
    that the product exists and is active and that project_id belongs to it.
    """
    logger.debug(
        "User %s creating task '%s'",
        sanitize(getattr(current_user, "username", "unknown")),
        sanitize(task_create.title),
    )

    try:
        task = await task_service.create_task_for_rest(
            title=task_create.title,
            description=task_create.description,
            product_id=task_create.product_id,
            tenant_key=current_user.tenant_key,
            created_by_user_id=current_user.id,
            project_id=task_create.project_id,
            parent_task_id=task_create.parent_task_id,
            status=task_create.status or "pending",
            priority=task_create.priority or "medium",
            estimated_effort=task_create.estimated_effort,
            actual_effort=task_create.actual_effort,
            task_type=task_create.task_type,
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message) from e
    except ValidationError as e:
        rejection = _argument_rejection(e)
        if rejection is not None:
            raise rejection from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message) from e

    logger.info("Created task %s by user %s", task.id, sanitize(current_user.username))
    return task_to_response(task)


@router.get("/summary")
@router.get("/summary/")
async def get_task_summary(
    product_id: IdQuery = None,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
):
    """
    Return simple task summary metrics grouped by product for the current tenant.
    Structure is compatible with UI store expectations.

    NOTE: Route must be defined BEFORE /{task_id}/ to avoid FastAPI matching
    "summary" as a task_id parameter (route ordering matters in FastAPI).

    Raises:
        ValidationError: No tenant context
        DatabaseError: Database operation failed
    """
    data = await task_service.get_summary(product_id=product_id)

    return {
        "success": True,
        "summary": data["summary"],
        "total_products": data["total_products"],
        "total_tasks": data["total_tasks"],
    }


@router.get("/deleted", response_model=list[TaskResponse])
@router.get("/deleted/", response_model=list[TaskResponse])
async def list_deleted_tasks(
    product_id: IdQuery = None,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
) -> list[TaskResponse]:
    """List soft-deleted (trashed) tasks for the recover dialog.

    Registered BEFORE ``/{task_id}/`` so the literal ``/deleted`` path is not
    matched as a task_id. Tenant-isolated; optionally scoped to a product.
    """
    result = await task_service.list_deleted_tasks(product_id=product_id, tenant_key=current_user.tenant_key)
    logger.info("Found %d deleted tasks for user %s", len(result), sanitize(current_user.username))
    return [task_to_response(task) for task in result]


@router.get("/{task_id}/", response_model=TaskResponse)
async def get_task(
    task_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """
    Get a single task by ID within the current tenant.

    Raises:
        ValidationError: No tenant context
        ResourceNotFoundError: Task not found
        DatabaseError: Database operation failed
    """
    task = await task_service.get_task(task_id)
    return task_to_response(task)


@router.patch("/{task_id}", response_model=TaskResponse)
@router.put("/{task_id}/", response_model=TaskResponse)
async def update_task(
    task_id: IdPath,
    task_update: TaskUpdate,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """
    Update a task.

    Only the task's creator or an admin of the same tenant can update it.

    Args:
        task_id: Task ID to update
        task_update: Fields to update
        current_user: Current authenticated user
        task_service: Task service instance

    Returns:
        Updated task data

    Raises:
        HTTPException: 403 if user lacks permission
        HTTPException: 404 if task not found
    """
    logger.debug("User %s updating task %s", sanitize(current_user.username), sanitize(task_id))

    task = await task_service.get_task(task_id)

    if current_user.role != "admin" and str(task.created_by_user_id) != str(current_user.id):
        logger.warning("User %s not authorized to update task %s", sanitize(current_user.username), sanitize(task_id))
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this task")

    update_data = task_update.dict(exclude_unset=True)
    completion_notes = update_data.pop("completion_notes", None)
    current_type_abbr = task.task_type.abbreviation if task.task_type else None
    if "task_type" in update_data and update_data["task_type"] == current_type_abbr:
        update_data.pop("task_type")
    if "task_type" in update_data:
        from api.app_state import state as _app_state
        from giljo_mcp.auth.dependencies import get_db_session  # noqa: F401  (typing only)
        from giljo_mcp.services.taxonomy_service import TaxonomyService

        taxonomy = TaxonomyService(db_manager=_app_state.db_manager)
        abbr = update_data.pop("task_type")
        if abbr:
            resolved = await taxonomy.validate(abbr, current_user.tenant_key)
            update_data["task_type_id"] = resolved.id
        else:
            update_data["task_type_id"] = None

    if "product_id" in update_data:
        if update_data["product_id"] == task.product_id:
            update_data.pop("product_id")
        else:
            raise ValidationError(
                message="A task's product is fixed at creation and cannot be reassigned.",
                context={
                    "task_id": task_id,
                    "current_product_id": task.product_id,
                    "requested_product_id": update_data["product_id"],
                },
            )

    try:
        await task_service.update_task(task_id, **update_data)
    except ValidationError as e:
        rejection = _argument_rejection(e)
        if rejection is None:
            raise
        raise rejection from e

    if completion_notes and update_data.get("status") == "completed":
        await task_service.append_completion_notes(task_id, completion_notes)

    logger.info("Updated task %s by user %s", sanitize(task_id), sanitize(current_user.username))

    task = await task_service.get_task(task_id)
    return task_to_response(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
@router.delete("/{task_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
):
    """
    Delete a task.

    Only the creator or admin can delete tasks.

    Args:
        task_id: Task ID to delete
        current_user: Current authenticated user
        task_service: Task service instance

    Raises:
        ValidationError: No tenant context
        ResourceNotFoundError: Task not found
        AuthorizationError: User not authorized to delete task
        DatabaseError: Database operation failed
    """
    logger.debug("User %s deleting task %s", sanitize(current_user.username), sanitize(task_id))

    await task_service.delete_task(task_id, str(current_user.id))

    logger.info("Deleted task %s by user %s", sanitize(task_id), sanitize(current_user.username))


@router.post("/{task_id}/restore", response_model=TaskResponse)
@router.post("/{task_id}/restore/", response_model=TaskResponse)
async def restore_task(
    task_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """Restore a soft-deleted (trashed) task.

    Re-mints a fresh serial (the trashed number may have been reused) and clears
    ``deleted_at``. Tenant-isolated.

    Raises:
        ResourceNotFoundError: No trashed task matched the id for the tenant
    """
    logger.debug("User %s restoring task %s", sanitize(current_user.username), sanitize(task_id))
    task = await task_service.restore_task(task_id)
    logger.info("Restored task %s by user %s", sanitize(task_id), sanitize(current_user.username))
    return task_to_response(task)


@router.post("/{task_id}/convert", response_model=ProjectConversionResponse)
@router.post("/{task_id}/convert/", response_model=ProjectConversionResponse)
async def convert_task_to_project(
    task_id: IdPath,
    conversion_request: TaskConversionRequest,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
) -> ProjectConversionResponse:
    """
    Convert a task to a project.

    This endpoint supports the TaskConverter frontend wizard.
    Only the task creator or admin can convert tasks.

    Args:
        task_id: Task ID to convert
        conversion_request: Conversion configuration
        current_user: Current authenticated user
        task_service: Task service instance

    Returns:
        Conversion result with new project details

    Raises:
        ValidationError: Task already converted or no active product
        ResourceNotFoundError: Task or user not found
        AuthorizationError: User not authorized
        DatabaseError: Database operation failed
    """
    logger.debug(f"User {sanitize(current_user.username)} converting task {sanitize(task_id)} to project")

    data = await task_service.convert_to_project(
        task_id=task_id,
        project_name=conversion_request.project_name,
        strategy=conversion_request.strategy,
        include_subtasks=conversion_request.include_subtasks,
        user_id=str(current_user.id),
    )

    logger.info(
        f"Converted task {sanitize(task_id)} to project {sanitize(data.project_id)} "
        f"(strategy: {sanitize(conversion_request.strategy)})"
    )

    return ProjectConversionResponse(
        project_id=data.project_id,
        project_name=data.project_name,
        original_task_id=data.task_id,
        conversion_strategy=conversion_request.strategy,
        created_at=datetime.now(UTC),
    )


@router.patch("/{task_id}/status/", response_model=TaskResponse)
async def change_task_status(
    task_id: IdPath,
    status_update: StatusUpdate,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """
    Change only the status field of a task. Convenience endpoint for UI.

    Raises:
        ValidationError: No tenant context
        ResourceNotFoundError: Task not found
        DatabaseError: Database operation failed
    """
    task = await task_service.change_status(task_id, status_update.status)
    return task_to_response(task)
