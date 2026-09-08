# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProjectLifecycleRepository - Data access layer for project lifecycle operations.

BE-5022c: Extracted from ProjectLifecycleService to route all database writes
through the repository layer.

Responsibilities:
- Project state queries (by ID, by status)
- Project status updates (activate, deactivate, complete, cancel, resume)
- Orchestrator fixture creation (AgentJob + AgentExecution)
- Agent execution queries and status transitions

Design Principles:
- Session-in pattern: all methods accept session as parameter
- tenant_key filtering on EVERY query — no exceptions
- No business logic — pure data access
"""

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.schemas.jsonb_validators import validate_agent_job_metadata


logger = logging.getLogger(__name__)


class ProjectLifecycleRepository:
    """
    Repository for project lifecycle database operations.

    All methods enforce tenant_key isolation.
    Session is passed in by the caller (service layer).
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ============================================================================
    # Read Operations
    # ============================================================================

    async def get_by_id(
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
                    Project.id == project_id,
                    Project.tenant_key == tenant_key,
                )
            )
        )
        return result.scalar_one_or_none()

    async def find_existing_orchestrator(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> AgentExecution | None:
        """
        Find non-decommissioned orchestrator execution for a project.

        Args:
            session: Active database session
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
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == tenant_key,
                ~AgentExecution.status.in_(["decommissioned"]),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_decommissioned_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[AgentExecution]:
        """
        Find decommissioned agent executions for a project.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID

        Returns:
            List of decommissioned AgentExecution instances
        """
        result = await session.execute(
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                    AgentExecution.status == "decommissioned",
                )
            )
        )
        return list(result.scalars().all())

    async def find_active_orchestrator_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[AgentExecution]:
        """Return all non-decommissioned orchestrator executions for a project.

        BE-6085: the conditional-reset path on deactivate needs every live
        orchestrator execution (not just one) so it can verify NONE of them ran
        and decommission all of them together. Mirrors find_existing_orchestrator
        but returns a list (scalar_one_or_none would raise on the rare duplicate).
        """
        result = await session.execute(
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == tenant_key,
                ~AgentExecution.status.in_(["decommissioned"]),
            )
        )
        return list(result.scalars().all())

    async def count_non_orchestrator_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> int:
        """Count non-orchestrator, non-decommissioned agent executions (subagents).

        BE-6085: the zero-subagents half of the never-run detection. A non-zero
        count means the orchestrator spawned real work, so deactivate must NOT
        reset. Tenant-scoped.
        """
        result = await session.execute(
            select(func.count())
            .select_from(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.agent_display_name != "orchestrator",
                AgentExecution.status.not_in(["decommissioned"]),
            )
        )
        return result.scalar() or 0

    async def delete_never_run_orchestrator_fixtures(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        statuses: list[str],
    ) -> list[dict]:
        """BE-6123: FK-safe HARD DELETE of never-run orchestrator fixture rows
        (AgentExecution + AgentJob), replacing BE-6085's status-flip tombstone.

        The service-layer gates (find_active_orchestrator_executions +
        count_non_orchestrator_executions) already proved the orchestrator never
        ran; this method performs the removal so deactivate->reactivate yields a
        fresh fixture instead of an accumulating decommissioned row.

        Safety invariants:
          - Only delete an orchestrator AgentJob when EVERY one of its executions
            qualifies (display name 'orchestrator', working_started_at IS NULL,
            status in ``statuses``). A job with any execution that ran / is a
            subagent / has another status is left fully intact.
          - Defensively skip any job/execution referenced by a user_approval
            (user_approvals.agent_execution_id and .job_id are ON DELETE RESTRICT;
            never-run fixtures have none, but a DELETE would 500 if they did).
          - DELETE executions BEFORE jobs (agent_executions.job_id ->
            agent_jobs.job_id is NO ACTION); agent_todo_items.job_id cascades at
            the DB level.
          - Tenant-scoped on every query.

        Args:
            session: Active database session (caller owns the transaction/commit).
            tenant_key: Tenant key for isolation.
            project_id: Project UUID.
            statuses: Allowed never-run statuses (e.g. ["waiting", "staged"]).

        Returns:
            List of {execution_id, agent_id, job_id} dicts for the deleted rows
            (empty when nothing qualified).
        """
        # Candidate orchestrator executions: parked pre-run, in an allowed status.
        candidates = (
            (
                await session.execute(
                    select(AgentExecution)
                    .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
                    .where(
                        AgentJob.project_id == project_id,
                        AgentJob.tenant_key == tenant_key,
                        AgentExecution.tenant_key == tenant_key,
                        AgentExecution.agent_display_name == "orchestrator",
                        AgentExecution.working_started_at.is_(None),
                        AgentExecution.status.in_(statuses),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not candidates:
            return []

        # Per-job gate: only delete a job when ALL of its executions qualify.
        job_to_execs: dict[str, list[AgentExecution]] = {}
        for job_id in {c.job_id for c in candidates}:
            execs = (
                (
                    await session.execute(
                        select(AgentExecution).where(
                            AgentExecution.job_id == job_id,
                            AgentExecution.tenant_key == tenant_key,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if execs and all(
                e.agent_display_name == "orchestrator" and e.working_started_at is None and e.status in statuses
                for e in execs
            ):
                job_to_execs[job_id] = list(execs)
        if not job_to_execs:
            return []

        # FK guard: drop any job that is itself, or has an execution, referenced
        # by a user_approval (ON DELETE RESTRICT would otherwise raise).
        all_exec_ids = [e.id for execs in job_to_execs.values() for e in execs]
        referenced = (
            await session.execute(
                select(UserApproval.agent_execution_id, UserApproval.job_id).where(
                    UserApproval.tenant_key == tenant_key,
                    or_(
                        UserApproval.agent_execution_id.in_(all_exec_ids),
                        UserApproval.job_id.in_(list(job_to_execs.keys())),
                    ),
                )
            )
        ).all()
        blocked_exec_ids = {row[0] for row in referenced}
        blocked_job_ids = {row[1] for row in referenced}
        for job_id in list(job_to_execs.keys()):
            execs = job_to_execs[job_id]
            if job_id in blocked_job_ids or any(e.id in blocked_exec_ids for e in execs):
                self._logger.warning(
                    "[BE-6123] Skipping never-run orchestrator job %s for project %s: referenced by a user_approval",
                    job_id,
                    project_id,
                )
                del job_to_execs[job_id]
        if not job_to_execs:
            return []

        deleted: list[dict] = []
        exec_ids: list[str] = []
        for job_id, execs in job_to_execs.items():
            for e in execs:
                deleted.append({"execution_id": str(e.id), "agent_id": e.agent_id, "job_id": job_id})
                exec_ids.append(e.id)

        # FK order: executions first (NO ACTION fk to agent_jobs), then jobs.
        await session.execute(
            delete(AgentExecution).where(
                AgentExecution.id.in_(exec_ids),
                AgentExecution.tenant_key == tenant_key,
            )
        )
        await session.execute(
            delete(AgentJob).where(
                AgentJob.job_id.in_(list(job_to_execs.keys())),
                AgentJob.tenant_key == tenant_key,
            )
        )
        return deleted

    async def delete_all_agent_state_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> dict[str, int]:
        """FE-6180: FK-safe HARD DELETE of ALL agent state for a project.

        The destructive sweep behind the 'Reset to original' / Deactivate-Chain
        primitive: removes every AgentJob + AgentExecution for the project
        (orchestrator AND any spawned subagents, ran or not) so the project
        returns to a clean pre-stage slate with NO audit trail. (Terminate is the
        audit-preserving graceful exit; this is the discard-everything rewind.)

        FK-safe order (information_schema): ``user_approvals`` (RESTRICT on both
        ``job_id`` and ``agent_execution_id``) first, then ``agent_executions``
        (NO ACTION fk -> agent_jobs), then ``agent_jobs`` (``agent_todo_items``
        CASCADEs at the DB level). ``messages`` carry no hard FK to agent jobs and
        are left intact. Tenant-scoped; caller owns the transaction/commit.
        Idempotent — a project with no agent rows is a no-op.

        Returns:
            ``{"jobs": n, "executions": n, "approvals": n}`` delete counts.
        """
        job_ids = (
            (
                await session.execute(
                    select(AgentJob.job_id).where(
                        AgentJob.project_id == project_id,
                        AgentJob.tenant_key == tenant_key,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not job_ids:
            return {"jobs": 0, "executions": 0, "approvals": 0}

        exec_ids = (
            (
                await session.execute(
                    select(AgentExecution.id).where(
                        AgentExecution.job_id.in_(job_ids),
                        AgentExecution.tenant_key == tenant_key,
                    )
                )
            )
            .scalars()
            .all()
        )

        # 1) user_approvals first (RESTRICT on job_id AND agent_execution_id).
        approval_conds = [UserApproval.job_id.in_(job_ids)]
        if exec_ids:
            approval_conds.append(UserApproval.agent_execution_id.in_(exec_ids))
        appr = await session.execute(
            delete(UserApproval).where(
                UserApproval.tenant_key == tenant_key,
                or_(*approval_conds),
            )
        )
        # 2) executions (NO ACTION fk to agent_jobs).
        await session.execute(
            delete(AgentExecution).where(
                AgentExecution.job_id.in_(job_ids),
                AgentExecution.tenant_key == tenant_key,
            )
        )
        # 3) jobs (agent_todo_items.job_id CASCADEs).
        await session.execute(
            delete(AgentJob).where(
                AgentJob.job_id.in_(job_ids),
                AgentJob.tenant_key == tenant_key,
            )
        )
        return {"jobs": len(job_ids), "executions": len(exec_ids), "approvals": appr.rowcount or 0}

    # ============================================================================
    # Write Operations
    # ============================================================================

    async def flush(self, session: AsyncSession) -> None:
        """Flush pending changes."""
        await session.flush()

    async def refresh(self, session: AsyncSession, entity: Project | AgentJob | AgentExecution) -> None:
        """Refresh an entity from the database."""
        await session.refresh(entity)

    async def cancel_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        reason: str | None = None,
    ) -> int:
        """
        Cancel a project via bulk update.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID
            reason: Optional cancellation reason

        Returns:
            Number of rows affected (0 or 1)
        """
        update_values: dict = {
            "status": ProjectStatus.CANCELLED,
            "completed_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        if reason:
            update_values["cancellation_reason"] = reason

        result = await session.execute(
            update(Project)
            .where(and_(Project.id == project_id, Project.tenant_key == tenant_key))
            .values(**update_values)
        )
        return result.rowcount

    async def create_orchestrator_fixture(
        self,
        session: AsyncSession,
        tenant_key: str,
        project: Project,
    ) -> dict[str, str]:
        """
        Create orchestrator AgentJob + AgentExecution fixture.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            project: Project instance

        Returns:
            Dict with job_id and agent_id
        """
        job_id = str(uuid4())
        agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project.id,
            mission=f"Orchestrator for project: {project.name}",
            job_type="orchestrator",
            status="active",
            job_metadata=validate_agent_job_metadata(
                {
                    "created_via": "project_activation_fixture",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ),
        )
        session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
            progress=0,
            health_status="unknown",
            # CE-0026: fixture is created on project activation, before staging
            # has begun. The first orchestrator execution always belongs to the
            # staging phase.
            project_phase="staging",
        )
        session.add(agent_execution)

        await session.flush()
        await session.refresh(agent_job)
        await session.refresh(agent_execution)

        return {
            "job_id": job_id,
            "agent_id": agent_id,
            "execution_id": str(agent_execution.id),
        }

    # ============================================================================
    # BE-5022d: Additional methods for closeout/staging/launch services
    # ============================================================================

    async def get_active_agent_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        exclude_statuses: list[str] | None = None,
    ) -> list[AgentExecution]:
        """
        Get agent executions for a project, excluding specified statuses.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID
            exclude_statuses: Statuses to exclude (default: ["complete", "decommissioned"])

        Returns:
            List of AgentExecution instances
        """
        if exclude_statuses is None:
            exclude_statuses = ["complete", "decommissioned"]
        result = await session.execute(
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                    AgentExecution.status.notin_(exclude_statuses),
                )
            )
        )
        return list(result.scalars().all())

    async def get_executions_by_status(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        statuses: list[str],
    ) -> list[AgentExecution]:
        """
        Get agent executions for a project with specified statuses.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            project_id: Project UUID
            statuses: List of statuses to match

        Returns:
            List of AgentExecution instances
        """
        result = await session.execute(
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.status.in_(statuses),
                )
            )
        )
        return list(result.scalars().all())

    async def get_agent_status_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> dict:
        """
        Aggregate agent execution status counts for a project.

        Returns:
            Dict mapping status string to count.
        """
        from sqlalchemy import func

        job_counts_result = await session.execute(
            select(AgentExecution.status, func.count(AgentExecution.agent_id).label("count"))
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                )
            )
            .group_by(AgentExecution.status)
        )
        return dict(job_counts_result.all())

    async def add_entity(self, session: AsyncSession, entity) -> None:
        """Add an entity to the session."""
        session.add(entity)

    async def find_non_decommissioned_orchestrator(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> AgentExecution | None:
        """Find the latest non-decommissioned orchestrator for a project (ordered by started_at desc)."""
        stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == tenant_key,
                ~AgentExecution.status.in_(["decommissioned"]),
            )
            .order_by(AgentExecution.started_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def get_user(
        self,
        session: AsyncSession,
        tenant_key: str,
        user_id: str,
    ):
        """Get a user by ID with tenant isolation."""
        from giljo_mcp.models.auth import User

        result = await session.execute(select(User).where(and_(User.id == user_id, User.tenant_key == tenant_key)))
        return result.scalar_one_or_none()

    async def get_user_field_priorities(
        self,
        session: AsyncSession,
        tenant_key: str,
        user_id: str,
    ) -> list:
        """Get user field priority rows."""
        from giljo_mcp.models.auth import UserFieldPriority

        result = await session.execute(
            select(UserFieldPriority).where(
                and_(
                    UserFieldPriority.user_id == user_id,
                    UserFieldPriority.tenant_key == tenant_key,
                )
            )
        )
        return list(result.scalars().all())
