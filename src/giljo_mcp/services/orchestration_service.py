# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
OrchestrationService - Facade for orchestration and job management.

Handover 0769: Facade delegating to sub-services.
Handover 0950j: Agent state methods extracted to OrchestrationAgentStateService.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    DatabaseError,
    ValidationError,
)
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.schemas.service_responses import (
    CompleteJobResult,
    JobListResult,
    MissionResponse,
    MissionUpdateResult,
    PendingJobsResult,
    ProgressResult,
    SpawnResult,
    WorkflowStatus,
)
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService
from giljo_mcp.services.progress_service import ProgressService
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


class OrchestrationService:
    """Facade for orchestration and agent jobs (Handover 0769).

    Delegates to JobLifecycleService, MissionService, ProgressService.
    Retains: workflow status, pending jobs, listing, completion, error, reactivation.
    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        test_session: AsyncSession | None = None,
        websocket_manager: Any | None = None,
    ):
        """
        Initialize OrchestrationService with database and tenant management.

        Args:
            db_manager: Database manager for async database operations
            tenant_manager: Tenant manager for multi-tenancy support
            test_session: Optional AsyncSession for tests to share the same transaction
            websocket_manager: Optional WebSocket manager for real-time broadcasts
        """
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Handover 0450: Initialize orchestration components (from orchestrator.py)
        # Initialize lazily to avoid initialization errors in tests with mocked dependencies
        self._template_generator = None

        # Handover 0769: Facade sub-services
        self._job_lifecycle = JobLifecycleService(db_manager, tenant_manager, test_session, websocket_manager)
        self._mission = MissionService(db_manager, tenant_manager, test_session, websocket_manager)
        self._progress = ProgressService(db_manager, tenant_manager, test_session, websocket_manager)
        # Handover 0950j: Agent state management (reactivate, dismiss, set_agent_status)
        self._agent_state = OrchestrationAgentStateService(db_manager, tenant_manager, test_session, websocket_manager)

        # Sprint 002e: Extracted sub-services
        from giljo_mcp.services.job_completion_service import JobCompletionService
        from giljo_mcp.services.job_query_service import JobQueryService
        from giljo_mcp.services.workflow_status_service import WorkflowStatusService

        self._workflow_status = WorkflowStatusService(db_manager, tenant_manager, test_session)
        self._job_completion = JobCompletionService(
            db_manager, tenant_manager, test_session, websocket_manager, self._agent_state
        )
        self._job_query = JobQueryService(db_manager, tenant_manager, test_session)

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._test_session
        )

    # ============================================================================
    # Project Orchestration
    # ============================================================================

    async def get_workflow_status(
        self,
        project_id: str,
        tenant_key: str,
        exclude_job_id: str | None = None,
    ) -> WorkflowStatus:
        """Facade: delegates to WorkflowStatusService."""
        return await self._workflow_status.get_workflow_status(project_id, tenant_key, exclude_job_id)

    # ============================================================================
    # Agent Job Management — Facade Delegations (Handover 0769)
    # ============================================================================

    async def spawn_job(
        self,
        agent_display_name: str,
        agent_name: str,
        project_id: str,
        tenant_key: str,
        mission: str | None = None,
        parent_job_id: str | None = None,
        context_chunks: list[str] | None = None,
        phase: int | None = None,
        predecessor_job_id: str | None = None,
    ) -> SpawnResult:
        """Facade: delegates to JobLifecycleService.

        BE-3010b: typed (was ``*a, **kw``) so the REST callers (agent_jobs/lifecycle.py)
        and any direct caller get signature checking; mirrors
        ``JobLifecycleService.spawn_job`` exactly.
        """
        return await self._job_lifecycle.spawn_job(
            agent_display_name=agent_display_name,
            agent_name=agent_name,
            project_id=project_id,
            tenant_key=tenant_key,
            mission=mission,
            parent_job_id=parent_job_id,
            context_chunks=context_chunks,
            phase=phase,
            predecessor_job_id=predecessor_job_id,
        )

    # ============================================================================
    # Mission & Orchestrator Instructions — Facade Delegations (Handover 0769)
    # ============================================================================

    async def get_agent_mission(self, job_id, tenant_key) -> MissionResponse:
        """Facade: delegates to MissionService."""
        return await self._mission.get_agent_mission(job_id, tenant_key)

    async def update_agent_mission(self, job_id: str, tenant_key: str, mission: str) -> MissionUpdateResult:
        """Facade: delegates to MissionService."""
        return await self._mission.update_agent_mission(job_id=job_id, tenant_key=tenant_key, mission=mission)

    # ============================================================================
    # Progress Reporting — Facade Delegation (Handover 0769)
    # ============================================================================

    async def report_progress(
        self,
        job_id: str,
        progress: dict[str, Any] | None = None,
        tenant_key: str | None = None,
        todo_items: list[dict] | None = None,
        todo_append: list[dict] | None = None,
        replace: bool = False,
    ) -> ProgressResult:
        """Facade: delegates to ProgressService.

        BE-3010b: typed (was ``*a, **kw``) so the REST caller (agent_jobs/progress.py)
        and any direct caller get signature checking; mirrors
        ``ProgressService.report_progress`` exactly.
        """
        return await self._progress.report_progress(
            job_id=job_id,
            progress=progress,
            tenant_key=tenant_key,
            todo_items=todo_items,
            todo_append=todo_append,
            replace=replace,
        )

    # ============================================================================
    # Pending Jobs
    # ============================================================================

    async def get_pending_jobs(self, tenant_key: str, agent_display_name: str | None = None) -> PendingJobsResult:
        """
        Get pending jobs, optionally filtered by agent display name.

        Handover 0358b: Migrated to dual-model (AgentJob + AgentExecution).
        - Queries AgentExecution.status for execution state (waiting, working, etc.)
        - Mission comes from AgentJob via join
        - Returns both job_id (work order) and agent_id (executor)

        Args:
            tenant_key: Tenant key for isolation
            agent_display_name: Optional display name of agent to filter by

        Returns:
            Dict with list of pending jobs

        """
        try:
            # Validate inputs

            if not tenant_key or not tenant_key.strip():
                raise ValidationError(
                    message="tenant_key cannot be empty",
                    context={"agent_display_name": agent_display_name, "tenant_key": tenant_key},
                )

            # Get pending executions with their jobs (dual-model)
            repo = AgentOperationsRepository()
            async with self._get_session(tenant_key) as session:
                rows = await repo.get_pending_executions_with_jobs(session, tenant_key, agent_display_name)

                # Format jobs for response
                formatted_jobs = []
                for execution, job in rows:
                    formatted_jobs.append(
                        {
                            "job_id": job.job_id,  # Work order ID
                            "agent_id": execution.agent_id,  # Executor ID
                            "execution_id": str(execution.id) if hasattr(execution, "id") else None,  # Unique row ID
                            "tenant_key": execution.tenant_key,  # For job_to_response
                            "project_id": job.project_id,  # From AgentJob
                            "agent_display_name": execution.agent_display_name,
                            "agent_name": execution.agent_name,
                            "mission": job.mission,  # Mission from AgentJob
                            "status": execution.status,  # Execution status
                            "progress": execution.progress if hasattr(execution, "progress") else 0,
                            "context_chunks": [],  # Context chunks removed in 0366a (stored in job_metadata)
                            "created_at": job.created_at.isoformat() if job.created_at else None,
                            "started_at": execution.started_at.isoformat() if execution.started_at else None,
                            "priority": "normal",
                        }
                    )

                return PendingJobsResult(jobs=formatted_jobs, count=len(formatted_jobs))

        except ValidationError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get pending jobs")
            raise DatabaseError(
                message=f"Failed to get pending jobs: {e!s}",
                context={"agent_display_name": agent_display_name, "tenant_key": tenant_key},
            ) from e

    # ============================================================================
    # Job Completion, Error Reporting, Reactivation
    # ============================================================================

    async def complete_job(
        self,
        job_id: str,
        result: dict[str, Any],
        tenant_key: str | None = None,
        acknowledge_closeout_todo: bool = False,
        acknowledge_messages_on_complete: bool = False,
    ) -> CompleteJobResult:
        """Facade: delegates to JobCompletionService."""
        return await self._job_completion.complete_job(
            job_id,
            result,
            tenant_key,
            acknowledge_closeout_todo=acknowledge_closeout_todo,
            acknowledge_messages_on_complete=acknowledge_messages_on_complete,
        )

    async def get_agent_result(self, job_id: str, tenant_key: str | None = None) -> dict | None:
        """Fetch the completion result for a given job's latest execution.

        Args:
            job_id: Job UUID
            tenant_key: Tenant key for isolation

        Returns:
            Result dict or None if no completed execution found
        """
        if not tenant_key:
            tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            return None

        repo = AgentOperationsRepository()
        async with self._get_session(tenant_key) as session:
            return await repo.get_completed_execution_result(session, tenant_key, job_id)

    async def set_agent_status(
        self, job_id, status, reason="", wake_in_minutes=None, tenant_key=None, wake_on_signal=False
    ):
        """Facade: delegates to OrchestrationAgentStateService."""
        return await self._agent_state.set_agent_status(
            job_id,
            status,
            reason=reason,
            wake_in_minutes=wake_in_minutes,
            tenant_key=tenant_key,
            wake_on_signal=wake_on_signal,
        )

    async def list_jobs(
        self,
        tenant_key: str,
        project_id: str | None = None,
        status_filter: str | None = None,
        agent_display_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> JobListResult:
        """Facade: delegates to JobQueryService."""
        return await self._job_query.list_jobs(tenant_key, project_id, status_filter, agent_display_name, limit, offset)

    async def get_job_detail(self, job_id: str, tenant_key: str) -> dict:
        """Facade: delegates to JobQueryService.

        BE-9330: the read behind ``GET /api/agent-jobs/{job_id}``. Deliberately
        NOT ``get_agent_mission`` -- that delivers an agent's mission protocol
        (and gates on execution state), which is a different question from
        "describe this job row".
        """
        return await self._job_query.get_job_detail(tenant_key=tenant_key, job_id=job_id)

    # NOTE: update_context_usage(), estimate_message_tokens(), _trigger_auto_succession(),
    # and trigger_succession() were removed in Handover 0422/0700d - the MCP server is passive
    # and cannot track external CLI tool context usage.
    # Manual succession via UI button (simple-handover REST endpoint).

    @staticmethod
    async def health_check() -> dict[str, Any]:
        """MCP server health check."""
        from giljo_mcp import branding
        from giljo_mcp.services.version_service import get_installed_version
        from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

        return {
            "status": "healthy",
            "server": "giljo_mcp",
            "version": get_installed_version(),
            "skills_version": SKILLS_VERSION,
            "timestamp": datetime.now(UTC).isoformat(),
            "database": "connected",
            "message": f"{branding.PRODUCT_NAME} server is operational",
        }

    # Succession methods removed (0391/0461/0700d)
    # Session refresh is handled by:
    #   - REST: POST /api/agent-jobs/{job_id}/simple-handover (UI button)
    # Agents cannot self-detect context exhaustion (passive HTTP architecture).
