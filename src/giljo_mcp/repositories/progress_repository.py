# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProgressRepository - Data access layer for agent progress tracking.

BE-5022d: Extracted session operations from ProgressService into
repository methods.

All methods enforce tenant_key isolation. Session is passed by the caller.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete as sql_delete
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob, AgentTodoItem


logger = logging.getLogger(__name__)


class ProgressRepository:
    """
    Repository for progress tracking database operations.

    Covers: ProgressService execution/job reads, TODO item CRUD.
    All methods enforce tenant_key isolation.
    Session is passed in by the caller (service layer).
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ============================================================================
    # Execution & Job Reads
    # ============================================================================

    async def get_active_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """Get the latest active (non-terminal) execution for a job."""
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_decommissioned_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """Get a decommissioned execution for diagnostics."""
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "decommissioned",
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_completed_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """Get a cleanly completed/closed (non-decommissioned) execution (BE-6211d).

        Mirrors :meth:`get_decommissioned_execution` so report_progress can tolerate
        a late progress report after a clean complete_job as a no-op rather than a 404.
        """
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status.in_(["complete", "closed"]),
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentJob | None:
        """Get a job by ID with tenant isolation."""
        result = await session.execute(
            select(AgentJob).where(AgentJob.job_id == job_id, AgentJob.tenant_key == tenant_key)
        )
        return result.scalar_one_or_none()

    # ============================================================================
    # TODO Items
    # ============================================================================

    async def get_todo_items(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> list[AgentTodoItem]:
        """Get TODO items for a job ordered by sequence."""
        result = await session.execute(
            select(AgentTodoItem)
            .where(AgentTodoItem.job_id == job_id, AgentTodoItem.tenant_key == tenant_key)
            .order_by(AgentTodoItem.sequence)
        )
        return list(result.scalars().all())

    async def delete_todo_items(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> None:
        """Delete all TODO items for a job (replace strategy)."""
        await session.execute(
            sql_delete(AgentTodoItem).where(AgentTodoItem.job_id == job_id, AgentTodoItem.tenant_key == tenant_key)
        )

    async def add_todo_item(self, session: AsyncSession, todo_item: AgentTodoItem) -> None:
        """Add a TODO item to the session."""
        session.add(todo_item)

    async def get_max_todo_sequence(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> int:
        """Get the maximum sequence number for TODO items."""
        result = await session.execute(
            select(sa_func.max(AgentTodoItem.sequence))
            .where(AgentTodoItem.job_id == job_id)
            .where(AgentTodoItem.tenant_key == tenant_key)
        )
        return result.scalar() or -1

    async def count_todos_by_status(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        status: str,
    ) -> int:
        """Count TODO items by status for a job."""
        result = await session.execute(
            select(sa_func.count(AgentTodoItem.id))
            .where(AgentTodoItem.job_id == job_id)
            .where(AgentTodoItem.tenant_key == tenant_key)
            .where(AgentTodoItem.status == status)
        )
        return result.scalar() or 0

    async def count_all_todos(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> int:
        """Count all TODO items for a job."""
        result = await session.execute(
            select(sa_func.count(AgentTodoItem.id))
            .where(AgentTodoItem.job_id == job_id)
            .where(AgentTodoItem.tenant_key == tenant_key)
        )
        return result.scalar() or 0

    # ============================================================================
    # Session Operations
    # ============================================================================

    async def refresh(self, session: AsyncSession, entity) -> None:
        """Refresh an entity from the database."""
        await session.refresh(entity)

    async def flush(self, session: AsyncSession) -> None:
        """Flush pending changes."""
        await session.flush()
