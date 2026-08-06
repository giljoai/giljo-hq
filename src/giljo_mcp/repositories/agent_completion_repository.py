# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Agent completion and lifecycle repository.

BE-5022d: Extracted from AgentJobRepository to keep files under 800 lines.
Contains operations for: job completion validation, job lifecycle spawning,
predecessor context, template resolution, and display name collision handling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentTodoItem, Message
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.tasks import MessageAcknowledgment, MessageRecipient
from giljo_mcp.models.templates import AgentTemplate


class AgentCompletionRepository:
    """Repository for job completion and lifecycle operations.

    Provides database operations for job completion validation,
    HITL enforcement, predecessor context, template resolution,
    and display name collision handling.
    """

    async def get_agent_job_by_job_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentJob | None:
        """Get agent job by job_id with tenant isolation.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID to retrieve

        Returns:
            AgentJob or None
        """
        stmt = select(AgentJob).where(
            AgentJob.tenant_key == tenant_key,
            AgentJob.job_id == job_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ============================================================================
    # JobCompletionService operations
    # ============================================================================

    async def find_active_execution_for_completion(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """Find the latest active execution for job completion.

        BE-9292b: "active" here means NOT terminal — so a 'silent' execution
        (health-monitor timeout) IS completable, which is what lets an
        orchestrator accept a stalled-but-successful agent instead of
        force-decommissioning it. Bound to the shared
        ``TERMINAL_EXECUTION_STATUSES`` because ``close_job``'s wrong-state error
        now advertises that recovery and must not drift from this predicate.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            AgentExecution or None
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

    async def get_unread_messages_for_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_id: str,
    ) -> list[Message]:
        """Get un-acknowledged, action-required messages gating an agent's closeout.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID
            agent_id: Recipient agent ID

        Returns:
            List of action-required, non-auto-generated Message instances the
            recipient has not yet acknowledged.

        BE-9012b (D7, §6 rows 1-2): the completion gate blocks ONLY on genuine
        ``requires_action`` posts that have NOT been acted on, and never on system
        ``auto_generated`` notices (``completion_report``s carry
        ``auto_generated=true``, models/tasks.py). Informational posts
        (``requires_action=False``) are no longer "unread work" — keying the gate
        on the message intent flag instead of raw unread is what dissolves the
        "closeout dance" server-side. ``auto_generated=False`` supersedes the old
        ``message_type != 'completion_report'`` carve-out (broader + robust: any
        future system notice is auto_generated, not necessarily a completion_report).

        BE-9108: "not acted on" is keyed on the SAME drain the rest of the system
        writes — a ``message_acknowledgments`` row for (message_id, agent_id),
        written by ``get_thread_history(mark_read=True)``
        (``comm_thread_repository.ack_messages_for_participant``). This replaced the
        dead ``Message.status == 'pending'`` predicate: no code path in src/ ever
        advances ``Message.status`` off 'pending', so gating on it meant a
        ``requires_action`` post could never be drained and permanently blocked
        complete_job. The gate now clears exactly when the recipient reads the post
        via mark_read — the remedy the COMPLETION_BLOCKED hint recommends.

        NOTE: this is the GATE definition, deliberately narrower than the unread
        BADGE count (``agent_operations_repository.get_live_unread_counts_by_agent``,
        which still surfaces every not-yet-acked post). An agent can have unacked
        informational posts (badge > 0) yet still close out — they were never work
        it owed.
        """
        already_acked = (
            select(MessageAcknowledgment.id)
            .where(
                MessageAcknowledgment.message_id == Message.id,
                MessageAcknowledgment.agent_id == agent_id,
                MessageAcknowledgment.tenant_key == tenant_key,
            )
            .exists()
        )
        stmt = (
            select(Message)
            .join(MessageRecipient)
            .where(
                and_(
                    Message.tenant_key == tenant_key,
                    Message.project_id == project_id,
                    Message.requires_action.is_(True),
                    Message.auto_generated.is_(False),
                    MessageRecipient.agent_id == agent_id,
                    ~already_acked,
                )
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_undrained_messages_for_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_id: str,
    ) -> list[Message]:
        """Get EVERY not-yet-acked message addressed to agent_id (any intent).

        BE-9242: broader than ``get_unread_messages_for_agent`` (the closeout GATE,
        narrowed to ``requires_action=True`` + ``auto_generated=False``). This
        enumerates every live cursor a now-TERMINAL agent still holds — including
        informational and auto-generated posts — so a lifecycle hook can partition
        them into "safe to auto-ack" vs. "must forward, never silently drop"
        (``agent_terminal_cursor_service.resolve_terminal_agent_cursors``).

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID
            agent_id: Recipient agent ID

        Returns:
            List of not-yet-acknowledged Message instances addressed to agent_id.
        """
        already_acked = (
            select(MessageAcknowledgment.id)
            .where(
                MessageAcknowledgment.message_id == Message.id,
                MessageAcknowledgment.agent_id == agent_id,
                MessageAcknowledgment.tenant_key == tenant_key,
            )
            .exists()
        )
        stmt = (
            select(Message)
            .join(MessageRecipient)
            .where(
                and_(
                    Message.tenant_key == tenant_key,
                    Message.project_id == project_id,
                    MessageRecipient.agent_id == agent_id,
                    ~already_acked,
                )
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_incomplete_todos(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> list[AgentTodoItem]:
        """Get incomplete TODO items for a job.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            List of incomplete AgentTodoItem instances
        """
        stmt = select(AgentTodoItem).where(
            and_(
                AgentTodoItem.job_id == job_id,
                AgentTodoItem.tenant_key == tenant_key,
                AgentTodoItem.status.notin_(["completed", "skipped"]),
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def find_other_active_executions_by_agent_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        exclude_agent_id: str,
    ) -> AgentExecution | None:
        """Check if other non-terminal executions exist for a job (by agent_id).

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID
            exclude_agent_id: Agent UUID to exclude from check

        Returns:
            AgentExecution or None
        """
        stmt = select(AgentExecution).where(
            AgentExecution.job_id == job_id,
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id != exclude_agent_id,
            AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_decommissioned_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """Find the latest decommissioned execution for a job.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            Decommissioned AgentExecution or None
        """
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

    # ============================================================================
    # JobLifecycleService operations
    # ============================================================================

    async def persist_job_and_execution(
        self,
        session: AsyncSession,
        agent_job: AgentJob,
        agent_execution: AgentExecution,
        project: Any | None = None,
        is_orchestrator: bool = False,
    ) -> tuple[AgentJob, AgentExecution]:
        """Persist AgentJob + AgentExecution, update project staging if orchestrator.

        Args:
            session: Async database session
            agent_job: AgentJob instance to persist
            agent_execution: AgentExecution instance to persist
            project: Project instance to update staging_status (if orchestrator)
            is_orchestrator: Whether the agent is an orchestrator

        Returns:
            Tuple of (AgentJob, AgentExecution) after commit and refresh
        """
        session.add(agent_job)

        if is_orchestrator and project is not None:
            project.staging_status = "staging"
            project.updated_at = datetime.now(UTC)

        session.add(agent_execution)
        # BE-3006b: flush (not commit) so PKs/server defaults populate; the
        # calling service (JobLifecycleService) owns the commit before it
        # emits the agent:created event.
        await session.flush()
        await session.refresh(agent_job)
        await session.refresh(agent_execution)
        return agent_job, agent_execution

    async def get_predecessor_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        predecessor_job_id: str,
    ) -> AgentJob | None:
        """Get a predecessor job by ID with tenant isolation.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            predecessor_job_id: Predecessor job UUID

        Returns:
            AgentJob or None
        """
        result = await session.execute(
            select(AgentJob).where(
                and_(
                    AgentJob.job_id == predecessor_job_id,
                    AgentJob.tenant_key == tenant_key,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_completed_execution_for_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """Get the latest completed execution for a job.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            Completed AgentExecution or None
        """
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "complete",
            )
            .order_by(AgentExecution.completed_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_display_names_in_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> set[str]:
        """Get all active display names in a project.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID

        Returns:
            Set of active agent_display_name values
        """
        result = await session.execute(
            select(AgentExecution.agent_display_name)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.status.in_(["waiting", "working", "blocked"]),
                )
            )
        )
        return {row[0] for row in result.fetchall()}

    async def get_active_template_names(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> list[str]:
        """Get active agent template names.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            List of active template name strings

        BE-9337: this list IS the spawn allowlist -- ``job_lifecycle_service``
        accepts an ``agent_name`` only if it appears here, and renders the list
        verbatim into the rejection ("Must be one of: ..."). Soft-delete stamps
        ``deleted_at`` and deliberately leaves ``is_active`` alone
        (``template_service.py:720``), so filtering on ``is_active`` alone kept
        every TRASHED template on it. The templates API already hides those
        rows, so the two surfaces disagreed about which agents exist and the
        disagreeing one was the one gating spawning: a user was offered a
        deleted agent as a valid choice, and a spawn against it resolved no
        template (``get_template_by_name`` excludes trashed rows since BE-9325)
        and bound no identity.

        Same omission, same one-line remedy, as the six sites BE-9325 fixed --
        this is the seventh, and it sits in this file between two queries that
        were already hardened against it (``get_template_by_name`` below,
        ``find_active_orchestrator_in_project`` by BE-9242).
        """
        result = await session.execute(
            select(AgentTemplate.name).where(
                and_(
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.is_active,
                    AgentTemplate.deleted_at.is_(None),
                )
            )
        )
        return [row[0] for row in result.fetchall()]

    async def find_active_orchestrator_in_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> AgentExecution | None:
        """Find the active orchestrator execution in a project.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID

        Returns:
            Active orchestrator AgentExecution or None

        BE-9242 fix: during a legitimate orchestrator handover/succession
        (job_lifecycle_service allows a successor to spawn while the
        predecessor is still active — parent_job_id == predecessor.agent_id),
        TWO orchestrator executions match this query at once. A bare
        ``scalar_one_or_none()`` would raise ``MultipleResultsFound`` and crash
        every caller on the close/forward path. Order by ``started_at`` DESC +
        ``limit(1)`` and take ``.first()`` so the query is multiplicity-tolerant
        and deterministic: the most-recently-STARTED active orchestrator is the
        successor, i.e. the correct live forward target. Mirrors the sibling
        pattern already used by ``find_active_execution_for_completion`` /
        ``find_decommissioned_execution``.
        """
        result = await session.execute(
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.agent_display_name == "orchestrator",
                    AgentExecution.status.in_(["waiting", "working", "blocked"]),
                )
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_template_by_name(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_name: str,
    ) -> AgentTemplate | None:
        """Get an active agent template by name.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            agent_name: Template name to look up

        Returns:
            AgentTemplate or None

        BE-9325: soft-delete stamps ``deleted_at`` and deliberately leaves
        ``is_active`` alone (``template_service.py:720``), so filtering on
        ``is_active`` alone still matches a TRASHED template. Two consequences,
        both reproduced before this fix:

        1. A deleted agent still becomes a live agent's operating identity --
           this lookup runs UPSTREAM of the local-file / server-fetch split, so
           both delivery routes were affected.
        2. Delete an agent, recreate it at the same name, activate it -- an
           ordinary maintenance sequence nothing prevents, since the collision
           check and the partial unique index both exclude deleted rows. Two
           rows then matched, ``scalar_one_or_none()`` raised
           ``MultipleResultsFound``, and ``job_lifecycle_service`` turned that
           into a generic "Failed to spawn agent" -- permanently, for that name.

        Excluding trashed rows fixes both. The ordering + ``.first()`` is kept
        as belt-and-braces against any future multiplicity (the same shape
        BE-9242 already applied to ``find_active_orchestrator`` 25 lines above,
        which was hardened against this exact trap while this method was
        missed): newest-created wins, deterministically, instead of raising.
        """
        result = await session.execute(
            select(AgentTemplate)
            .where(
                and_(
                    AgentTemplate.name == agent_name,
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.is_active,
                    AgentTemplate.deleted_at.is_(None),
                )
            )
            .order_by(AgentTemplate.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()
