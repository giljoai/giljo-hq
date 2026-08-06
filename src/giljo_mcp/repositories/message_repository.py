# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MessageRepository - Data access layer for message counter operations

Handover 0387f: Repository for counter-based message persistence.
Provides atomic counter updates for message tracking without JSONB.

Responsibilities:
- Increment/decrement message counters on AgentExecution
- Atomic operations for message statistics
- Multi-tenant isolation

Design Principles:
- Single Responsibility: Only counter operations
- Atomic Updates: Use SQL UPDATE with arithmetic
- Testability: Can be unit tested independently
"""

import logging
from typing import Any

from sqlalchemy import and_, case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Message, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob


logger = logging.getLogger(__name__)


class MessageRepository:
    """
    Repository for message counter operations.

    Provides atomic counter updates for message tracking without JSONB persistence.
    """

    def __init__(self):
        """Initialize MessageRepository."""
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def batch_update_counters(
        self,
        session: AsyncSession,
        tenant_key: str,
        sent_increments: dict[str, int] | None = None,
        waiting_increments: dict[str, int] | None = None,
    ) -> int:
        """
        Batch-update sent and waiting counters in a single SQL statement.

        Uses a single UPDATE with CASE expressions to touch all affected rows
        atomically. PostgreSQL acquires row locks within one statement, which
        eliminates the cross-statement circular-wait deadlock that occurs with
        N+1 individual UPDATEs.

        Args:
            session: Active database session
            tenant_key: Tenant key for multi-tenant isolation
            sent_increments: {agent_id: increment} for messages_sent_count
            waiting_increments: {agent_id: increment} for messages_waiting_count

        Returns:
            Number of rows affected

        Example:
            >>> await repo.batch_update_counters(
            ...     session=session,
            ...     tenant_key="tenant-abc",
            ...     sent_increments={"agent-1": 1},
            ...     waiting_increments={"agent-2": 1, "agent-3": 1},
            ... )
        """
        sent_increments = sent_increments or {}
        waiting_increments = waiting_increments or {}

        all_agent_ids = set(sent_increments.keys()) | set(waiting_increments.keys())
        if not all_agent_ids:
            return 0

        values: dict = {}

        if sent_increments:
            values["messages_sent_count"] = case(
                *[
                    (AgentExecution.agent_id == agent_id, AgentExecution.messages_sent_count + inc)
                    for agent_id, inc in sent_increments.items()
                ],
                else_=AgentExecution.messages_sent_count,
            )

        if waiting_increments:
            values["messages_waiting_count"] = case(
                *[
                    (AgentExecution.agent_id == agent_id, AgentExecution.messages_waiting_count + inc)
                    for agent_id, inc in waiting_increments.items()
                ],
                else_=AgentExecution.messages_waiting_count,
            )

        stmt = (
            update(AgentExecution)
            .where(
                AgentExecution.agent_id.in_(all_agent_ids),
                AgentExecution.tenant_key == tenant_key,
            )
            .values(**values)
        )
        result = await session.execute(stmt)

        self._logger.debug(
            "Batch counter update: %d rows affected (sent=%s, waiting=%s)",
            result.rowcount,
            list(sent_increments.keys()),
            list(waiting_increments.keys()),
        )
        return result.rowcount

    # ============================================================================
    # Routing / Write Operations (BE-5022c)
    # ============================================================================

    async def get_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        """
        Get a project by ID with tenant isolation.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID

        Returns:
            Project instance or None
        """
        result = await session.execute(
            select(Project).where(
                and_(
                    Project.tenant_key == tenant_key,
                    Project.id == project_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_message_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        message_id: str,
    ) -> Message | None:
        """Fetch a persisted message row by id (BE-9012b, D5; widened BE-9247).

        A thread post persists ``messages.project_id = thread.project_id`` (NULL for
        a town-square thread). The relocated auto-block / forward-on-send redirect
        reads this back off the message it is reacting to — reusing this repo's own
        ``messages`` table rather than touching the locked ``CommThreadService`` —
        to decide project-bound vs. town-square, AND (BE-9247) to get the same row's
        ``content``/``thread_id``/``from_agent_id``/``from_display_name`` for a
        send-time redirect to the live orchestrator, all off ONE query instead of a
        project-id-only lookup plus a second round-trip. Returns None if the message
        does not exist (or is in another tenant); a NULL ``project_id`` on the
        returned row is a town-square post, which callers treat as side-effect-free.
        """
        result = await session.execute(
            select(Message).where(
                and_(
                    Message.tenant_key == tenant_key,
                    Message.id == message_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def resolve_sender_display_name(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        from_agent: str,
    ) -> str | None:
        """
        Resolve sender agent reference to display name.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID
            from_agent: Sender agent reference (display name or agent_id)

        Returns:
            Display name string or None
        """
        result = await session.execute(
            select(AgentExecution.agent_display_name)
            .join(AgentJob)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentExecution.tenant_key == tenant_key,
                    (AgentExecution.agent_display_name == from_agent) | (AgentExecution.agent_id == from_agent),
                )
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def flush(self, session: AsyncSession) -> None:
        """Flush pending changes."""
        await session.flush()

    async def get_execution_by_agent_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_id: str,
    ) -> AgentExecution | None:
        """
        Get latest execution by agent_id.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            agent_id: Agent UUID

        Returns:
            AgentExecution instance or None
        """
        result = await session.execute(
            select(AgentExecution)
            .where(
                AgentExecution.agent_id == agent_id,
                AgentExecution.tenant_key == tenant_key,
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_agent_job_by_job_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentJob | None:
        """
        Get agent job by job_id with tenant isolation.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            AgentJob instance or None
        """
        result = await session.execute(
            select(AgentJob).where(
                AgentJob.job_id == job_id,
                AgentJob.tenant_key == tenant_key,
            )
        )
        return result.scalar_one_or_none()

    async def get_job_id_and_project_for_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> Any:
        """
        Get job_id and project_id for a given job.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            Row with job_id, project_id or None
        """
        result = await session.execute(
            select(AgentJob.job_id, AgentJob.project_id).where(
                AgentJob.job_id == job_id,
                AgentJob.tenant_key == tenant_key,
            )
        )
        return result.first()

    async def get_active_project(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> Project | None:
        """
        Get the active project for a tenant.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation

        Returns:
            Project ORM instance or None
        """
        result = await session.execute(
            select(Project).where(and_(Project.tenant_key == tenant_key, Project.status == ProjectStatus.ACTIVE))
        )
        return result.scalar_one_or_none()
