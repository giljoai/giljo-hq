# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TaskRepository - Data access layer for Task entities.

BE-5022d: Extracted from task_service.py and task_conversion_service.py
to enforce the service->repository boundary.

All database reads and writes for Task are routed through this repository.
Tenant isolation is enforced at the query level on every operation.
"""

from __future__ import annotations

import logging

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Project, Task
from giljo_mcp.models.auth import User
from giljo_mcp.models.products import Product


logger = logging.getLogger(__name__)


class TaskRepository:
    """
    Repository for task-domain database operations.

    Methods accept an AsyncSession parameter (session-in pattern) so the
    calling service controls transaction boundaries.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ========================================================================
    # Task reads
    # ========================================================================

    async def get_task_by_id(
        self,
        session: AsyncSession,
        task_id: str,
        tenant_key: str,
    ) -> Task | None:
        """
        Get a task by ID with tenant isolation.

        Args:
            session: Active database session
            task_id: Task UUID
            tenant_key: Tenant key for isolation

        Returns:
            Task ORM instance or None
        """
        from sqlalchemy.orm import selectinload

        # BE-6130b: live reads exclude soft-deleted (trashed) tasks. Use
        # get_deleted_task_by_id for the restore path.
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
        """Get a SOFT-DELETED task by ID with tenant isolation (for restore).

        Mirror of ``get_task_by_id`` but for the trash: only ``deleted_at IS NOT
        NULL`` rows, so a live task can never be "restored".
        """
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
        """List soft-deleted tasks for a tenant, optionally scoped to a product
        (most-recently-trashed first). Powers the task recover dialog."""
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
        """Permanently delete a SOFT-DELETED task (TSK-6132 reaper). Tenant-isolated.

        Restricted to trashed rows (``deleted_at IS NOT NULL``) so a live task is
        never reaped. ``tasks.parent_task_id`` is a self-FK with NO ``ON DELETE``
        action, so any child subtasks still pointing at this row are first
        re-parented to NULL (within the tenant) to keep the delete FK-safe; that
        orphan-promotion mirrors how a hard delete would otherwise FK-violate.
        Roadmap items (``roadmap_items.task_id``) carry ``ON DELETE CASCADE`` and
        clear at the DB level. Returns True if a trashed task was deleted, False if
        none matched (idempotent).
        """
        task = await self.get_deleted_task_by_id(session, task_id, tenant_key)
        if task is None:
            return False
        # Re-parent any children to NULL before deleting (self-FK has no cascade).
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
        """
        Execute a pre-built task query and return results.

        Args:
            session: Active database session
            query: SQLAlchemy select statement

        Returns:
            List of Task ORM instances
        """
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_project_by_id(
        self,
        session: AsyncSession,
        project_id: str,
        product_id: str,
        tenant_key: str,
    ) -> Project | None:
        """
        Get a project by ID with tenant and product isolation.

        Args:
            session: Active database session
            project_id: Project UUID
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Project ORM instance or None
        """
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
        """
        Get the tenant's DEFAULT product -- where an unscoped read resolves.

        FE-9524: renamed from
        ``get_active_product``. Delegates to
        ``ProductRepository.get_default_product`` (the sole-product fallback
        + single-row guarantee are documented and maintained in exactly one
        place -- this used to be a second, drifted copy of that query, which
        is how it was still reading ``is_active`` after the split).

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation

        Returns:
            Product ORM instance or None
        """
        from giljo_mcp.repositories.product_repository import ProductRepository

        return await ProductRepository().get_default_product(session, tenant_key, eager_load=False)

    async def get_product_by_id(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> Product | None:
        """
        Get a non-deleted product by ID with tenant isolation.

        Mirrors the validation the REST task-create endpoint used to do inline
        (BE-3006a single-writer rule): tenant-scoped and ``deleted_at IS NULL``.
        The caller checks ``is_active`` so it can raise a distinct error.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Product ORM instance or None
        """
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
        """
        Get a user by ID (for permission checks).

        Args:
            session: Active database session
            user_id: User UUID

        Returns:
            User ORM instance or None
        """
        stmt = select(User).where(User.tenant_key == tenant_key).where(User.id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_subtasks(
        self,
        session: AsyncSession,
        parent_task_id: str,
        tenant_key: str,
    ) -> list[Task]:
        """
        Get child tasks for a parent task.

        Args:
            session: Active database session
            parent_task_id: Parent task UUID
            tenant_key: Tenant key for isolation

        Returns:
            List of child Task ORM instances
        """
        stmt = select(Task).where(and_(Task.parent_task_id == parent_task_id, Task.tenant_key == tenant_key))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========================================================================
    # Task writes
    # ========================================================================

    async def add_and_flush(self, session: AsyncSession, task: Task) -> None:
        """
        Add a task and flush (BE-6086: repository flushes; the session owner commits).

        Flushing assigns the row its server-side id and makes it visible within
        the transaction without committing. The owning service entry point (the
        ``async with self._get_session(...)`` scope) commits on clean exit.

        Args:
            session: Active database session
            task: Fully constructed Task ORM instance
        """
        session.add(task)
        await session.flush()

    async def flush_and_refresh(self, session: AsyncSession, entity) -> None:
        """
        Flush pending changes and refresh an entity (BE-6086: flush, never commit).

        ``refresh`` re-reads server-generated/defaulted columns within the same
        transaction after the flush; the session owner commits on scope exit.

        Args:
            session: Active database session
            entity: ORM instance to refresh
        """
        await session.flush()
        await session.refresh(entity)

    async def delete_task(self, session: AsyncSession, task: Task) -> None:
        """
        Delete a task from the session.

        Args:
            session: Active database session
            task: Task ORM instance to delete
        """
        await session.delete(task)

    # ========================================================================
    # Project writes (for task conversion)
    # ========================================================================

    async def add_project(self, session: AsyncSession, project: Project) -> None:
        """
        Add a project to the session.

        Args:
            session: Active database session
            project: Fully constructed Project ORM instance
        """
        session.add(project)

    async def flush(self, session: AsyncSession) -> None:
        """
        Flush pending changes without committing.

        Args:
            session: Active database session
        """
        await session.flush()

    async def refresh(self, session: AsyncSession, entity) -> None:
        """
        Refresh an entity from the database.

        Args:
            session: Active database session
            entity: ORM instance to refresh
        """
        await session.refresh(entity)
