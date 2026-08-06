# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Agent operations repository for auxiliary agent queries.

BE-5022d: Extracted from AgentJobRepository to keep files under 800 lines.
Contains operations for: heartbeat, silence detection, workflow status,
orchestration service, and job query service.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Row, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import AgentTodoItem, Message
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.system_setting import SystemSetting
from giljo_mcp.models.tasks import MessageAcknowledgment, MessageRecipient


SILENCE_THRESHOLD_SETTING_KEY = "agent_silence_threshold_minutes"


def _already_acked_exists_clause(tenant_key: str):
    """Shared EXISTS-subquery: a message is "acked" when a
    ``message_acknowledgments`` row exists for (message_id, the recipient's
    agent_id) in this tenant. BE-9273 DRY extraction -- byte-identical to the
    inline block every ``get_live_*_unread_counts_*`` method below used to
    duplicate; callers negate it (``~already_acked``) for "still unread".
    """
    return (
        select(MessageAcknowledgment.id)
        .where(
            MessageAcknowledgment.message_id == Message.id,
            MessageAcknowledgment.agent_id == MessageRecipient.agent_id,
            MessageAcknowledgment.tenant_key == tenant_key,
        )
        .exists()
    )


class AgentOperationsRepository:
    """Repository for auxiliary agent operations.

    Provides database operations for heartbeat tracking, silence detection,
    workflow status queries, pending job queries, and job listing.
    """

    # ============================================================================
    # Heartbeat operations
    # ============================================================================

    async def touch_heartbeat(
        self,
        session: AsyncSession,
        job_id: str,
        tenant_key: str,
        debounce_seconds: int = 30,
    ) -> bool:
        """Update last_activity_at with debounce.

        Args:
            session: Async database session
            job_id: AgentJob ID
            tenant_key: Tenant key for isolation
            debounce_seconds: Minimum seconds between updates

        Returns:
            True if update was performed, False if debounced
        """
        now = datetime.now(UTC)
        threshold = now - timedelta(seconds=debounce_seconds)

        conditions = [
            AgentExecution.job_id == job_id,
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.status.notin_(TERMINAL_EXECUTION_STATUSES),
            ((AgentExecution.last_activity_at.is_(None)) | (AgentExecution.last_activity_at < threshold)),
        ]

        result = await session.execute(update(AgentExecution).where(and_(*conditions)).values(last_activity_at=now))
        if result.rowcount:
            await session.flush()
            return True
        return False

    # ============================================================================
    # SilenceDetector operations
    # ============================================================================

    async def find_stale_working_agents(
        self,
        session: AsyncSession,
        cutoff: datetime,
    ) -> list[AgentExecution]:
        """Find working agents that have gone silent (cross-tenant scan).

        TENANT ISOLATION NOTE: This intentionally scans ALL tenants.
        The silence detector is a system-wide background health monitor.

        Args:
            session: Async database session
            cutoff: Datetime threshold; agents inactive since before this are stale

        Returns:
            List of stale AgentExecution instances with eager-loaded job/project
        """
        stmt = (
            select(AgentExecution)
            .options(selectinload(AgentExecution.job).selectinload(AgentJob.project))
            .where(
                AgentExecution.status == "working",
                or_(
                    AgentExecution.last_progress_at < cutoff,
                    and_(
                        AgentExecution.last_progress_at.is_(None),
                        AgentExecution.started_at < cutoff,
                    ),
                ),
            )
        )
        with tenant_isolation_bypass(
            session,
            reason="system silence monitor scans working agents across tenants",
            models=(AgentExecution, AgentJob, Project),
        ):
            result = await session.execute(stmt)
        return list(result.scalars().all())

    async def mark_agents_silent(
        self,
        session: AsyncSession,
        agents: list[AgentExecution],
    ) -> None:
        """Mark a list of agents as silent and flush.

        Args:
            session: Async database session
            agents: List of AgentExecution instances to mark silent
        """
        for agent in agents:
            agent.status = "silent"
        if agents:
            await session.flush()

    async def find_silent_agent_with_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> tuple[AgentExecution | None, str | None]:
        """Find a silent agent by job_id and return with project_id.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            Tuple of (AgentExecution or None, project_id or None)
        """
        stmt = (
            select(AgentExecution, AgentJob.project_id)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.job_id == job_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "silent",
            )
        )
        result = await session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None, None
        return row[0], row[1]

    async def clear_silent_to_working(
        self,
        session: AsyncSession,
        agent: AgentExecution,
    ) -> None:
        """Transition a silent agent back to working and flush.

        Args:
            session: Async database session
            agent: AgentExecution to transition
        """
        agent.status = "working"
        agent.last_progress_at = datetime.now(UTC)
        await session.flush()

    async def find_silent_agent_by_agent_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_id: str,
    ) -> tuple[AgentExecution | None, str | None]:
        """Find a silent agent by agent_id and return with project_id.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            agent_id: Agent execution ID

        Returns:
            Tuple of (AgentExecution or None, project_id or None)
        """
        stmt = (
            select(AgentExecution, AgentJob.project_id)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.agent_id == agent_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "silent",
            )
        )
        result = await session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None, None
        return row[0], row[1]

    async def get_silence_threshold_setting(
        self,
        session: AsyncSession,
    ) -> int | None:
        """Read silence threshold from system settings.

        Args:
            session: Async database session

        Returns:
            Threshold in minutes or None if not configured
        """
        stmt = select(SystemSetting.value).where(SystemSetting.key == SILENCE_THRESHOLD_SETTING_KEY)
        result = await session.execute(stmt)
        value = result.scalar_one_or_none()

        if value is None:
            return None

        try:
            return max(1, int(value))
        except ValueError:
            return None

    # ============================================================================
    # WorkflowStatusService operations
    # ============================================================================

    async def get_active_agent_ids_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[tuple[str, str | None]]:
        """Distinct ACTIVE agent_ids for a project, with each one's display name.

        "Active" = any execution NOT in a terminal status (complete / closed /
        decommissioned) — the same definition the mission/progress repos use for
        "an agent that can still receive and act on a directive". Succession
        means one ``agent_id`` can own several executions; this returns ONE entry
        per agent_id (first display name seen wins). Tenant-isolated on BOTH
        tables.

        Returns a list of ``(agent_id, display_name)`` tuples (empty if the
        project has no active executions).
        """
        query = (
            select(AgentExecution.agent_id, AgentExecution.agent_display_name)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.tenant_key == tenant_key,
                AgentJob.tenant_key == tenant_key,
                AgentJob.project_id == project_id,
                AgentExecution.status.notin_(TERMINAL_EXECUTION_STATUSES),
            )
        )
        rows = (await session.execute(query)).all()
        seen: dict[str, str | None] = {}
        for agent_id, display_name in rows:
            if agent_id not in seen:
                seen[agent_id] = display_name
        return list(seen.items())

    async def get_workflow_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        exclude_job_id: str | None = None,
    ) -> list[Row]:
        """Get all executions for a project with the columns needed for workflow status.

        BE-6071: column-projected (was select(AgentExecution, AgentJob) loading full ORM
        rows incl. mission/result blobs just to count statuses). Returns Row objects with
        named attributes: job_id, agent_id, agent_name, agent_display_name, status,
        messages_waiting_count (from AgentExecution) and job_type (from AgentJob).

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID
            exclude_job_id: Optional job_id to exclude

        Returns:
            List of projected Row objects (one per execution).
        """
        query = (
            select(
                AgentExecution.job_id,
                AgentExecution.agent_id,
                AgentExecution.agent_name,
                AgentExecution.agent_display_name,
                AgentExecution.status,
                AgentExecution.messages_waiting_count,
                AgentJob.job_type,
            )
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.tenant_key == tenant_key,
                AgentJob.project_id == project_id,
                # BE-6200 (#6): explicitly exclude project-less rows (e.g. the
                # project-less chain conductor, project_id IS NULL) so it can never
                # surface in a specific project's workflow-status agents[]. The
                # equality above already excludes NULL in SQL; this makes the intent
                # explicit and refactor-proof.
                AgentJob.project_id.isnot(None),
            )
        )
        if exclude_job_id:
            query = query.where(AgentJob.job_id != exclude_job_id)
        result = await session.execute(query)
        return list(result.all())

    async def get_live_unread_counts_by_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_ids: list[str],
    ) -> dict[str, int]:
        """Live not-yet-acked message count per agent (BE-6200 / Unit F).

        A message is "unread for this agent" when it is addressed to the agent
        (``MessageRecipient.agent_id``), in the same project + tenant, and has NOT
        been acknowledged by that agent. This is the single source of truth for the
        unread count; the denormalized ``AgentExecution.messages_waiting_count``
        column drifts from it.

        BE-9108: read-state is keyed on the ``message_acknowledgments`` drain (a row
        for (message_id, agent_id), written by ``get_thread_history(mark_read=True)``)
        — the SAME drain the closeout gate now uses. This replaced the dead
        ``Message.status == 'pending'`` predicate (nothing in src/ ever advances
        ``Message.status``, so the badge could never decrement on read). The badge is
        deliberately BROADER than the gate: it counts every not-yet-acked post
        addressed to the agent (informational included), whereas the gate blocks only
        on ``requires_action`` + non-``auto_generated`` posts. They share the ack
        read-state definition and agree for action-required posts.

        ``completion_report`` messages are SYSTEM notifications auto-sent on agent
        completion, not action items; they are excluded here so a fully-completed
        project shows no phantom unread badge (UI-1).

        One GROUP BY query across all agent_ids (no N+1). Agents with zero unread
        messages are absent from the result; the caller defaults them to 0.
        """
        if not agent_ids:
            return {}

        already_acked = _already_acked_exists_clause(tenant_key)
        stmt = (
            select(MessageRecipient.agent_id, func.count(Message.id))
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id == project_id,
                Message.message_type != "completion_report",
                MessageRecipient.agent_id.in_(agent_ids),
                ~already_acked,
            )
            .group_by(MessageRecipient.agent_id)
        )
        result = await session.execute(stmt)
        return dict(result.all())

    async def get_live_unread_counts_by_project_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
        agent_ids: list[str],
    ) -> dict[tuple[str, str], int]:
        """Live pending-message count per (project_id, agent_id) — multi-project (BE-6200 follow-on).

        Multi-project sibling of ``get_live_unread_counts_by_agent``: the /jobs list
        spans MANY projects at once, so the count must be keyed by
        ``(project_id, agent_id)`` rather than ``agent_id`` alone. Same
        "counts as unread work" definition as the single-project method and the
        closeout gate (BE-9108): a message is unread when it is addressed to the
        agent, in the matching project + tenant, NOT a ``completion_report`` system
        notification (those are auto-sent on completion, not action items), and NOT
        yet acknowledged by the agent (no ``message_acknowledgments`` row for
        (message_id, agent_id) — the ``get_thread_history(mark_read=True)`` drain,
        replacing the dead ``Message.status`` predicate nothing in src/ updates).

        ONE GROUP BY across all (project_id, agent_id) pairs (no N+1). Pairs with zero
        unread messages are absent from the result; the caller defaults them to 0.
        Keys are stringified so callers can look up with ``str(project_id)``.
        """
        if not project_ids or not agent_ids:
            return {}

        already_acked = _already_acked_exists_clause(tenant_key)
        stmt = (
            select(Message.project_id, MessageRecipient.agent_id, func.count(Message.id))
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id.in_(project_ids),
                Message.message_type != "completion_report",
                MessageRecipient.agent_id.in_(agent_ids),
                ~already_acked,
            )
            .group_by(Message.project_id, MessageRecipient.agent_id)
        )
        result = await session.execute(stmt)
        return {(str(pid), aid): cnt for pid, aid, cnt in result.all()}

    async def get_live_action_required_unread_counts_by_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_ids: list[str],
    ) -> dict[str, int]:
        """Live action-required unread count per agent (BE-9242 deliverable #3).

        Same shape as ``get_live_unread_counts_by_agent`` (the broader BADGE total)
        but scoped to the SAME "genuinely actionable" definition the closeout gate
        uses (``agent_completion_repository.get_unread_messages_for_agent``):
        ``requires_action=True`` and ``auto_generated=False``. This is the subset
        of the badge total that will actually block ``complete_job`` — surfaced
        distinctly so a ``badge>0`` that will NOT block completion no longer reads
        as "broken" on the dashboard.

        ``auto_generated=False`` already excludes ``completion_report`` system
        notices (they always carry ``auto_generated=True``), so no separate
        ``message_type`` filter is needed here (unlike the broader badge query).

        One GROUP BY query across all agent_ids (no N+1). Agents with zero
        action-required unread messages are absent from the result; the caller
        defaults them to 0.
        """
        if not agent_ids:
            return {}

        already_acked = _already_acked_exists_clause(tenant_key)
        stmt = (
            select(MessageRecipient.agent_id, func.count(Message.id))
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id == project_id,
                Message.requires_action.is_(True),
                Message.auto_generated.is_(False),
                MessageRecipient.agent_id.in_(agent_ids),
                ~already_acked,
            )
            .group_by(MessageRecipient.agent_id)
        )
        result = await session.execute(stmt)
        return dict(result.all())

    async def get_live_action_required_unread_counts_by_project_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_ids: list[str],
        agent_ids: list[str],
    ) -> dict[tuple[str, str], int]:
        """Multi-project sibling of ``get_live_action_required_unread_counts_by_agent``
        (BE-9273), keyed ``(project_id, agent_id)`` for the /jobs list -- same
        relationship as ``get_live_unread_counts_by_project_agent`` has to
        ``get_live_unread_counts_by_agent``. Identical "genuinely actionable"
        definition (requires_action, non-auto_generated, not yet acked). Missing
        pairs default to 0; keys are stringified for ``str(project_id)`` lookup.
        """
        if not project_ids or not agent_ids:
            return {}

        already_acked = _already_acked_exists_clause(tenant_key)
        stmt = (
            select(Message.project_id, MessageRecipient.agent_id, func.count(Message.id))
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id.in_(project_ids),
                Message.requires_action.is_(True),
                Message.auto_generated.is_(False),
                MessageRecipient.agent_id.in_(agent_ids),
                ~already_acked,
            )
            .group_by(Message.project_id, MessageRecipient.agent_id)
        )
        result = await session.execute(stmt)
        return {(str(pid), aid): cnt for pid, aid, cnt in result.all()}

    async def get_live_unread_counts_by_agent_and_thread(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        agent_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        """Per-thread unread breakdown per agent (BE-9242 deliverable #2).

        Sibling of ``get_live_unread_counts_by_agent`` with ``Message.thread_id``
        added to the projection/group-by, so a caller can report WHICH thread an
        agent's unread posts live on rather than only a project-wide total.
        Uses the IDENTICAL "unread" definition (not yet acked, excludes
        ``completion_report`` system notices) so, by construction,
        ``sum(per-thread counts for an agent) == get_live_unread_counts_by_agent[agent]``.

        Messages with no ``thread_id`` (legacy/non-hub direct messages) are
        grouped under the "" key so every unread message is still counted
        somewhere -- the sum-of-parts invariant holds even for pre-hub rows.

        Returns: ``{agent_id: {thread_id_or_"": count}}``. Agents/threads with
        zero unread messages are absent; the caller defaults to 0.
        """
        if not agent_ids:
            return {}

        already_acked = _already_acked_exists_clause(tenant_key)
        stmt = (
            select(
                MessageRecipient.agent_id,
                func.coalesce(Message.thread_id, "").label("thread_id"),
                func.count(Message.id),
            )
            .join(MessageRecipient, Message.id == MessageRecipient.message_id)
            .where(
                Message.tenant_key == tenant_key,
                MessageRecipient.tenant_key == tenant_key,
                Message.project_id == project_id,
                Message.message_type != "completion_report",
                MessageRecipient.agent_id.in_(agent_ids),
                ~already_acked,
            )
            .group_by(MessageRecipient.agent_id, "thread_id")
        )
        result = await session.execute(stmt)
        breakdown: dict[str, dict[str, int]] = {}
        for agent_id, thread_id, count in result.all():
            breakdown.setdefault(agent_id, {})[thread_id] = count
        return breakdown

    async def get_todo_counts_by_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        """Get aggregated TODO counts grouped by job_id and status.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_ids: List of job IDs to query

        Returns:
            Dict mapping job_id -> {status: count}
        """
        if not job_ids:
            return {}

        stmt = (
            select(
                AgentTodoItem.job_id,
                AgentTodoItem.status,
                func.count().label("cnt"),
            )
            .where(
                AgentTodoItem.job_id.in_(job_ids),
                AgentTodoItem.tenant_key == tenant_key,
            )
            .group_by(AgentTodoItem.job_id, AgentTodoItem.status)
        )
        result = await session.execute(stmt)
        rows = result.all()

        todo_map: dict[str, dict[str, int]] = {}
        for t_job_id, t_status, t_cnt in rows:
            todo_map.setdefault(t_job_id, {})[t_status] = t_cnt
        return todo_map

    # ============================================================================
    # OrchestrationService operations
    # ============================================================================

    async def get_pending_executions_with_jobs(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_display_name: str | None = None,
        limit: int = 10,
    ) -> list[tuple[AgentExecution, AgentJob]]:
        """Get pending (waiting) executions with their job records.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            agent_display_name: Optional filter by display name
            limit: Maximum results

        Returns:
            List of (AgentExecution, AgentJob) tuples
        """
        stmt = (
            select(AgentExecution, AgentJob)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status == "waiting",
            )
        )
        if agent_display_name and agent_display_name.strip():
            stmt = stmt.where(AgentExecution.agent_display_name == agent_display_name)
        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return list(result.all())

    async def get_completed_execution_result(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> dict | None:
        """Get the completion result from the latest completed execution.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID

        Returns:
            Result dict or None
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
        execution = result.scalar_one_or_none()
        if execution and execution.result:
            return execution.result
        return None

    # ============================================================================
    # JobQueryService operations
    # ============================================================================

    async def list_jobs_paginated(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str | None = None,
        status_filter: str | None = None,
        agent_display_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
        job_id: str | None = None,
    ) -> tuple[list[tuple[AgentExecution, AgentJob]], int]:
        """List jobs with pagination, returning executions + jobs and total count.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            project_id: Optional project filter
            status_filter: Optional execution status filter
            agent_display_name: Optional display name filter
            limit: Max results
            offset: Pagination offset

        Returns:
            Tuple of (list of (AgentExecution, AgentJob) tuples, total count)
        """
        query = (
            select(AgentExecution, AgentJob)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .options(selectinload(AgentJob.todo_items))
            .where(AgentExecution.tenant_key == tenant_key)
        )

        if job_id:  # BE-9330: single-job read reuses this exact query, so detail cannot drift from list
            query = query.where(AgentJob.job_id == job_id)
        if project_id:
            # BE-6200 (#6): the equality already excludes NULL; isnot(None) makes
            # the exclusion of project-less rows (chain conductor) explicit so a
            # project's /jobs agent list can never include it.
            query = query.where(AgentJob.project_id == project_id, AgentJob.project_id.isnot(None))
        if status_filter:
            query = query.where(AgentExecution.status == status_filter)
        if agent_display_name:
            query = query.where(AgentExecution.agent_display_name == agent_display_name)

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar()

        query = query.order_by(AgentJob.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        rows = list(result.all())

        return rows, total or 0

    async def get_job_messages_for_agent(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        limit: int = 50,
    ) -> tuple[AgentExecution | None, dict[str, str], list[Message]]:
        """Get messages for an agent job (for MessageAuditModal).

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            job_id: AgentJob ID
            limit: Max messages to return

        Returns:
            Tuple of (execution or None, agent_id->display_name lookup, messages list)
        """
        exec_stmt = select(AgentExecution).where(
            AgentExecution.job_id == job_id,
            AgentExecution.tenant_key == tenant_key,
        )
        execution = (await session.execute(exec_stmt)).scalar_one_or_none()

        if not execution:
            return None, {}, []

        # BE-6071: column-project to only the lookup columns instead of loading full
        # AgentExecution ORM rows for every tenant execution (this builds a display-name map).
        agents_stmt = select(
            AgentExecution.agent_id,
            AgentExecution.agent_name,
            AgentExecution.agent_display_name,
        ).where(
            AgentExecution.tenant_key == tenant_key,
        )
        agents_result = await session.execute(agents_stmt)

        agent_lookup: dict[str, str] = {}
        for agent_id, agent_name, agent_display_name in agents_result.all():
            display_name = agent_display_name.capitalize() if agent_display_name else "Agent"
            agent_lookup[agent_id] = display_name
            if agent_name:
                agent_lookup[agent_name] = display_name

        msg_stmt = (
            select(Message)
            .outerjoin(MessageRecipient)
            .where(
                Message.tenant_key == tenant_key,
                or_(
                    Message.from_agent_id == execution.agent_id,
                    MessageRecipient.agent_id == execution.agent_id,
                ),
            )
            .options(selectinload(Message.recipients))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = (await session.execute(msg_stmt)).scalars().unique().all()

        return execution, agent_lookup, list(messages)
