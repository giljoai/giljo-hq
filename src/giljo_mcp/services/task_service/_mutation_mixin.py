# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime

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
from giljo_mcp.services.task_service._handover_guards import (
    require_handover_description_shape_of,
    resolve_create_task_type,
)
from giljo_mcp.services.task_type_immutability import (
    TaskTypeImmutableError,
    require_no_task_type_change,
)
from giljo_mcp.services.text_field_validation import require_non_blank
from giljo_mcp.utils.log_sanitizer import sanitize


_ALLOWED_TASK_UPDATE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "status",
        "priority",
        "estimated_effort",
        "actual_effort",
        "project_id",
        "parent_task_id",
        "converted_to_project_id",
        "hidden",
    }
)


class _TaskMutationMixin:

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
        validate_product: bool = False,
    ) -> str:
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
                    validate_product=validate_product,
                )
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:
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
        validate_product: bool = False,
    ) -> str:
        if not tenant_key:
            tenant_key = self.tenant_manager.get_current_tenant()

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

        if project_id:
            project = await self._repo.get_project_by_id(session, project_id, product_id, tenant_key)

            if not project:
                raise ResourceNotFoundError(
                    message=f"Project {project_id} not found or access denied",
                    context={"project_id": project_id, "product_id": product_id, "tenant_key": tenant_key},
                )

        if parent_task_id:
            parent = await self._repo.get_task_by_id(session, parent_task_id, tenant_key)
            if not parent:
                raise ResourceNotFoundError(
                    message=f"Parent task {parent_task_id} not found or access denied",
                    context={"parent_task_id": parent_task_id, "tenant_key": tenant_key},
                )

        task_title = title or content
        task_description = description or content

        require_non_blank(task_title, field="title", operation="create_task", entity="Task")

        if assign_shared_series and task_type_id is not None and series_number is None:
            from giljo_mcp.repositories.project_repository import ProjectRepository

            project_repo = ProjectRepository()
            await project_repo.lock_rows_for_series_shared(session, tenant_key, product_id)
            series_number = await project_repo.get_next_series_number_shared(session, tenant_key, product_id)
        if assigned_series_out is not None:
            assigned_series_out[0] = series_number

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
        task_type: str | None = None,
    ) -> Task:
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not effective_tenant_key:
            raise ValidationError(
                message="tenant_key is required for task creation",
                context={"operation": "create_task_for_rest"},
            )

        requested_type = resolve_create_task_type(task_type, description)

        from giljo_mcp.services.taxonomy_service import TaxonomyService

        taxonomy = TaxonomyService(db_manager=self.db_manager, session=self._session)
        reserved_type = await taxonomy.ensure_reserved_type(effective_tenant_key, requested_type)
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
            validate_product=True,
        )

        async with self._get_session(effective_tenant_key) as session:
            task = await self._repo.get_task_by_id(session, task_id, effective_tenant_key)
        if task is None:
            raise ResourceNotFoundError(
                message="Task not found after creation",
                context={"task_id": task_id, "tenant_key": effective_tenant_key},
            )

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


    async def update_task(self, task_id: str, **kwargs) -> TaskUpdateResult:
        try:
            async with self._get_session() as session:
                return await self._update_task_impl(session, task_id, **kwargs)

        except (
            BaseGiljoError,
            ResourceNotFoundError,
            ValidationError,
            AuthorizationError,
            TaskTypeImmutableError,
        ):
            raise
        except Exception as e:
            self._logger.exception("Failed to update task")
            raise BaseGiljoError(message=str(e), context={"operation": "update_task", "task_id": task_id}) from e

    async def _update_task_impl(self, session: AsyncSession, task_id: str, **kwargs) -> TaskUpdateResult:
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

        if "title" in kwargs:
            require_non_blank(kwargs["title"], field="title", operation="update_task", entity="Task", task_id=task_id)

        require_handover_description_shape_of(task, kwargs.get("description"))

        if "task_type" in kwargs:
            require_no_task_type_change(
                current_type=getattr(task.task_type, "abbreviation", None) if task.task_type else None,
                requested_type=kwargs.pop("task_type"),
                task_id=task_id,
            )

        updated_fields = []
        for key, value in kwargs.items():
            if key in _ALLOWED_TASK_UPDATE_FIELDS:
                setattr(task, key, value)
                updated_fields.append(key)
            else:
                self._logger.warning(
                    f"Rejected update to disallowed field '{sanitize(key)}' on task {sanitize(task_id)}"
                )

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

        await session.commit()

        self._logger.info(f"Updated task {sanitize(task_id)}: {sanitize(updated_fields)}")

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
                        "product_id": task.product_id,
                    },
                )
            except (RuntimeError, ValueError, OSError) as ws_error:
                self._logger.warning(f"Failed to broadcast task:updated event: {ws_error}")

        return TaskUpdateResult(task_id=task_id, updated_fields=updated_fields)

    async def delete_task(self, task_id: str, user_id: str) -> None:
        try:
            async with self._get_session() as session:
                return await self._delete_task_impl(session, task_id, user_id)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:
            self._logger.exception("Failed to delete task {task_id}")
            raise BaseGiljoError(message=str(e), context={"operation": "delete_task", "task_id": task_id}) from e

    async def _delete_task_impl(self, session: AsyncSession, task_id: str, user_id: str) -> None:
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available", context={"operation": "delete_task", "task_id": task_id}
            )

        task = await self._repo.get_task_by_id(session, task_id, tenant_key)

        if not task:
            raise ResourceNotFoundError(
                message="Task not found", context={"task_id": task_id, "tenant_key": tenant_key}
            )

        user = await self._repo.get_user_by_id(session, tenant_key, user_id)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        if not self._conversion.can_delete_task(task, user):
            raise AuthorizationError(
                message="Not authorized to delete this task. Only task creator or admin can delete.",
                context={"task_id": task_id, "user_id": user_id},
            )

        task.deleted_at = datetime.now(UTC)
        await self._repo.flush(session)

        self._logger.info(f"Soft-deleted task {sanitize(task_id)} by user {sanitize(user_id)}")

    async def restore_task(self, task_id: str) -> Task:
        try:
            async with self._get_session() as session:
                return await self._restore_task_impl(session, task_id)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:
            self._logger.exception("Failed to restore task {task_id}")
            raise BaseGiljoError(message=str(e), context={"operation": "restore_task", "task_id": task_id}) from e

    async def _restore_task_impl(self, session: AsyncSession, task_id: str) -> Task:
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

        if recover_window_expired(task.deleted_at):
            raise ValidationError(
                message=(
                    f"This task was deleted more than {RECOVER_WINDOW_DAYS} days ago and can no longer be recovered."
                ),
                context={"task_id": task_id, "tenant_key": tenant_key},
            )

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
