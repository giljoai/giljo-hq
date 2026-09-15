# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

        self._template_generator = None

        self._job_lifecycle = JobLifecycleService(db_manager, tenant_manager, test_session, websocket_manager)
        self._mission = MissionService(db_manager, tenant_manager, test_session, websocket_manager)
        self._progress = ProgressService(db_manager, tenant_manager, test_session, websocket_manager)
        self._agent_state = OrchestrationAgentStateService(db_manager, tenant_manager, test_session, websocket_manager)

        from giljo_mcp.services.job_completion_service import JobCompletionService
        from giljo_mcp.services.job_query_service import JobQueryService
        from giljo_mcp.services.workflow_status_service import WorkflowStatusService

        self._workflow_status = WorkflowStatusService(db_manager, tenant_manager, test_session)
        self._job_completion = JobCompletionService(
            db_manager, tenant_manager, test_session, websocket_manager, self._agent_state
        )
        self._job_query = JobQueryService(db_manager, tenant_manager, test_session)

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._test_session
        )


    async def get_workflow_status(
        self,
        project_id: str,
        tenant_key: str,
        exclude_job_id: str | None = None,
    ) -> WorkflowStatus:
        return await self._workflow_status.get_workflow_status(project_id, tenant_key, exclude_job_id)


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
        inline_seed: bool = False,
    ) -> SpawnResult:
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
            inline_seed=inline_seed,
        )


    async def get_agent_mission(self, job_id, tenant_key) -> MissionResponse:
        return await self._mission.get_agent_mission(job_id, tenant_key)

    async def update_agent_mission(self, job_id: str, tenant_key: str, mission: str) -> MissionUpdateResult:
        return await self._mission.update_agent_mission(job_id=job_id, tenant_key=tenant_key, mission=mission)


    async def report_progress(
        self,
        job_id: str,
        progress: dict[str, Any] | None = None,
        tenant_key: str | None = None,
        todo_items: list[dict] | None = None,
        todo_append: list[dict] | None = None,
        replace: bool = False,
    ) -> ProgressResult:
        return await self._progress.report_progress(
            job_id=job_id,
            progress=progress,
            tenant_key=tenant_key,
            todo_items=todo_items,
            todo_append=todo_append,
            replace=replace,
        )


    async def get_pending_jobs(self, tenant_key: str, agent_display_name: str | None = None) -> PendingJobsResult:
        try:

            if not tenant_key or not tenant_key.strip():
                raise ValidationError(
                    message="tenant_key cannot be empty",
                    context={"agent_display_name": agent_display_name, "tenant_key": tenant_key},
                )

            repo = AgentOperationsRepository()
            async with self._get_session(tenant_key) as session:
                rows = await repo.get_pending_executions_with_jobs(session, tenant_key, agent_display_name)

                formatted_jobs = []
                for execution, job in rows:
                    formatted_jobs.append(
                        {
                            "job_id": job.job_id,
                            "agent_id": execution.agent_id,
                            "execution_id": str(execution.id) if hasattr(execution, "id") else None,
                            "tenant_key": execution.tenant_key,
                            "project_id": job.project_id,
                            "agent_display_name": execution.agent_display_name,
                            "agent_name": execution.agent_name,
                            "mission": job.mission,
                            "status": execution.status,
                            "progress": execution.progress if hasattr(execution, "progress") else 0,
                            "context_chunks": [],
                            "created_at": job.created_at.isoformat() if job.created_at else None,
                            "started_at": execution.started_at.isoformat() if execution.started_at else None,
                            "priority": "normal",
                        }
                    )

                return PendingJobsResult(jobs=formatted_jobs, count=len(formatted_jobs))

        except ValidationError:
            raise
        except Exception as e:
            self._logger.exception("Failed to get pending jobs")
            raise DatabaseError(
                message=f"Failed to get pending jobs: {e!s}",
                context={"agent_display_name": agent_display_name, "tenant_key": tenant_key},
            ) from e


    async def complete_job(
        self,
        job_id: str,
        result: dict[str, Any],
        tenant_key: str | None = None,
        acknowledge_closeout_todo: bool = False,
        acknowledge_messages_on_complete: bool = False,
    ) -> CompleteJobResult:
        return await self._job_completion.complete_job(
            job_id,
            result,
            tenant_key,
            acknowledge_closeout_todo=acknowledge_closeout_todo,
            acknowledge_messages_on_complete=acknowledge_messages_on_complete,
        )

    async def get_agent_result(self, job_id: str, tenant_key: str | None = None) -> dict | None:
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
        return await self._job_query.list_jobs(tenant_key, project_id, status_filter, agent_display_name, limit, offset)

    async def get_job_detail(self, job_id: str, tenant_key: str) -> dict:
        return await self._job_query.get_job_detail(tenant_key=tenant_key, job_id=job_id)


    @staticmethod
    async def health_check() -> dict[str, Any]:
        from giljo_mcp import branding
        from giljo_mcp.services.version_service import get_installed_version
        from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

        return {
            "status": "healthy",
            "server": branding.MCP_ALIAS,
            "version": get_installed_version(),
            "skills_version": SKILLS_VERSION,
            "timestamp": datetime.now(UTC).isoformat(),
            "database": "connected",
            "message": f"{branding.PRODUCT_NAME} server is operational",
        }

