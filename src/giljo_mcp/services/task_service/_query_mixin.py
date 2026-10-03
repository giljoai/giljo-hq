# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Task


class _TaskQueryMixin:


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
        try:
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

        except BaseGiljoError:
            raise
        except Exception as e:
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
        query = (
            select(Task)
            .options(selectinload(Task.task_type))
            .where(Task.tenant_key == tenant_key, Task.deleted_at.is_(None))
        )

        if filter_type == "product_tasks":
            if product_id:
                query = query.where(Task.product_id == product_id)
            else:
                default_product = await self._repo.get_default_product(session, tenant_key)

                if default_product:
                    query = query.where(Task.product_id == default_product.id)
                else:
                    return []

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

        query = query.order_by(Task.created_at.desc())

        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)

        return await self._repo.list_tasks(session, query)


    async def get_task(self, task_id: str) -> Task:
        try:
            async with self._get_session() as session:
                return await self._get_task_impl(session, task_id)
        except BaseGiljoError:
            raise
        except Exception as e:
            self._logger.exception("Failed to get task {task_id}")
            raise BaseGiljoError(message=str(e), context={"operation": "get_task", "task_id": task_id}) from e

    async def _get_task_impl(self, session: AsyncSession, task_id: str) -> Task:
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
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(
                    message="No tenant context available", context={"operation": "list_deleted_tasks"}
                )
            async with self._get_session(tenant_key) as session:
                return await self._repo.list_deleted_tasks(session, tenant_key, product_id)
        except BaseGiljoError:
            raise
        except Exception as e:
            self._logger.exception("Failed to list deleted tasks")
            raise BaseGiljoError(message=str(e), context={"operation": "list_deleted_tasks"}) from e

    async def get_summary(self, product_id: str | None = None) -> dict[str, Any]:
        return await self._conversion.get_summary(product_id)
