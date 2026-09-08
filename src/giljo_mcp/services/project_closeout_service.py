# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProjectCloseoutService - Extracted from ProjectService (Handover 0769).

Handles project closeout operations:
- close_out_project, get_closeout_data, can_close_project
- generate_closeout_prompt
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import BaseGiljoError, ResourceNotFoundError, ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.service_responses import (
    AgentStatusChangeEvent,
    CanCloseResult,
    CloseoutData,
    CloseoutPromptResult,
    ProjectCloseOutResult,
)
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.agent_terminal_cursor_service import resolve_terminal_agent_cursors
from giljo_mcp.services.closeout_ws_broadcast import (
    broadcast_agent_status_events,
    build_agent_status_change_events,
)
from giljo_mcp.services.diagnose_staging_hints import compute_stuck_conditions
from giljo_mcp.services.project_closeout_readiness import (
    AgentReadinessFinding,
    CloseoutReadinessReport,
    incomplete_todos_by_jobs,
    live_action_required_unread_by_agent,
    pending_approval_ids_by_execution,
)
from giljo_mcp.services.project_helpers import mark_chain_member_status
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)

# Agent statuses that never block closeout and are excluded from the readiness
# scan (BE-3010c: unified from the former tools-layer _SKIP_STATUSES/SKIP_STATUSES
# duplicates, which carried identical members under divergent names).
_CLOSEOUT_SKIP_STATUSES: frozenset[str] = frozenset({"decommissioned", "closed"})


class ProjectCloseoutService:
    """Service for project closeout operations."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        test_session: AsyncSession | None = None,
        websocket_manager: Any | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._project_repo = ProjectRepository()
        self._lifecycle_repo = ProjectLifecycleRepository()

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def close_out_project(self, project_id: str, tenant_key: str) -> ProjectCloseOutResult:
        """
        Close out project and decommission agents (Handover 0113).

        Marks project as completed with timestamp and optionally decommissions
        associated agents if agent jobs are tracked.

        Args:
            project_id: Project UUID
            tenant_key: Tenant key for multi-tenant isolation

        Returns:
            Dict with success status, message, and decommissioned agent details

        Raises:
            ResourceNotFoundError: When project not found or access denied
            BaseGiljoError: When operation fails
        """
        try:
            async with self._get_session(tenant_key) as session:
                # Fetch project with tenant validation
                project = await self._project_repo.get_by_id(session, tenant_key, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found or access denied",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )

                # Mark project as completed
                project.status = ProjectStatus.COMPLETED
                project.completed_at = datetime.now(UTC)
                project.updated_at = datetime.now(UTC)
                project.closeout_executed_at = datetime.now(UTC)

                # BE-6181: a chain member closing out is the terminal "completed"
                # signal the C1 conductor guard (job_completion_service
                # _guard_conductor_chain_incomplete) keys on — NOTHING wrote it
                # before this, so a conductor could never finish its chain. Marks
                # project_statuses[project]="completed" in the active run. Solo (no
                # run) -> no-op. Best-effort: never fails the closeout.
                await mark_chain_member_status(
                    db_manager=self.db_manager,
                    tenant_manager=self.tenant_manager,
                    project_id=project_id,
                    tenant_key=tenant_key,
                    status="completed",
                    test_session=self._test_session,
                    websocket_manager=self._websocket_manager,
                )

                # Decommission associated agents with smart lifecycle drain (Handover 0498)
                executions_to_decommission = await self._lifecycle_repo.get_active_agent_executions(
                    session, tenant_key, project_id
                )
                decommissioned_ids = []

                for execution in executions_to_decommission:
                    execution.status = "decommissioned"
                    execution.updated_at = datetime.now(UTC)
                    decommissioned_ids.append(execution.job_id)

                await session.commit()

                self._logger.info(
                    f"Closed out project {project_id} with {len(decommissioned_ids)} agents decommissioned"
                )

                # Broadcast status change to all browsers
                if self._websocket_manager:
                    try:
                        await self._websocket_manager.broadcast_project_update(
                            project_id=project_id,
                            update_type="closed",
                            project_data={
                                "name": project.name,
                                "status": ProjectStatus.COMPLETED.value,
                                "mission": project.mission,
                                "product_id": project.product_id,
                            },
                            tenant_key=tenant_key,
                        )
                    except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                        self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

                return ProjectCloseOutResult(
                    message="Project closed out successfully",
                    agents_decommissioned=len(decommissioned_ids),
                    decommissioned_agent_ids=decommissioned_ids,
                    project_status=ProjectStatus.COMPLETED.value,
                )

        except ResourceNotFoundError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to close out project")
            raise BaseGiljoError(
                message=f"Failed to close out project: {e!s}",
                context={"project_id": project_id, "tenant_key": tenant_key},
            ) from e

    async def decommission_project_agents(
        self,
        session: AsyncSession,
        project_id: str,
        tenant_key: str,
    ) -> tuple[list[str], list[AgentStatusChangeEvent]]:
        """
        Decommission all active agents for a project (session-in pattern).

        Sets execution status to 'decommissioned' for any still-active agents.
        Caller owns the session and transaction boundary.

        Args:
            session: Active database session (caller-managed).
            project_id: Project UUID being closed.
            tenant_key: Tenant isolation key.

        Returns:
            Tuple of (agent display names decommissioned, one AgentStatusChangeEvent
            per agent). BE-9246: the display-name list is unchanged (additive); the
            caller must emit the events POST-COMMIT, never mid-flush.
        """
        active_statuses = ["waiting", "working", "blocked", "silent"]
        executions = await self._lifecycle_repo.get_executions_by_status(
            session, tenant_key, project_id, active_statuses
        )

        # BE-9242 defense-in-depth: resolve_terminal_agent_cursors forwards each
        # agent's action-required cursor to the LIVE orchestrator, which is
        # re-resolved from the DB per iteration. Setting the orchestrator's own
        # row to 'decommissioned' first would autoflush it out of the live set,
        # so a peer processed afterward would find "no live orchestrator" and be
        # left un-acked even though one WAS live at call start. Process the
        # orchestrator's row LAST (stable sort keeps all other ordering intact)
        # so every peer still sees it live while forwarding.
        executions = sorted(executions, key=lambda e: e.agent_display_name == "orchestrator")

        # BE-9246: build events BEFORE the overwrite below so old_status is the
        # pre-transition value; the caller emits them POST-COMMIT.
        status_events = build_agent_status_change_events(executions, "decommissioned")

        decommissioned_names: list[str] = []
        for execution in executions:
            execution.status = "decommissioned"
            label = execution.agent_display_name or execution.agent_name or execution.agent_id
            decommissioned_names.append(label)
            # BE-9242: decommissioned is terminal -- resolve any live message
            # cursor this agent still holds (auto-ack informational, forward
            # action-required to the live orchestrator) so it cannot linger.
            await resolve_terminal_agent_cursors(
                session,
                tenant_key=tenant_key,
                project_id=project_id,
                agent_id=execution.agent_id,
                agent_label=label,
                terminal_status="decommissioned",
            )

        if decommissioned_names:
            await self._lifecycle_repo.flush(session)

        return decommissioned_names, status_events

    async def close_completed_agents(
        self,
        session: AsyncSession,
        project_id: str,
        tenant_key: str,
    ) -> tuple[list[str], list[AgentStatusChangeEvent]]:
        """
        Transition all 'complete' agents to 'closed' during project closeout (session-in pattern).

        Normal closeout = accepted work. Agents in 'complete' become 'closed'
        (final acceptance). Caller owns the session and transaction boundary.

        Args:
            session: Active database session (caller-managed).
            project_id: Project UUID being closed.
            tenant_key: Tenant isolation key.

        Returns:
            Tuple of (agent display names closed, one AgentStatusChangeEvent per
            agent). BE-9246: the display-name list is unchanged (additive); the
            caller must emit the events POST-COMMIT, never mid-flush.
        """
        executions = await self._lifecycle_repo.get_executions_by_status(session, tenant_key, project_id, ["complete"])

        # BE-9246: build events BEFORE the overwrite below so old_status is the
        # pre-transition value; the caller emits them POST-COMMIT.
        status_events = build_agent_status_change_events(executions, "closed")

        closed_names: list[str] = []
        for execution in executions:
            execution.status = "closed"
            label = execution.agent_display_name or execution.agent_name or execution.agent_id
            closed_names.append(label)
            # BE-9242: closed is terminal -- same auto-resolve as decommission above.
            await resolve_terminal_agent_cursors(
                session,
                tenant_key=tenant_key,
                project_id=project_id,
                agent_id=execution.agent_id,
                agent_label=label,
                terminal_status="closed",
            )

        if closed_names:
            await self._lifecycle_repo.flush(session)
            self._logger.info(
                "Closed %d agent(s) during project closeout: %s",
                len(closed_names),
                ", ".join(closed_names),
            )

        return closed_names, status_events

    async def close_completed_agents_with_commit(
        self,
        project_id: str,
        tenant_key: str,
    ) -> list[str]:
        """
        Transition 'complete' agents to 'closed' and commit in a single transaction.

        Session-owning wrapper around close_completed_agents for use from endpoints
        that should not manage sessions directly.

        Args:
            project_id: Project UUID being closed.
            tenant_key: Tenant isolation key.

        Returns:
            List of agent display names that were closed.
        """
        async with self._get_session(tenant_key) as session:
            closed_names, status_events = await self.close_completed_agents(
                session=session,
                project_id=project_id,
                tenant_key=tenant_key,
            )
            # BE-9518: this method never otherwise loads the project row; a cheap
            # PK lookup before commit is the only source for product_id here.
            project_for_broadcast = await self._project_repo.get_by_id(session, tenant_key, project_id)
            product_id = project_for_broadcast.product_id if project_for_broadcast else None
            await session.commit()

        # BE-9246 POST-COMMIT: emit only after `session.commit()` above and only
        # after the `async with` block has released the session -- never mid-flush,
        # so a broadcast can never announce a status a rollback could still undo.
        await broadcast_agent_status_events(
            self._websocket_manager,
            tenant_key=tenant_key,
            project_id=project_id,
            product_id=product_id,  # BE-9518
            events=status_events,
        )

        return closed_names

    async def get_closeout_data(self, project_id: str, db_session: Any | None = None) -> CloseoutData:
        """
        Generate dynamic closeout checklist and prompt for project completion.

        Called by GET /api/projects/{project_id}/closeout.

        Returns:
            ProjectCloseoutDataResponse payload.

        Raises:
            ResourceNotFoundError: Project not found or access denied
        """
        tenant_key = self.tenant_manager.get_current_tenant()

        if db_session:
            return await self._build_closeout_data(project_id, tenant_key, db_session)

        async with self._get_session(tenant_key) as session:
            return await self._build_closeout_data(project_id, tenant_key, session)

    async def can_close_project(
        self, project_id: str, tenant_key: str | None = None, db_session: Any | None = None
    ) -> CanCloseResult:
        """
        Determine whether a project can be closed based on agent status.

        Returns:
            Can-close response data

        Raises:
            ValidationError: Tenant context missing
            ResourceNotFoundError: Project not found or access denied
        """
        tenant_key = tenant_key or self.tenant_manager.get_current_tenant()

        if not tenant_key:
            raise ValidationError(message="Tenant context missing", context={"project_id": project_id})

        if db_session:
            return await self._build_can_close_response(project_id, tenant_key, db_session)

        async with self._get_session(tenant_key) as session:
            return await self._build_can_close_response(project_id, tenant_key, session)

    async def generate_closeout_prompt(
        self, project_id: str, tenant_key: str | None = None, db_session: Any | None = None
    ) -> CloseoutPromptResult:
        """
        Generate closeout prompt with checklist and agent summary.

        Returns:
            Closeout prompt data

        Raises:
            ValidationError: Tenant context missing
            ResourceNotFoundError: Project not found or access denied
        """
        tenant_key = tenant_key or self.tenant_manager.get_current_tenant()

        if not tenant_key:
            raise ValidationError(message="Tenant context missing", context={"project_id": project_id})

        if db_session:
            return await self._build_closeout_prompt(project_id, tenant_key, db_session)

        async with self._get_session(tenant_key) as session:
            return await self._build_closeout_prompt(project_id, tenant_key, session)

    async def _build_closeout_data(self, project_id: str, tenant_key: str, session: Any) -> CloseoutData:
        """
        Internal helper to build closeout data using provided session.

        Raises:
            ResourceNotFoundError: Project not found or access denied
        """
        project = await self._get_project_for_tenant(project_id, tenant_key, session)

        if not project:
            raise ResourceNotFoundError(
                message="Project not found or access denied",
                context={"project_id": project_id, "tenant_key": tenant_key},
            )

        status_counts = await self._aggregate_agent_statuses(project_id, tenant_key, session)
        total_agents = status_counts["total"]
        completed_agents = status_counts["completed"]
        blocked_agents = status_counts["blocked"]
        silent_agents = status_counts.get("silent", 0)
        active_agents = status_counts["active"]

        all_agents_complete = total_agents > 0 and completed_agents == total_agents and active_agents == 0
        has_blocked_agents = blocked_agents > 0

        return CloseoutData(
            project_id=project_id,
            project_name=project.name,
            agent_count=total_agents,
            completed_agents=completed_agents,
            blocked_agents=blocked_agents,
            silent_agents=silent_agents,
            all_agents_complete=all_agents_complete,
            has_blocked_agents=has_blocked_agents,
        )

    async def _build_can_close_response(self, project_id: str, tenant_key: str, session: Any) -> CanCloseResult:
        """
        Build readiness response for can-close endpoint.

        Raises:
            ResourceNotFoundError: Project not found or access denied
        """
        project = await self._get_project_for_tenant(project_id, tenant_key, session)

        if not project:
            raise ResourceNotFoundError(
                message="Project not found or access denied",
                context={"project_id": project_id, "tenant_key": tenant_key},
            )

        # BE-3010c: route the coarse can-close counts through the unified readiness
        # method so all three former readiness sites share one source of truth.
        # status_counts is derived from the same _aggregate_agent_statuses, so the
        # can-close output is byte-identical.
        report = await self.evaluate_closeout_readiness(session, project_id, tenant_key)
        status_counts = report.status_counts
        all_agents_finished = status_counts["total"] > 0 and status_counts["active"] == 0

        summary = None
        if all_agents_finished:
            summary_parts = [f"{status_counts['completed']} successful agents"]
            summary_parts.append(f"{status_counts['blocked']} blocked agents")
            summary_parts.append(f"{status_counts.get('silent', 0)} silent agents")
            summary = ", ".join(summary_parts)

        return CanCloseResult(
            can_close=all_agents_finished,
            summary=summary,
            all_agents_finished=all_agents_finished,
            agent_statuses={
                "complete": status_counts["completed"],
                "blocked": status_counts["blocked"],
                "silent": status_counts.get("silent", 0),
                "active": status_counts["active"],
            },
        )

    async def _build_closeout_prompt(self, project_id: str, tenant_key: str, session: Any) -> CloseoutPromptResult:
        """
        Build a bash closeout prompt and checklist for the project.

        Raises:
            ResourceNotFoundError: Project not found or access denied
        """
        project = await self._get_project_for_tenant(project_id, tenant_key, session)

        if not project:
            raise ResourceNotFoundError(
                message="Project not found or access denied",
                context={"project_id": project_id, "tenant_key": tenant_key},
            )

        status_counts = await self._aggregate_agent_statuses(project_id, tenant_key, session)
        agent_summary = (
            f"{status_counts['completed']} completed, "
            f"{status_counts['blocked']} blocked, "
            f"{status_counts.get('silent', 0)} silent, "
            f"{status_counts['active']} active"
        )

        repo_path = "."
        branch = "main"

        prompt = (
            "#!/bin/bash\n"
            "set -euo pipefail\n\n"
            f"cd {repo_path}\n"
            "git status\n"
            "git add .\n"
            f'git commit -m "Project complete: {project.name}"\n'
            f"git push origin {branch}\n\n"
            "cat > PROJECT_SUMMARY.md <<'EOF'\n"
            f"Project: {project.name}\n"
            f"Mission: {project.mission or ''}\n"
            f"Agent Summary: {agent_summary}\n"
            "Key Outcomes:\n"
            "- Fill in final deliverables here\n"
            "Decisions Made:\n"
            "- Record architecture or workflow decisions here\n"
            "EOF\n"
        )

        checklist = [
            "Review all agent outputs and ensure artifacts are saved.",
            "Commit final changes to the repository.",
            f"Push branch {branch} to remote.",
            "Update PROJECT_SUMMARY.md with outcomes and decisions.",
            "Run write_project_closeout() to refresh 360 Memory.",
        ]

        project.closeout_prompt = prompt
        await session.commit()

        return CloseoutPromptResult(
            prompt=prompt,
            checklist=checklist,
            project_name=project.name,
            agent_summary=agent_summary,
        )

    async def _aggregate_agent_statuses(self, project_id: str, tenant_key: str, session: Any) -> dict[str, Any]:
        """
        Aggregate agent status counts for closeout operations (migrated to AgentExecution - Handover 0367a).
        """
        job_counts = await self._lifecycle_repo.get_agent_status_counts(session, tenant_key, project_id)

        total_agents = sum(job_counts.values())
        completed_agents = job_counts.get("complete", 0)
        blocked_agents = job_counts.get("blocked", 0)
        silent_agents = job_counts.get("silent", 0)
        # Valid statuses after 0491: waiting, working, blocked, complete, silent, decommissioned
        active_statuses = {"working", "waiting", "blocked", "silent"}
        active_agents = sum(job_counts.get(status, 0) for status in active_statuses)

        return {
            "job_counts": job_counts,
            "total": total_agents,
            "completed": completed_agents,
            "blocked": blocked_agents,
            "silent": silent_agents,
            "active": active_agents,
        }

    async def _get_project_for_tenant(self, project_id: str, tenant_key: str, session: Any) -> Project | None:
        """
        Fetch a project scoped to tenant for closeout operations.
        """
        return await self._project_repo.get_by_id(session, tenant_key, project_id)

    # ========================================================================
    # Closeout readiness — the ONE source of truth (BE-3010c)
    # ========================================================================

    async def evaluate_closeout_readiness(
        self,
        session: Any,
        project_id: str,
        tenant_key: str,
        *,
        orchestrator_job_id: str | None = None,
    ) -> CloseoutReadinessReport:
        """Gather the SUPERSET of closeout-readiness findings for a project.

        The single source of readiness truth. The former three divergent
        implementations now derive from this one method:
        - ``tools/project_closeout._check_agent_readiness`` (rich blocker list),
        - ``tools/write_memory_entry._check_closeout_readiness`` (envelope), and
        - ``can_close`` / ``_build_can_close_response`` (coarse counts, via
          ``status_counts``).
        A change to WHAT is inspected (the readiness rule) is made HERE once and
        every caller observes it. Rendering (blocker shape) stays with the caller.

        Per-agent data is gathered for every non-skipped agent. When
        ``orchestrator_job_id`` is supplied the orchestrator is excluded from the
        agent scan and its own incomplete TODOs are gathered separately (the
        former ``_check_closeout_readiness`` Check 4).
        """
        exec_stmt = (
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentExecution.tenant_key == tenant_key,
                )
            )
        )
        executions = (await session.execute(exec_stmt)).scalars().all()

        # BE-9144: the former per-execution TODO + approval lookups were an N+1
        # (one query per non-skipped agent, plus one per awaiting_user agent).
        # Gather the scanned set once, then batch both lookups into a single
        # GROUP-BY-style IN(...) query each — the same technique
        # workflow_status_service uses via get_todo_counts_by_job.
        scanned = [
            execution
            for execution in executions
            if not (orchestrator_job_id and execution.job_id == orchestrator_job_id)
            and execution.status not in _CLOSEOUT_SKIP_STATUSES
        ]

        todo_job_ids = {execution.job_id for execution in scanned}
        if orchestrator_job_id:
            todo_job_ids.add(orchestrator_job_id)
        todos_by_job = await incomplete_todos_by_jobs(session, list(todo_job_ids), tenant_key)

        approval_exec_ids = [execution.id for execution in scanned if execution.status == "awaiting_user"]
        approval_by_exec = await pending_approval_ids_by_execution(session, approval_exec_ids, tenant_key)

        # TSK-9268: the live ack-based unread store the mark_read drain writes.
        live_unread_by_agent = await live_action_required_unread_by_agent(session, tenant_key, project_id, scanned)

        findings: list[AgentReadinessFinding] = []
        for execution in scanned:
            incomplete = todos_by_job.get(execution.job_id, [])
            approval_id = approval_by_exec.get(execution.id) if execution.status == "awaiting_user" else None

            findings.append(
                AgentReadinessFinding(
                    job_id=execution.job_id,
                    agent_id=execution.agent_id,
                    agent_name=execution.agent_name or execution.agent_display_name,
                    status=execution.status,
                    messages_waiting=(live_unread_by_agent.get(execution.agent_id, 0) if execution.agent_id else 0),
                    incomplete_todos=[t.content for t in incomplete],
                    incomplete_pending=sum(1 for t in incomplete if t.status == "pending"),
                    incomplete_in_progress=sum(1 for t in incomplete if t.status == "in_progress"),
                    awaiting_user=(execution.status == "awaiting_user"),
                    approval_id=approval_id,
                )
            )

        agents_checked = len(scanned)

        orch_incomplete: list[str] = []
        orch_pending = orch_in_progress = 0
        if orchestrator_job_id:
            orch = todos_by_job.get(orchestrator_job_id, [])
            orch_incomplete = [t.content for t in orch]
            orch_pending = sum(1 for t in orch if t.status == "pending")
            orch_in_progress = sum(1 for t in orch if t.status == "in_progress")

        # Coarse status counts derived from the SAME execution scan (no extra
        # query) so the can-close view shares this method without a second round
        # trip. Shape matches _aggregate_agent_statuses (the other closeout
        # endpoints' source) so can_close stays byte-identical.
        job_counts: dict[str, int] = {}
        for execution in executions:
            job_counts[execution.status] = job_counts.get(execution.status, 0) + 1
        status_counts = {
            "job_counts": job_counts,
            "total": sum(job_counts.values()),
            "completed": job_counts.get("complete", 0),
            "blocked": job_counts.get("blocked", 0),
            "silent": job_counts.get("silent", 0),
            "active": sum(job_counts.get(s, 0) for s in ("working", "waiting", "blocked", "silent")),
        }

        return CloseoutReadinessReport(
            findings=findings,
            agents_checked=agents_checked,
            status_counts=status_counts,
            orchestrator_incomplete=orch_incomplete,
            orchestrator_pending=orch_pending,
            orchestrator_in_progress=orch_in_progress,
        )

    # ========================================================================
    # Orchestrator self-healing diagnostic (BE-6111c / BE-5055)
    # ========================================================================

    async def diagnose_project_state(self, project_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        """Read-only lifecycle diagnostic for a project (no writes, no new tables).

        Composes the project's lifecycle gates (status, execution_mode,
        staging_status, implementation_launched_at), the agent/job status
        counts, and the closeout-readiness findings into ONE report so an
        orchestrator can detect and recover from a wedged project without
        guessing. Reuses :meth:`evaluate_closeout_readiness` (the single
        readiness source) and the project read; tenant-filtered throughout.

        Raises:
            ValidationError: Tenant context missing.
            ResourceNotFoundError: Project not found or access denied.
        """
        tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="Tenant context missing", context={"project_id": project_id})

        async with self._get_session(tenant_key) as session:
            project = await self._get_project_for_tenant(project_id, tenant_key, session)
            if not project:
                raise ResourceNotFoundError(
                    message="Project not found or access denied",
                    context={"project_id": project_id, "tenant_key": tenant_key},
                )

            report = await self.evaluate_closeout_readiness(session, project_id, tenant_key)
            counts = report.status_counts

            status = str(getattr(project, "status", "") or "")
            execution_mode = getattr(project, "execution_mode", None)
            launched_at = getattr(project, "implementation_launched_at", None)
            completed_at = getattr(project, "completed_at", None)
            is_terminal = status in (
                ProjectStatus.COMPLETED,
                ProjectStatus.CANCELLED,
                ProjectStatus.TERMINATED,
                ProjectStatus.DELETED,
            )
            all_finished = counts["total"] > 0 and counts["active"] == 0

            # BE-8003a: `suggested_actions` (below) is deliberately NOT migrated to
            # the canonical `next_action` envelope. It's a multi-item list mapped
            # 1:1 to independent `stuck` conditions that can co-occur (e.g. silent
            # agents AND a pending approval at once) -- collapsing it to a single
            # next_action would drop remedies for every condition but the first.
            # Allowlisted in tests/unit/test_be8003a_next_action_envelope_surface.py.
            # BE-9499b: computation moved to diagnose_staging_hints.py (Guardrail-1).
            stuck, suggested = compute_stuck_conditions(
                execution_mode=execution_mode,
                is_terminal=is_terminal,
                counts=counts,
                all_finished=all_finished,
                staging_status=getattr(project, "staging_status", None),
                any_awaiting_user=any(f.awaiting_user for f in report.findings),
                status=status,
            )

            blockers = [
                {
                    "job_id": f.job_id,
                    "agent_name": f.agent_name,
                    "status": f.status,
                    "awaiting_user": f.awaiting_user,
                    "messages_waiting": f.messages_waiting,
                    "incomplete_todo_count": len(f.incomplete_todos),
                }
                for f in report.findings
                if f.status != "complete"
            ]

            return {
                "project_id": str(getattr(project, "id", project_id)),
                "product_id": str(getattr(project, "product_id", "")) or None,
                "name": getattr(project, "name", None),
                "status": status,
                "execution_mode": execution_mode,
                "staging_status": getattr(project, "staging_status", None),
                "implementation_launched_at": launched_at.isoformat() if launched_at else None,
                "completed_at": completed_at.isoformat() if completed_at else None,
                "agent_status_counts": {
                    "total": counts["total"],
                    "complete": counts["completed"],
                    "blocked": counts["blocked"],
                    "silent": counts.get("silent", 0),
                    "active": counts["active"],
                },
                "readiness": {
                    "can_close": all_finished,
                    "blockers": blockers,
                },
                "stuck_conditions": stuck,
                "suggested_actions": suggested,
            }
