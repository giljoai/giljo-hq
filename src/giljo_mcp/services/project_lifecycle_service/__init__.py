# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProjectLifecycleService - Extracted from ProjectService (Handover 0769).

Handles project lifecycle state transitions:
- activate, deactivate, cancel_staging
- complete, cancel, continue_working
"""

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
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ProjectLifecycleService(OrchestratorFixtureMixin):
    """Service for project lifecycle state transitions."""

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
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def activate_project(
        self,
        project_id: str,
        force: bool = False,
        websocket_manager: Any | None = None,
        tenant_key: str | None = None,
    ) -> Project:
        """
        Activate a project.

        State Transitions:
        - staging -> active (initial launch)
        - inactive -> active (activate/resume)

        Ruling 5 amended (D5, 2026-08-28): N projects may be active per product.
        Activating this project no longer touches any other project's status.

        Args:
            project_id: Project UUID
            force: If True, skip validation checks (default: False)
            websocket_manager: Optional WebSocket manager for real-time updates
            tenant_key: Optional tenant key (uses current tenant if not provided)

        Returns:
            Project: The activated project instance

        Raises:
            ResourceNotFoundError: When project not found
            ProjectStateError: When invalid state transition
            BaseGiljoError: When operation fails

        Example:
            >>> project = await service.activate_project("abc-123")
            >>> assert project.status == "active"
        """
        try:
            resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
            async with self._get_session(resolved_tenant) as session:
                # Fetch project
                project = await self._repo.get_by_id(session, resolved_tenant, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found", context={"project_id": project_id, "tenant_key": resolved_tenant}
                    )

                # Validate state transition.
                # BE-5039 Phase 2b: ``staging`` is no longer a canonical
                # value -- the Postgres ENUM cannot persist it and the
                # codebase never wrote it. Only ``INACTIVE`` is a valid
                # source state for activation.
                if project.status != ProjectStatus.INACTIVE and not force:
                    raise ProjectStateError(
                        message=f"Cannot activate project from status '{project.status.value}'",
                        context={"project_id": project_id, "current_status": project.status.value},
                    )

                # Activate project
                project.status = ProjectStatus.ACTIVE
                project.updated_at = datetime.now(UTC)

                await session.commit()
                await self._repo.refresh(session, project)

                self._logger.info(f"Activated project {sanitize(project_id)}")

                # Broadcast WebSocket event if manager provided
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

                # Handover 0431: Create orchestrator fixture on project activation
                # This ensures orchestrator appears in UI before "Stage Project" is clicked
                await self._ensure_orchestrator_fixture(
                    session=session,
                    project=project,
                    websocket_manager=ws_mgr,
                )

                return project

        except (ResourceNotFoundError, ProjectStateError):
            # Re-raise our custom exceptions
            raise
        except IntegrityError as e:
            # BE-9519, kept unreachable-but-harmless per BE-9525b: this branch
            # mapped a unique-index violation on
            # idx_project_single_active_per_product to a clean
            # ANOTHER_PROJECT_ACTIVE rejection. BE-9525b (ruling 5 amended)
            # dropped that index and the deactivate-then-activate ordering
            # above, so this string match can no longer fire -- Postgres will
            # never raise this IntegrityError again. Left in place rather than
            # deleted: removing a weeks-old incident-fix catch is a separate
            # cleanup with its own zero-reachability proof, not bundled here.
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
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
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
        """
        Deactivate an active project.

        State Transition: active -> inactive

        Args:
            project_id: Project UUID
            tenant_key: Optional tenant key (uses current tenant if not provided)
            websocket_manager: Optional WebSocket manager for real-time updates

        Returns:
            Project: The deactivated project instance

        Raises:
            ResourceNotFoundError: Project not found
            ProjectStateError: Cannot deactivate project with current status

        Example:
            >>> project = await service.deactivate_project("abc-123")
            >>> assert project.status == "inactive"
        """
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        async with self._get_session(resolved_tenant) as session:
            # Fetch project
            project = await self._repo.get_by_id(session, resolved_tenant, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found or access denied",
                    context={"project_id": project_id, "tenant_key": resolved_tenant},
                )

            # Validate state
            if project.status != ProjectStatus.ACTIVE:
                raise ProjectStateError(
                    message=f"Cannot deactivate project with status '{project.status.value}'",
                    context={"project_id": project_id, "current_status": project.status.value},
                )

            # BE-6085/BE-6123: conditionally DELETE a NEVER-RUN orchestrator so a
            # wedged project becomes re-stageable without accumulating tombstones.
            # Runs in THIS transaction, before the commit below. The ELSE
            # (orchestrator ran or has subagents) leaves agent state untouched --
            # today's behavior, load-bearing.
            removed = await self._maybe_reset_never_run_orchestrator(session, resolved_tenant, project)

            # Deactivate project
            project.status = ProjectStatus.INACTIVE
            project.updated_at = datetime.now(UTC)

            await session.commit()
            await self._repo.refresh(session, project)

            self._logger.info(
                "Deactivated project %s%s",
                sanitize(project_id),
                f" ({len(removed)} never-run orchestrator row(s) deleted)" if removed else "",
            )

            # Broadcast WebSocket event
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

            # BE-6123: tell open dashboards to drop the deleted rows live. Emitted
            # post-commit (TRANSACTION_OWNERSHIP_CONVENTION) so a failed commit
            # never produces a phantom removal; WS failure must not fail the op.
            await self._broadcast_agents_removed(
                ws_mgr, resolved_tenant, project_id, removed, product_id=project.product_id
            )

            return project

    def check_staging_allowed(self, project: Project) -> None:
        """Facade: delegates to ProjectStagingService."""
        self._staging.check_staging_allowed(project)

    async def restage(self, project_id: str) -> dict:
        """Facade: delegates to ProjectStagingService."""
        return await self._staging.restage(project_id)

    async def reset_to_prestage(self, project_id: str, tenant_key: str | None = None) -> dict:
        """Facade: delegates to ProjectStagingService (FE-6180 destructive reset)."""
        return await self._staging.reset_to_prestage(project_id, tenant_key=tenant_key)

    async def unstage(self, project_id: str) -> dict:
        """Facade: delegates to ProjectStagingService."""
        return await self._staging.unstage(project_id)

    async def mark_staged(
        self, project_id: str, execution_mode: str, tenant_key: str | None = None, db_session: Any | None = None
    ) -> None:
        """Facade: delegates to ProjectStagingService."""
        await self._staging.mark_staged(project_id, execution_mode, tenant_key=tenant_key, db_session=db_session)

    async def cancel_staging(self, project_id: str, websocket_manager: Any | None = None) -> ProjectData:
        """Facade: delegates to ProjectStagingService."""
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
        """
        Mark a project as completed and trigger 360 memory update.

        Args:
            project_id: Project UUID
            summary: Completion summary (required)
            key_outcomes: List of key outcomes/deliverables
            decisions_made: List of decisions captured during project
            db_session: Optional database session (for transaction management)
            git_commits: Optional agent/operator-supplied commits captured at
                closeout. Threaded into write_project_closeout, which
                validates and persists them as structured rows. Omission/None
                yields an empty list (no commits).
            decommission_events_out: BE-9273 out-param for an externally-supplied
                ``db_session`` (this call does not own the commit): if a list is
                passed, the force-decommission events land here instead of being
                silently dropped, so the true commit-owner can broadcast them.
                Unused (no-op) when this call owns its own session.

        Returns:
            ProjectCompleteResult: Completion result with memory update metadata

        Raises:
            ValidationError: When tenant not set or summary missing
            BaseGiljoError: When operation fails
        """
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
            # Re-raise our custom exceptions
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
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
        """
        Complete project within provided session context.

        Raises:
            ResourceNotFoundError: When project not found
        """
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

        # BE-6181 / BE-6198: complete_project is the REST/dashboard closeout path. The MCP
        # write_project_closeout tool path now does its own chain sync inside
        # close_project_and_update_memory (BE-6198) -- it does NOT route through here. Both
        # are real independent entry points, so each marks the chain member "completed" so
        # the C1 conductor guard sees a terminal status and lets the chain finish. This call
        # stays: it is idempotent (mark_chain_member_status no-ops when already at target).
        # Solo (no active run) -> no-op. Best-effort: never fails the closeout transaction.
        await mark_chain_member_status(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            project_id=project_id,
            tenant_key=tenant_key,
            status="completed",
            test_session=self._test_session,
            websocket_manager=self._websocket_manager,
        )

        # Invoke MCP tool to write 360 Memory entry
        from giljo_mcp.tools.project_closeout import close_project_and_update_memory

        # BE-9273: close_project_and_update_memory runs with session=session
        # (owns_session=False from ITS perspective), so it cannot safely
        # broadcast the force-decommission events itself -- commit timing
        # belongs to THIS caller. Collect the raw events here and broadcast
        # them ourselves, below, only after our own commit actually lands.
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
                # BE-9256 fix (adversarial-audit Finding #1): close_project_and_update_memory
                # uses the BE-6081 Tier-2 dict-return carve-out for a deliberate domain
                # rejection (e.g. GIT_COMMIT_TITLE_REQUIRED) instead of raising -- that
                # carve-out is scoped to the @mcp.tool boundary. This is a service-layer
                # caller (the REST /complete endpoint), where post-0480 requires raising on
                # error. Without this check the rejection dict was silently treated as
                # success: project.status committed to COMPLETED with memory_updated=True
                # reported, but zero memory entries were actually written. Raise BEFORE the
                # commit below so the whole transaction (including the status/timestamp
                # mutations above) rolls back -- no partial state persists.
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

            # BE-9273 POST-COMMIT: mirrors the BE-9246 owns_session=True MCP-tool
            # path -- only emit once OUR OWN commit above has actually landed
            # (never mid-flush, so a broadcast can't announce a status a rollback
            # here could still undo).
            if decommission_events:
                await broadcast_agent_status_events(
                    self._websocket_manager,
                    tenant_key=tenant_key,
                    project_id=project_id,
                    product_id=project.product_id,  # BE-9518
                    events=decommission_events,
                )
        elif decommission_events and decommission_events_out is not None:
            # commit=False: an externally-supplied db_session, so this call does
            # NOT own the commit and must never broadcast (same reasoning as
            # close_project_and_update_memory's own owns_session gate). Hand the
            # events to the caller-supplied out-param instead of silently
            # dropping them, so the true commit-owner can broadcast POST its own
            # commit. Currently unreachable (no production caller passes
            # db_session into complete_project), so this only activates for a
            # future external-session caller.
            decommission_events_out.extend(decommission_events)

        # Broadcast project status change to all browsers
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
        """
        Cancel a project with completed_at timestamp.

        Args:
            project_id: Project UUID
            tenant_key: Tenant key for multi-tenant isolation
            reason: Optional cancellation reason to store in metadata

        Returns:
            None

        Raises:
            ResourceNotFoundError: When project not found
            BaseGiljoError: When operation fails

        Example:
            >>> await service.cancel_project(
            ...     "abc-123",
            ...     "tenant-key-456",
            ...     reason="Requirements changed"
            ... )
        """
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
            # Re-raise our custom exceptions
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to cancel project")
            raise BaseGiljoError(message=f"Failed to cancel project: {e!s}", context={"project_id": project_id}) from e

    async def continue_working(self, project_id: str, tenant_key: str) -> ProjectResumeResult:
        """
        Resume work on a completed project (Handover 0113).

        Reopens a completed project by changing status to active and clearing
        completed_at timestamp. Validates project is in completed state.

        Args:
            project_id: Project UUID
            tenant_key: Tenant key for multi-tenant isolation

        Returns:
            Dict with success status, message, and resumed agent details

        Raises:
            ResourceNotFoundError: When project not found or access denied
            ProjectStateError: When project not in completed state
            BaseGiljoError: When operation fails

        Example:
            >>> result = await service.continue_working(
            ...     "abc-123",
            ...     "tenant-key-456"
            ... )
            >>> # Returns: {
            ...     "message": "Project resumed successfully",
            ...     "agents_resumed": 3,
            ...     "resumed_agent_ids": ["job-1", "job-2", "job-3"]
            ... }
        """
        try:
            async with self._get_session(tenant_key) as session:
                # Fetch project with tenant validation
                project = await self._repo.get_by_id(session, tenant_key, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found or access denied",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )

                # Validate project is in completed state
                if project.status != ProjectStatus.COMPLETED:
                    raise ProjectStateError(
                        message=f"Cannot resume project from status '{project.status.value}'. Project must be completed.",
                        context={"project_id": project_id, "current_status": project.status.value},
                    )

                # Reopen project in inactive state.
                # This avoids violating the Single Active Project per product constraint.
                project.status = ProjectStatus.INACTIVE
                project.completed_at = None
                project.updated_at = datetime.now(UTC)

                # Resume decommissioned agents (migrated to AgentExecution - Handover 0367a)
                executions_to_resume = await self._repo.find_decommissioned_executions(session, tenant_key, project_id)
                resumed_ids = []

                for execution in executions_to_resume:
                    execution.status = "waiting"
                    execution.updated_at = datetime.now(UTC)
                    resumed_ids.append(execution.job_id)

                await session.commit()

                self._logger.info(f"Resumed project {project_id} with {len(resumed_ids)} agents resumed")

                # Broadcast status change to all browsers
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
            # Re-raise our custom exceptions
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
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
        """Broadcast memory update via WebSocketManager (in-process)."""
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
        except Exception as ws_error:  # Broad catch: WebSocket resilience, non-critical broadcast
            self._logger.error(
                f"[WEBSOCKET ERROR] Failed to broadcast project:memory_updated: {ws_error}",
                exc_info=True,
            )
