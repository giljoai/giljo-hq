# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

    def __init__(
        self,
        db_manager: DatabaseManager = None,
        tenant_manager: TenantManager = None,
        session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._session = session
        self._repo = TaskRepository()
        self._project_repo = ProjectRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._session
        )

    async def convert_to_project(
        self, task_id: str, project_name: str | None, strategy: str, include_subtasks: bool, user_id: str
    ) -> ConversionResult:
        try:
            async with self._get_session(self.tenant_manager.get_current_tenant()) as session:
                return await self._convert_to_project_impl(
                    session, task_id, project_name, strategy, include_subtasks, user_id
                )
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:
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
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available", context={"operation": "convert_to_project", "task_id": task_id}
            )

        task = await self._repo.get_task_by_id(session, task_id, tenant_key)

        if not task:
            raise ResourceNotFoundError(
                message="Task not found", context={"task_id": task_id, "tenant_key": tenant_key}
            )

        if task.converted_to_project_id:
            raise ValidationError(
                message=f"Task already converted to project {task.converted_to_project_id}",
                context={"task_id": task_id, "converted_to_project_id": task.converted_to_project_id},
            )

        user = await self._repo.get_user_by_id(session, tenant_key, user_id)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        if user.role != "admin" and task.created_by_user_id != user.id:
            raise AuthorizationError(
                message="Not authorized to convert this task. Only task creator or admin can convert.",
                context={"task_id": task_id, "user_id": user_id},
            )

        bound_product = await self._repo.get_product_by_id(session, task.product_id, tenant_key)

        if not bound_product:
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


        project_type_id: str | None = None
        project_series_number: int | None = task.series_number
        if project_series_number is None:
            await self._project_repo.lock_rows_for_series_shared(session, tenant_key, bound_product.id)
            project_series_number = await self._project_repo.get_next_series_number_shared(
                session, tenant_key, bound_product.id
            )

        final_project_name = project_name or task.title
        new_project = Project(
            name=final_project_name,
            description=task.description or f"Project created from task: {task.title}",
            mission="",
            product_id=bound_product.id,
            tenant_key=tenant_key,
            status=ProjectStatus.INACTIVE,
            project_type_id=project_type_id,
            series_number=project_series_number,
        )

        await self._repo.add_project(session, new_project)
        await self._repo.flush(session)

        task.converted_to_project_id = new_project.id

        if include_subtasks:
            subtasks = await self._repo.get_subtasks(session, task_id, tenant_key)

            for subtask in subtasks:
                subtask.project_id = new_project.id

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

        await self._repo.delete_task(session, task)
        self._logger.info(
            f"Deleted task {sanitize(task_id)} after successful conversion to project {sanitize(new_project.id)}"
        )

        await self._repo.flush(session)
        await self._repo.refresh(session, new_project)

        self._logger.info(
            f"Converted task {sanitize(task_id)} to project {sanitize(new_project.id)} (strategy: {sanitize(strategy)})"
        )

        return ConversionResult(
            task_id=str(task_id),
            project_id=str(new_project.id),
            project_name=new_project.name,
            project_taxonomy_alias=new_project.taxonomy_alias or "",
            product_id=bound_product.id,
            product_name=bound_product.name,
        )


    async def get_summary(self, product_id: str | None = None) -> dict[str, Any]:
        try:
            async with self._get_session(self.tenant_manager.get_current_tenant()) as session:
                return await self._get_summary_impl(session, product_id)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError, AuthorizationError):
            raise
        except Exception as e:
            self._logger.exception("Failed to get task summary")
            raise BaseGiljoError(message=str(e), context={"operation": "get_summary"}) from e

    async def _get_summary_impl(self, session: AsyncSession, product_id: str | None = None) -> dict[str, Any]:
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={"operation": "get_summary"})

        base_query = select(Task).where(Task.tenant_key == tenant_key, Task.deleted_at.is_(None))
        if product_id:
            base_query = base_query.where(Task.product_id == product_id)

        tasks = await self._repo.list_tasks(session, base_query)

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

            status = task.status or "pending"
            if status in s:
                s[status] += 1

            priority = task.priority or "medium"
            if priority in s["by_priority"]:
                s["by_priority"][priority] += 1

        return {"summary": summary, "total_products": len(summary), "total_tasks": len(tasks)}


    def can_delete_task(self, task: Task, user) -> bool:

        if user.role == "admin":
            return task.tenant_key == user.tenant_key

        return task.tenant_key == user.tenant_key and task.created_by_user_id == user.id
