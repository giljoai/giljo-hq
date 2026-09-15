# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Project, Task
from giljo_mcp.models.auth import User
from giljo_mcp.models.products import Product


logger = logging.getLogger(__name__)


class TaskRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def get_task_by_id(
        self,
        session: AsyncSession,
        task_id: str,
        tenant_key: str,
    ) -> Task | None:
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Task)
            .options(selectinload(Task.task_type))
            .where(and_(Task.id == task_id, Task.tenant_key == tenant_key, Task.deleted_at.is_(None)))
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_deleted_task_by_id(
        self,
        session: AsyncSession,
        task_id: str,
        tenant_key: str,
    ) -> Task | None:
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Task)
            .options(selectinload(Task.task_type))
            .where(and_(Task.id == task_id, Task.tenant_key == tenant_key, Task.deleted_at.isnot(None)))
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_deleted_tasks(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> list[Task]:
        from sqlalchemy.orm import selectinload

        conditions = [Task.tenant_key == tenant_key, Task.deleted_at.isnot(None)]
        if product_id is not None:
            conditions.append(Task.product_id == product_id)
        stmt = (
            select(Task).options(selectinload(Task.task_type)).where(and_(*conditions)).order_by(Task.deleted_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def hard_delete_task(self, session: AsyncSession, tenant_key: str, task_id: str) -> bool:
        task = await self.get_deleted_task_by_id(session, task_id, tenant_key)
        if task is None:
            return False
        await session.execute(
            update(Task)
            .where(and_(Task.parent_task_id == task_id, Task.tenant_key == tenant_key))
            .values(parent_task_id=None)
        )
        await session.delete(task)
        await session.flush()
        return True

    async def list_tasks(
        self,
        session: AsyncSession,
        query,
    ) -> list[Task]:
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_project_by_id(
        self,
        session: AsyncSession,
        project_id: str,
        product_id: str,
        tenant_key: str,
    ) -> Project | None:
        stmt = select(Project).where(
            and_(
                Project.id == project_id,
                Project.product_id == product_id,
                Project.tenant_key == tenant_key,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_default_product(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> Product | None:
        from giljo_mcp.repositories.product_repository import ProductRepository

        return await ProductRepository().get_default_product(session, tenant_key, eager_load=False)

    async def get_product_by_id(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> Product | None:
        stmt = select(Product).where(
            and_(
                Product.id == product_id,
                Product.tenant_key == tenant_key,
                Product.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        user_id: str,
    ) -> User | None:
        stmt = select(User).where(User.tenant_key == tenant_key).where(User.id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_subtasks(
        self,
        session: AsyncSession,
        parent_task_id: str,
        tenant_key: str,
    ) -> list[Task]:
        stmt = select(Task).where(and_(Task.parent_task_id == parent_task_id, Task.tenant_key == tenant_key))
        result = await session.execute(stmt)
        return list(result.scalars().all())


    async def add_and_flush(self, session: AsyncSession, task: Task) -> None:
        session.add(task)
        await session.flush()

    async def flush_and_refresh(self, session: AsyncSession, entity) -> None:
        await session.flush()
        await session.refresh(entity)

    async def delete_task(self, session: AsyncSession, task: Task) -> None:
        await session.delete(task)


    async def add_project(self, session: AsyncSession, project: Project) -> None:
        session.add(project)

    async def flush(self, session: AsyncSession) -> None:
        await session.flush()

    async def refresh(self, session: AsyncSession, entity) -> None:
        await session.refresh(entity)
