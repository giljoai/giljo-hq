# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.jsonb_validators import validate_agent_job_metadata
from giljo_mcp.schemas.service_responses import ProjectLaunchResult
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.project_helpers import _build_ws_project_data
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ProjectLaunchService:

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
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def launch_project(
        self,
        project_id: str,
        user_id: str | None = None,
        launch_config: dict[str, Any | None] = None,
        websocket_manager: Any | None = None,
        project_service: Any | None = None,
    ) -> ProjectLaunchResult:
        tenant_key = self.tenant_manager.get_current_tenant()

        async with self._get_session(tenant_key) as session:
            project = await self._validate_launch_preconditions(
                session, project_id, tenant_key, websocket_manager, project_service
            )

            field_toggles, depth_config = await self._resolve_user_config(session, user_id, tenant_key)

            existing = await self._lifecycle_repo.find_non_decommissioned_orchestrator(session, tenant_key, project_id)
            if existing:
                return self._build_reuse_result(project, existing)

            return await self._spawn_orchestrator(
                session,
                project,
                project_id,
                tenant_key,
                field_toggles,
                depth_config,
                user_id,
                websocket_manager,
            )

    async def _validate_launch_preconditions(
        self,
        session: AsyncSession,
        project_id: str,
        tenant_key: str,
        websocket_manager: Any | None,
        project_service: Any | None,
    ) -> Project:
        project = await self._project_repo.get_by_id(session, tenant_key, project_id)

        if not project:
            raise ResourceNotFoundError(
                message="Project not found",
                context={"project_id": project_id},
            )

        if project.status != ProjectStatus.ACTIVE and project_service:
            await project_service.activate_project(project_id, websocket_manager=websocket_manager)

        return project

    async def _resolve_user_config(
        self,
        session: AsyncSession,
        user_id: str | None,
        tenant_key: str,
    ) -> tuple[dict, dict]:
        field_toggles: dict = {}
        depth_config: dict | None = None

        if user_id:
            user = await self._lifecycle_repo.get_user(session, tenant_key, user_id)

            if user:
                rows = await self._lifecycle_repo.get_user_field_priorities(session, tenant_key, user_id)
                if rows:
                    from giljo_mcp.config.defaults import DEFAULT_CATEGORY_TOGGLES

                    field_toggles = dict(DEFAULT_CATEGORY_TOGGLES)
                    for row in rows:
                        field_toggles[row.category] = row.enabled
                    field_toggles["product_core"] = True
                    field_toggles["project_description"] = True

                depth_config = {
                    "vision_documents": user.depth_vision_documents,
                    "memory_last_n_projects": user.depth_memory_last_n,
                    "git_commits": user.depth_git_commits,
                    "agent_templates": user.depth_agent_templates,
                    "tech_stack_sections": user.depth_tech_stack_sections,
                    "architecture_depth": user.depth_architecture,
                }

        if not depth_config:
            depth_config = {
                "vision_documents": "medium",
                "memory_last_n_projects": 3,
                "git_commits": 25,
                "agent_templates": "basic",
                "tech_stack_sections": "all",
                "architecture_depth": "overview",
            }

        return field_toggles, depth_config

    def _build_reuse_result(self, project: Project, existing: AgentExecution) -> ProjectLaunchResult:
        self._logger.info(
            f"[LAUNCH] Reusing existing orchestrator {existing.job_id} "
            f"for project {project.id} (status={existing.status})"
        )

        return ProjectLaunchResult(
            project_id=project.id,
            orchestrator_job_id=existing.job_id,
            launch_prompt=self._generate_launch_prompt(project.name, project.id, project.mission, existing.job_id),
            status=project.status,
            staging_status=project.staging_status,
        )

    async def _spawn_orchestrator(
        self,
        session: AsyncSession,
        project: Project,
        project_id: str,
        tenant_key: str,
        field_toggles: dict,
        depth_config: dict,
        user_id: str | None,
        websocket_manager: Any | None,
    ) -> ProjectLaunchResult:
        orchestrator_job_id = str(uuid4())

        agent_job = AgentJob(
            job_id=orchestrator_job_id,
            tenant_key=tenant_key,
            project_id=project_id,
            mission=project.mission or f"Orchestrator mission for project: {project.name}",
            job_type="orchestrator",
            status="active",
            job_metadata=validate_agent_job_metadata(
                {
                    "field_toggles": field_toggles,
                    "depth_config": depth_config,
                    "user_id": user_id,
                    "created_via": "project_launch_service",
                }
            ),
        )
        await self._lifecycle_repo.add_entity(session, agent_job)

        agent_execution = AgentExecution(
            agent_id=str(uuid4()),
            job_id=orchestrator_job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
            progress=0,
            health_status="unknown",
            project_phase="staging",
        )
        await self._lifecycle_repo.add_entity(session, agent_execution)

        project.staging_status = "staging"
        project.updated_at = datetime.now(UTC)

        await self._lifecycle_repo.flush(session)

        launch_prompt = self._generate_launch_prompt(project.name, project.id, project.mission, orchestrator_job_id)

        await session.commit()

        self._logger.info(
            f"Launched project {sanitize(project_id)} with orchestrator job {sanitize(orchestrator_job_id)}"
        )

        if websocket_manager:
            project_data = _build_ws_project_data(project)
            project_data["staging_status"] = project.staging_status
            project_data["orchestrator_job_id"] = orchestrator_job_id
            await websocket_manager.broadcast_project_update(
                project_id=project.id,
                update_type="launched",
                project_data=project_data,
                tenant_key=project.tenant_key,
            )

        return ProjectLaunchResult(
            project_id=project.id,
            orchestrator_job_id=orchestrator_job_id,
            launch_prompt=launch_prompt,
            status=project.status,
            staging_status=project.staging_status,
        )

    @staticmethod
    def _generate_launch_prompt(project_name: str, project_id: str, mission: str | None, job_id: str) -> str:
        return f"""Launch orchestrator for project: {project_name}

Project ID: {project_id}
Mission: {mission}
Orchestrator Job ID: {job_id}

This is a thin-client launch. Use the get_staging_instructions() MCP tool to fetch full mission details.
"""
