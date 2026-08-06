# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Agent job repository for AgentJob operations.

Handover 0017: Provides agent job coordination and lifecycle management.
Separate from user tasks - handles agent-to-agent job coordination for agentic orchestration.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Message, ProductMemoryEntry, Project
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.tasks import MessageRecipient


class AgentJobRepository:
    """
    Repository for agent job management.

    Handles the complete lifecycle of agent jobs from creation to completion,
    including status transitions and execution tracking.
    """

    def __init__(self, db_manager):
        """
        Initialize agent job repository.

        Args:
            db_manager: Database manager instance
        """
        self.db = db_manager

    # ============================================================================
    # Agent Execution & AgentJob Methods (Handover 1011 - Phase 4)
    # ============================================================================

    async def get_execution_by_agent_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_id: str,
    ) -> AgentExecution | None:
        """
        Get agent execution by agent_id with tenant isolation.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation (REQUIRED)
            agent_id: Agent ID to retrieve

        Returns:
            AgentExecution instance or None if not found

        Example:
            >>> execution = await repo.get_execution_by_agent_id(session, "tenant-1", "agent-123")
            >>> if execution:
            ...     print(execution.status)
        """
        # ORIGINAL QUERY: operations.py lines 226-230 (get_job_health endpoint)
        stmt = select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == agent_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_execution_by_job_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """
        Get agent execution by job_id with tenant isolation (fallback lookup).

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation (REQUIRED)
            job_id: AgentJob ID to retrieve execution for

        Returns:
            AgentExecution instance or None if not found

        Example:
            >>> execution = await repo.get_execution_by_job_id(session, "tenant-1", "job-456")
        """
        # ORIGINAL QUERY: operations.py lines 235-239 (get_job_health endpoint fallback)
        stmt = select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.job_id == job_id,
        )
        result = await session.execute(stmt)
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
            session: Async database session
            tenant_key: Tenant key for isolation (REQUIRED)
            job_id: AgentJob ID to retrieve

        Returns:
            AgentJob instance or None if not found

        Example:
            >>> job = await repo.get_agent_job_by_job_id(session, "tenant-1", "job-789")
            >>> if job:
            ...     print(job.mission)
        """
        # ORIGINAL QUERY: operations.py lines 318-322 (update_agent_mission endpoint)
        stmt = select(AgentJob).where(
            AgentJob.tenant_key == tenant_key,
            AgentJob.job_id == job_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_execution_for_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """
        Get the latest execution instance for a job (by started_at desc).

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation (REQUIRED)
            job_id: AgentJob ID to get latest execution for

        Returns:
            Latest AgentExecution instance or None if not found

        Example:
            >>> execution = await repo.get_latest_execution_for_job(session, "tenant-1", "job-123")
            >>> if execution:
            ...     print(f"Status: {execution.status}")
        """
        # ORIGINAL QUERY: operations.py lines 343-348 (update_agent_mission WebSocket event)
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
            )
            .order_by(AgentExecution.started_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ============================================================================
    # Agent State Operations (BE-5022c: OrchestrationAgentStateService)
    # ============================================================================

    async def find_blocked_execution_for_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """
        Find the latest blocked execution for a job.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            Blocked AgentExecution or None
        """
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "blocked",
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_complete_execution_for_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """
        Find the latest complete execution for a job.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            Complete AgentExecution or None
        """
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "complete",
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_active_execution_for_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """
        Find the latest non-terminal execution for a job.

        BE-9292b: bound to the shared ``TERMINAL_EXECUTION_STATUSES`` so
        "non-terminal" has one definition. Note 'silent' is NOT terminal — a
        stalled agent remains completable.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            Active AgentExecution or None
        """
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

    async def get_project_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        """
        Get a project by ID with tenant isolation.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID

        Returns:
            Project instance or None
        """
        result = await session.execute(
            select(Project).where(
                Project.id == project_id,
                Project.tenant_key == tenant_key,
            )
        )
        return result.scalar_one_or_none()

    async def check_memory_entry_exists(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> bool:
        """
        Check if any 360 memory entry exists for a project.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID

        Returns:
            True if memory entry exists, False otherwise
        """
        stmt = (
            select(ProductMemoryEntry)
            .where(
                ProductMemoryEntry.project_id == project_id,
                ProductMemoryEntry.tenant_key == tenant_key,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def find_orchestrator_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> AgentExecution | None:
        """
        Find the active orchestrator execution for a project.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID

        Returns:
            Orchestrator AgentExecution or None
        """
        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_auto_completion_message(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        from_agent_id: str,
        from_display_name: str,
        content: str,
        recipient_agent_id: str,
    ) -> Message:
        """
        Create an auto-generated completion report message with recipient.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID
            from_agent_id: Sender agent ID
            from_display_name: Sender display name
            content: Message content
            recipient_agent_id: Recipient agent ID

        Returns:
            Created Message instance
        """
        auto_message = Message(
            tenant_key=tenant_key,
            project_id=project_id,
            from_agent_id=from_agent_id,
            from_display_name=from_display_name,
            auto_generated=True,
            content=content,
            message_type="completion_report",
            status="pending",
        )
        session.add(auto_message)
        await session.flush()
        session.add(
            MessageRecipient(
                message_id=auto_message.id,
                agent_id=recipient_agent_id,
                tenant_key=tenant_key,
            )
        )
        return auto_message

    async def find_other_active_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        exclude_execution_id: int,
    ) -> AgentExecution | None:
        """
        Check if other non-terminal executions exist for a job.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID
            exclude_execution_id: Execution row ID to exclude

        Returns:
            AgentExecution or None
        """
        stmt = select(AgentExecution).where(
            AgentExecution.job_id == job_id,
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.id != exclude_execution_id,
            AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def flush(self, session: AsyncSession) -> None:
        """Flush pending changes.

        BE-3006b: repositories never commit. The session owner (the service
        entry point / DI scope) owns the commit. See
        internal design notes
        """
        await session.flush()

    # ============================================================================
    # BE-5022d: AgentJobManager service operations
    # ============================================================================

    async def add_execution_for_existing_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        execution: AgentExecution,
    ) -> tuple[AgentJob, AgentExecution]:
        """Verify job exists, persist a new execution, commit and refresh.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID that must exist
            execution: New AgentExecution to persist

        Returns:
            Tuple of (AgentJob, refreshed AgentExecution)

        Raises:
            ValueError: Job not found for tenant
        """
        job_result = await session.execute(
            select(AgentJob).where(
                AgentJob.job_id == job_id,
                AgentJob.tenant_key == tenant_key,
            )
        )
        job = job_result.scalar_one_or_none()

        if not job:
            raise ValueError(f"AgentJob with job_id={job_id} not found for tenant {tenant_key}")

        session.add(execution)
        # BE-3006b: flush (not commit); the calling service owns the commit.
        await session.flush()
        await session.refresh(execution)
        return job, execution

    async def complete_job_with_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> tuple[AgentJob | None, list[AgentExecution]]:
        """Mark a job as completed and all its executions as complete.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID to complete

        Returns:
            Tuple of (AgentJob or None, list of AgentExecution)
        """
        job_result = await session.execute(
            select(AgentJob).where(and_(AgentJob.job_id == job_id, AgentJob.tenant_key == tenant_key))
        )
        job = job_result.scalar_one_or_none()

        if not job:
            return None, []

        job.status = "completed"
        job.completed_at = datetime.now(UTC)

        executions_result = await session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
            )
        )
        executions = executions_result.scalars().all()

        for execution in executions:
            execution.status = "complete"

        # BE-3006b: flush (not commit); the calling service owns the commit.
        await session.flush()
        await session.refresh(job)
        for execution in executions:
            await session.refresh(execution)

        return job, list(executions)

    async def list_team_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        include_inactive: bool = False,
    ) -> list[AgentExecution]:
        """List agent executions for a job (team discovery).

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID
            include_inactive: Include completed/decommissioned executions

        Returns:
            List of AgentExecution instances
        """
        query = select(AgentExecution).where(
            and_(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
            )
        )

        if not include_inactive:
            query = query.where(AgentExecution.status.in_(["waiting", "working", "blocked"]))

        result = await session.execute(query.order_by(AgentExecution.started_at))
        return list(result.scalars().all())
