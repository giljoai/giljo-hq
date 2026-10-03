# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import (
    ImplementationNotReadyError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.service_responses import ProjectData
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.comm_thread_enrolment import project_thread_ref
from giljo_mcp.services.next_action import STAGING_COMPLETE
from giljo_mcp.services.project_helpers import (
    _build_ws_project_data,
    advance_chain_member_to_implementing,
    stamp_launch,
)
from giljo_mcp.services.sequence_chain_context import chain_predecessor_open_error, resolve_chain_launch_gate
from giljo_mcp.services.sequence_run_service import broadcast_deferred_sequence_updates
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ProjectStagingService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        test_session: AsyncSession | None = None,
        websocket_manager: Any | None = None,
        lifecycle_service: Any | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._lifecycle = lifecycle_service
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._project_repo = ProjectRepository()
        self._lifecycle_repo = ProjectLifecycleRepository()

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._test_session
        )

    def check_staging_allowed(self, project: Project) -> None:
        if project.staging_status == "staging":
            raise ProjectStateError(
                message="Staging already in progress. Use Re-Stage to reset first.",
                context={"project_id": project.id, "staging_status": project.staging_status},
            )

    @staticmethod
    def check_implementation_allowed(project: Project) -> None:
        if project.staging_status != STAGING_COMPLETE:
            raise ImplementationNotReadyError(
                reason="staging_incomplete",
                message="No orchestrator found for this project. Please ensure staging has been completed.",
                context={"project_id": project.id, "staging_status": project.staging_status},
            )
        if project.implementation_launched_at is None:
            raise ImplementationNotReadyError(
                reason="not_launched",
                message="Implementation has not been launched yet for this project.",
                context={"project_id": project.id},
            )

    async def restage(self, project_id: str) -> dict:
        tenant_key = self.tenant_manager.get_current_tenant()

        async with self._get_session() as session:
            project = await self._project_repo.get_by_id(session, tenant_key, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found",
                    context={"project_id": project_id},
                )

            if project.staging_status not in ("staging", STAGING_COMPLETE):
                raise ProjectStateError(
                    message="Project is not currently staged",
                    context={
                        "project_id": project_id,
                        "staging_status": project.staging_status,
                    },
                )

            if project.staging_status == STAGING_COMPLETE and project.implementation_launched_at is not None:
                raise ProjectStateError(
                    message="Cannot recover mode: implementation already launched",
                    context={
                        "project_id": project_id,
                        "staging_status": project.staging_status,
                    },
                )

            orchestrator = await self._lifecycle_repo.find_existing_orchestrator(session, tenant_key, project_id)

            if orchestrator and orchestrator.status not in ("waiting", "complete"):
                raise ProjectStateError(
                    message="Cannot restage: orchestrator agent is already active",
                    context={
                        "project_id": project_id,
                        "orchestrator_status": orchestrator.status,
                    },
                )

            project.staging_status = None
            project.mission = ""
            project.implementation_launched_at = None
            project.updated_at = datetime.now(UTC)

            if orchestrator:
                orchestrator.status = "decommissioned"

            await session.commit()

            new_fixture = await self._lifecycle._ensure_orchestrator_fixture(session, project)

            self._logger.info(
                "[RESTAGE] Project %s restaged, new orchestrator: %s",
                project_id,
                new_fixture,
            )

            return {
                "message": "Project restaged successfully",
                "project_id": project.id,
                "new_orchestrator": new_fixture,
            }

    async def reset_to_prestage(self, project_id: str, tenant_key: str | None = None) -> dict:
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()

        async with self._get_session(effective_tenant_key) as session:
            project = await self._project_repo.get_by_id(session, effective_tenant_key, project_id)
            if not project:
                raise ResourceNotFoundError(message="Project not found", context={"project_id": project_id})

            project.staging_status = None
            project.mission = ""
            project.implementation_launched_at = None
            project.ever_launched_at = None
            project.status = ProjectStatus.INACTIVE
            project.updated_at = datetime.now(UTC)

            deleted = await self._lifecycle_repo.delete_all_agent_state_for_project(
                session, effective_tenant_key, project_id
            )
            await session.commit()

            self._logger.info("[RESET] Project %s reset to pre-stage; deleted %s", project_id, deleted)
            return {
                "message": "Project reset to original state",
                "project_id": project.id,
                "deleted": deleted,
            }

    async def unstage(self, project_id: str) -> dict:
        tenant_key = self.tenant_manager.get_current_tenant()

        async with self._get_session() as session:
            project = await self._project_repo.get_by_id(session, tenant_key, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found",
                    context={"project_id": project_id},
                )

            if project.staging_status != "staged":
                raise ProjectStateError(
                    message="Project is not in staged state. Cannot unstage.",
                    context={
                        "project_id": project_id,
                        "staging_status": project.staging_status,
                    },
                )

            project.staging_status = None
            project.mission = ""
            project.updated_at = datetime.now(UTC)
            await session.commit()

            self._logger.info("[UNSTAGE] Project %s unstaged", project_id)

            return {
                "message": "Project unstaged successfully",
                "project_id": project.id,
            }

    async def mark_staged(
        self,
        project_id: str,
        execution_mode: str,
        tenant_key: str | None = None,
        db_session: AsyncSession | None = None,
    ) -> None:
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        if not resolved_tenant:
            raise ValidationError(
                message="Tenant not set", context={"operation": "mark_staged", "project_id": project_id}
            )

        owns_session = db_session is None
        if owns_session:
            async with self._get_session(resolved_tenant) as session:
                await self._mark_staged_transaction(session, resolved_tenant, project_id, execution_mode)
        else:
            await self._mark_staged_transaction(db_session, resolved_tenant, project_id, execution_mode)

    async def _mark_staged_transaction(
        self, session: AsyncSession, tenant_key: str, project_id: str, execution_mode: str
    ) -> None:
        project = await self._project_repo.get_by_id(session, tenant_key, project_id)

        if not project:
            raise ResourceNotFoundError(
                message="Project not found",
                context={"project_id": project_id},
            )

        project.staging_status = "staged"
        if project.implementation_launched_at is None:
            project.execution_mode = execution_mode
        project.updated_at = datetime.now(UTC)

        await session.commit()

        self._logger.info("[MARK_STAGED] Project %s marked staged", project_id)

    async def launch_implementation(
        self,
        project_id: str,
        tenant_key: str | None = None,
        launched_by: str | None = None,
        websocket_manager: Any | None = None,
        origin: str | None = None,
    ) -> dict[str, Any]:
        effective_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        ws = websocket_manager or self._websocket_manager

        async with self._get_session(effective_tenant) as session:
            project = await self._project_repo.get_by_id(session, effective_tenant, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found",
                    context={"project_id": project_id},
                )

            already_launched = project.implementation_launched_at is not None

            if not already_launched:
                is_chain_member, blocking_predecessor = await resolve_chain_launch_gate(
                    session, project_id=project_id, tenant_key=effective_tenant
                )
                if blocking_predecessor is not None:
                    raise chain_predecessor_open_error(project, blocking_predecessor)

                if not is_chain_member and project.staging_status != STAGING_COMPLETE:
                    raise ImplementationNotReadyError(
                        reason="staging_incomplete",
                        message=(
                            "Cannot launch implementation: project staging is not complete. "
                            "Complete this project's staging first (drive it to staging_complete "
                            "via the staging-end complete_job), then launch_implementation."
                        ),
                        context={"project_id": project.id, "staging_status": project.staging_status},
                    )

                stamp_launch(project)

                await self._advance_chain_on_launch(session, project_id, effective_tenant, websocket_manager=ws)
                await session.commit()
                await broadcast_deferred_sequence_updates(session)
                await self._project_repo.refresh(session, project)

            launched_at_iso = project.implementation_launched_at.isoformat()
            project_active = project.status == ProjectStatus.ACTIVE
            product_id = project.product_id
            thread_ref = await project_thread_ref(session, effective_tenant, project_id)

            self._logger.info(
                "[LAUNCH_IMPL] Project %s implementation launched (already_launched=%s) by %s",
                sanitize(project_id),
                already_launched,
                launched_by or "unknown",
            )

        await self._broadcast_launch_event(
            ws,
            tenant_key=effective_tenant,
            project_id=project_id,
            product_id=product_id,
            launched_at_iso=launched_at_iso,
            origin=origin,
        )

        result: dict[str, Any] = {
            "success": True,
            "implementation_launched_at": launched_at_iso,
            "already_launched": already_launched,
            "launched_at": launched_at_iso,
            "project_active": project_active,
            **thread_ref,
        }
        if not project_active:
            result["next_action"] = (
                "The implementation gate is open, but this project is not active, so the "
                "dashboard Jobs view does not show it. Launching activates an inactive project "
                "when the gate is first crossed; this one was launched earlier or holds another "
                "status. To show the run: update_project(project_id, status='active') from the "
                "harness, or the Activate control on the project in the dashboard."
            )
        return result

    async def _broadcast_launch_event(
        self,
        ws: Any | None,
        *,
        tenant_key: str,
        project_id: str,
        product_id: str | None,
        launched_at_iso: str,
        origin: str | None,
    ) -> None:
        if not ws:
            return
        payload: dict[str, Any] = {
            "project_id": project_id,
            "product_id": product_id,
            "implementation_launched_at": launched_at_iso,
        }
        if origin is not None:
            payload["source"] = origin
        await ws.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type="project:implementation_launched",
            data=payload,
        )

    async def _advance_chain_on_launch(
        self,
        session: AsyncSession,
        project_id: str,
        tenant_key: str,
        websocket_manager: Any | None = None,
    ) -> None:
        await advance_chain_member_to_implementing(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            project_id=project_id,
            tenant_key=tenant_key,
            session=session,
            websocket_manager=websocket_manager,
        )

    async def cancel_staging(self, project_id: str, websocket_manager: Any | None = None) -> ProjectData:
        async with self._get_session() as session:
            project = await self._project_repo.get_by_id(session, self.tenant_manager.get_current_tenant(), project_id)

            if not project:
                raise ResourceNotFoundError(message="Project not found", context={"project_id": project_id})

            if project.staging_status != "staging" or project.status != ProjectStatus.INACTIVE:
                raise ProjectStateError(
                    message=(
                        f"Cannot cancel staging: project status='{project.status.value}', "
                        f"staging_status='{project.staging_status}' (need INACTIVE + staging)"
                    ),
                    context={
                        "project_id": project_id,
                        "current_status": project.status.value,
                        "staging_status": project.staging_status,
                    },
                )

            project.status = ProjectStatus.CANCELLED
            project.completed_at = datetime.now(UTC)
            project.updated_at = datetime.now(UTC)

            await session.commit()
            await self._project_repo.refresh(session, project)

            self._logger.info(f"Cancelled staging for project {project_id}")

            if websocket_manager:
                await websocket_manager.broadcast_project_update(
                    project_id=project.id,
                    update_type="cancelled",
                    project_data=_build_ws_project_data(project),
                    tenant_key=project.tenant_key,
                )

            return ProjectData(
                id=project.id,
                name=project.name,
                status=project.status,
                mission=project.mission,
                description=project.description,
                cancellation_reason=project.cancellation_reason,
                early_termination=project.early_termination,
                created_at=project.created_at.isoformat() if project.created_at else None,
                updated_at=project.updated_at.isoformat() if project.updated_at else None,
                completed_at=project.completed_at.isoformat() if project.completed_at else None,
                product_id=project.product_id,
            )
