# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import (
    AlreadyExistsError,
    BaseGiljoError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository
from giljo_mcp.schemas.service_responses import (
    AgentStatusChangeEvent,
    ProjectCompleteResult,
    ProjectData,
    ProjectResumeResult,
)
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.closeout_ws_broadcast import broadcast_agent_status_events
from giljo_mcp.services.project_helpers import _build_ws_project_data, mark_chain_member_status
from giljo_mcp.services.project_lifecycle_service._orchestrator_fixture_mixin import OrchestratorFixtureMixin
from giljo_mcp.services.sequence_run_service import broadcast_deferred_sequence_updates
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ProjectLifecycleService(OrchestratorFixtureMixin):

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
        self._repo = ProjectLifecycleRepository()

        from giljo_mcp.services.project_staging_service import ProjectStagingService

        self._staging = ProjectStagingService(
            db_manager, tenant_manager, test_session, websocket_manager, lifecycle_service=self
        )

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def activate_project(
        self,
        project_id: str,
        force: bool = False,
        websocket_manager: Any | None = None,
        tenant_key: str | None = None,
    ) -> Project:
        try:
            resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
            async with self._get_session(resolved_tenant) as session:
                project = await self._repo.get_by_id(session, resolved_tenant, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found", context={"project_id": project_id, "tenant_key": resolved_tenant}
                    )

                if project.status != ProjectStatus.INACTIVE and not force:
                    raise ProjectStateError(
                        message=f"Cannot activate project from status '{project.status.value}'",
                        context={"project_id": project_id, "current_status": project.status.value},
                    )

                project.status = ProjectStatus.ACTIVE
                project.updated_at = datetime.now(UTC)

                await session.commit()
                await self._repo.refresh(session, project)

                self._logger.info(f"Activated project {sanitize(project_id)}")

                ws_mgr = websocket_manager or self._websocket_manager
                if ws_mgr:
                    try:
                        await ws_mgr.broadcast_project_update(
                            project_id=project.id,
                            update_type="status_changed",
                            project_data=_build_ws_project_data(project),
                            tenant_key=project.tenant_key,
                        )
                    except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                        self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

                await self._ensure_orchestrator_fixture(
                    session=session,
                    project=project,
                    websocket_manager=ws_mgr,
                )

                return project

        except (ResourceNotFoundError, ProjectStateError):
            raise
        except IntegrityError as e:
            if "idx_project_single_active_per_product" in str(e):
                raise AlreadyExistsError(
                    message=(
                        "Another project is already active for this product. "
                        "Deactivate it first, or use the activate endpoint, "
                        "which handles this automatically."
                    ),
                    error_code="ANOTHER_PROJECT_ACTIVE",
                    context={"project_id": project_id},
                ) from e
            self._logger.exception("Failed to activate project")
            raise BaseGiljoError(
                message=f"Failed to activate project: {e!s}", context={"project_id": project_id}
            ) from e
        except Exception as e:
            self._logger.exception("Failed to activate project")
            raise BaseGiljoError(
                message=f"Failed to activate project: {e!s}", context={"project_id": project_id}
            ) from e

    async def deactivate_project(
        self,
        project_id: str,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
    ) -> Project:
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        async with self._get_session(resolved_tenant) as session:
            project = await self._repo.get_by_id(session, resolved_tenant, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found or access denied",
                    context={"project_id": project_id, "tenant_key": resolved_tenant},
                )

            if project.status != ProjectStatus.ACTIVE:
                raise ProjectStateError(
                    message=f"Cannot deactivate project with status '{project.status.value}'",
                    context={"project_id": project_id, "current_status": project.status.value},
                )

            removed = await self._maybe_reset_never_run_orchestrator(session, resolved_tenant, project)

            project.status = ProjectStatus.INACTIVE
            project.updated_at = datetime.now(UTC)

            await session.commit()
            await self._repo.refresh(session, project)

            self._logger.info(
                "Deactivated project %s%s",
                sanitize(project_id),
                f" ({len(removed)} never-run orchestrator row(s) deleted)" if removed else "",
            )

            ws_mgr = websocket_manager or self._websocket_manager
            if ws_mgr:
                try:
                    await ws_mgr.broadcast_project_update(
                        project_id=project.id,
                        update_type="status_changed",
                        project_data=_build_ws_project_data(project),
                        tenant_key=project.tenant_key,
                    )
                except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                    self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

            await self._broadcast_agents_removed(
                ws_mgr, resolved_tenant, project_id, removed, product_id=project.product_id
            )

            return project

    async def terminate_project(
        self,
        project_id: str,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
    ) -> Project:
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        async with self._get_session(resolved_tenant) as session:
            project = await self._repo.get_by_id(session, resolved_tenant, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found or access denied",
                    context={"project_id": project_id, "tenant_key": resolved_tenant},
                )

            if project.status == ProjectStatus.TERMINATED:
                return project

            stood_down = await self._repo.stand_down_project_agents(session, resolved_tenant, project_id)

            project.status = ProjectStatus.TERMINATED
            project.updated_at = datetime.now(UTC)

            await session.commit()
            await self._repo.refresh(session, project)

            self._logger.info(
                "Terminated project %s (agent jobs=%d, executions=%d stood down; no rows deleted)",
                sanitize(project_id),
                stood_down["jobs"],
                stood_down["executions"],
            )

            ws_mgr = websocket_manager or self._websocket_manager
            if ws_mgr:
                try:
                    await ws_mgr.broadcast_project_update(
                        project_id=project.id,
                        update_type="status_changed",
                        project_data=_build_ws_project_data(project),
                        tenant_key=project.tenant_key,
                    )
                except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                    self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

            return project

    def check_staging_allowed(self, project: Project) -> None:
        self._staging.check_staging_allowed(project)

    async def restage(self, project_id: str) -> dict:
        return await self._staging.restage(project_id)

    async def reset_to_prestage(self, project_id: str, tenant_key: str | None = None) -> dict:
        return await self._staging.reset_to_prestage(project_id, tenant_key=tenant_key)

    async def unstage(self, project_id: str) -> dict:
        return await self._staging.unstage(project_id)

    async def mark_staged(
        self, project_id: str, execution_mode: str, tenant_key: str | None = None, db_session: Any | None = None
    ) -> None:
        await self._staging.mark_staged(project_id, execution_mode, tenant_key=tenant_key, db_session=db_session)

    async def cancel_staging(self, project_id: str, websocket_manager: Any | None = None) -> ProjectData:
        return await self._staging.cancel_staging(project_id, websocket_manager)

    async def complete_project(
        self,
        project_id: str,
        summary: str,
        key_outcomes: list[str],
        decisions_made: list[str],
        tenant_key: str | None = None,
        db_session: Any | None = None,
        git_commits: list[dict] | None = None,
        decommission_events_out: list[AgentStatusChangeEvent] | None = None,
    ) -> ProjectCompleteResult:
        try:
            resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
            if not resolved_tenant:
                raise ValidationError(message="Tenant not set", context={"operation": "complete_project"})

            if not summary or not summary.strip():
                raise ValidationError(
                    message="Summary is required", context={"operation": "complete_project", "project_id": project_id}
                )

            owns_session = db_session is None

            if owns_session:
                async with self._get_session(resolved_tenant) as session:
                    return await self._complete_project_transaction(
                        session=session,
                        project_id=project_id,
                        tenant_key=resolved_tenant,
                        summary=summary,
                        key_outcomes=key_outcomes,
                        decisions_made=decisions_made,
                        git_commits=git_commits,
                        commit=owns_session,
                    )

            return await self._complete_project_transaction(
                session=db_session,
                project_id=project_id,
                tenant_key=resolved_tenant,
                summary=summary,
                key_outcomes=key_outcomes,
                decisions_made=decisions_made,
                git_commits=git_commits,
                commit=False,
                decommission_events_out=decommission_events_out,
            )

        except ValidationError:
            raise
        except Exception as e:
            self._logger.exception("Failed to complete project")
            raise BaseGiljoError(
                message=f"Failed to complete project: {e!s}",
                context={"project_id": project_id, "tenant_key": tenant_key},
            ) from e

    async def _complete_project_transaction(
        self,
        session: AsyncSession,
        project_id: str,
        tenant_key: str,
        summary: str,
        key_outcomes: list[str],
        decisions_made: list[str],
        commit: bool,
        git_commits: list[dict] | None = None,
        decommission_events_out: list[AgentStatusChangeEvent] | None = None,
    ) -> ProjectCompleteResult:
        now = datetime.now(UTC)

        project = await self._repo.get_by_id(session, tenant_key, project_id)

        if not project:
            raise ResourceNotFoundError(
                message="Project not found or access denied",
                context={"project_id": project_id, "tenant_key": tenant_key},
            )

        project.status = ProjectStatus.COMPLETED
        project.completed_at = now
        project.updated_at = now
        project.closeout_executed_at = now
        project.orchestrator_summary = summary

        await mark_chain_member_status(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            project_id=project_id,
            tenant_key=tenant_key,
            status="completed",
            test_session=session,
            websocket_manager=self._websocket_manager,
        )

        from giljo_mcp.tools.project_closeout import close_project_and_update_memory

        decommission_events: list[AgentStatusChangeEvent] = []

        try:
            mcp_result = await close_project_and_update_memory(
                project_id=project_id,
                summary=summary,
                key_outcomes=key_outcomes or [],
                decisions_made=decisions_made or [],
                tenant_key=tenant_key,
                db_manager=self.db_manager,
                session=session,
                force=True,
                git_commits=git_commits or None,
                decommission_events_out=decommission_events,
            )
        except (ResourceNotFoundError, ValidationError, ProjectStateError, OSError):
            self._logger.exception("MCP tool call failed")
            memory_updated = False
            sequence_number = 0
            git_commits_count = 0
        else:
            if mcp_result.get("success") is False:
                raise ValidationError(
                    message=mcp_result.get("message") or "Project closeout was rejected",
                    error_code=mcp_result.get("error", "PROJECT_CLOSEOUT_REJECTED"),
                    context={"project_id": project_id, "hint": mcp_result.get("hint")},
                )
            memory_updated = True
            sequence_number = mcp_result.get("sequence_number", 0)
            git_commits_count = mcp_result.get("git_commits_count", 0)

        if commit:
            await session.commit()
            await broadcast_deferred_sequence_updates(session)

            if decommission_events:
                await broadcast_agent_status_events(
                    self._websocket_manager,
                    tenant_key=tenant_key,
                    project_id=project_id,
                    product_id=project.product_id,
                    events=decommission_events,
                )
        elif decommission_events and decommission_events_out is not None:
            decommission_events_out.extend(decommission_events)

        ws_mgr = self._websocket_manager
        if ws_mgr:
            try:
                await ws_mgr.broadcast_project_update(
                    project_id=project_id,
                    update_type="status_changed",
                    project_data={
                        "name": project.name,
                        "status": "completed",
                        "mission": project.mission,
                        "product_id": project.product_id,
                    },
                    tenant_key=tenant_key,
                )
            except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

        await self._broadcast_memory_update(
            project_id=project_id,
            project_name=project.name,
            sequence_number=sequence_number,
            summary=summary,
            tenant_key=tenant_key,
        )

        return ProjectCompleteResult(
            message=f"Project {project_id} completed successfully",
            memory_updated=memory_updated,
            sequence_number=sequence_number,
            git_commits_count=git_commits_count,
        )

    async def cancel_project(self, project_id: str, tenant_key: str, reason: str | None = None) -> None:
        try:
            async with self._get_session(tenant_key) as session:
                rowcount = await self._repo.cancel_project(session, tenant_key, project_id, reason)

                if rowcount == 0:
                    raise ResourceNotFoundError(
                        message="Project not found or access denied",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )

                await session.commit()

                self._logger.info(f"Cancelled project {project_id}")

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to cancel project")
            raise BaseGiljoError(message=f"Failed to cancel project: {e!s}", context={"project_id": project_id}) from e

    async def continue_working(self, project_id: str, tenant_key: str) -> ProjectResumeResult:
        try:
            async with self._get_session(tenant_key) as session:
                project = await self._repo.get_by_id(session, tenant_key, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found or access denied",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )

                if project.status != ProjectStatus.COMPLETED:
                    raise ProjectStateError(
                        message=f"Cannot resume project from status '{project.status.value}'. Project must be completed.",
                        context={"project_id": project_id, "current_status": project.status.value},
                    )

                project.status = ProjectStatus.INACTIVE
                project.completed_at = None
                project.updated_at = datetime.now(UTC)

                executions_to_resume = await self._repo.find_decommissioned_executions(session, tenant_key, project_id)
                resumed_ids = []

                for execution in executions_to_resume:
                    execution.status = "waiting"
                    execution.updated_at = datetime.now(UTC)
                    resumed_ids.append(execution.job_id)

                await session.commit()

                self._logger.info(f"Resumed project {project_id} with {len(resumed_ids)} agents resumed")

                ws_mgr = self._websocket_manager
                if ws_mgr:
                    try:
                        await ws_mgr.broadcast_project_update(
                            project_id=project_id,
                            update_type="status_changed",
                            project_data={
                                "name": project.name,
                                "status": ProjectStatus.INACTIVE.value,
                                "mission": project.mission,
                                "product_id": project.product_id,
                            },
                            tenant_key=tenant_key,
                        )
                    except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                        self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

                return ProjectResumeResult(
                    message="Project resumed successfully",
                    agents_resumed=len(resumed_ids),
                    resumed_agent_ids=resumed_ids,
                    project_status=ProjectStatus.INACTIVE.value,
                )

        except (ResourceNotFoundError, ProjectStateError):
            raise
        except Exception as e:
            self._logger.exception("Failed to resume project")
            raise BaseGiljoError(
                message=f"Failed to resume project: {e!s}", context={"project_id": project_id, "tenant_key": tenant_key}
            ) from e

    async def _broadcast_memory_update(
        self,
        project_id: str,
        project_name: str,
        sequence_number: int,
        summary: str,
        tenant_key: str,
    ) -> None:
        self._logger.info(
            f"[WEBSOCKET DEBUG] Broadcasting memory update for project {sanitize(project_id)} (sequence: {sequence_number})"
        )

        if not self._websocket_manager:
            self._logger.debug("[WEBSOCKET] No WebSocket manager available for project:memory_updated")
            return

        summary_preview = (summary[:200] + "...") if len(summary) > 200 else summary

        try:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="project:memory_updated",
                data={
                    "project_id": project_id,
                    "project_name": project_name,
                    "sequence_number": sequence_number,
                    "summary_preview": summary_preview,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as ws_error:
            self._logger.error(
                f"[WEBSOCKET ERROR] Failed to broadcast project:memory_updated: {ws_error}",
                exc_info=True,
            )
