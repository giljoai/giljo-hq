# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProjectDeletionService - Extracted from ProjectService (Handover 0769).

Handles project deletion and purge operations:
- delete_project (soft delete)
- nuclear_delete_project (hard delete)
- purge_all_deleted_projects, purge_expired_deleted_projects
- restore_project
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.service_responses import (
    NuclearDeleteResult,
    OperationResult,
    ProjectPurgeResult,
    SoftDeleteResult,
)
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


class ProjectDeletionService:
    """Service for project deletion and purge operations."""

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
        self._repo = ProjectRepository()

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._test_session
        )

    async def delete_project(self, project_id: str) -> SoftDeleteResult:
        """
        Soft delete a project.

        Sets status='deleted' and deleted_at timestamp for the current tenant's project.
        Actual purge is handled separately by purge_expired_deleted_projects().

        Args:
            project_id: Project UUID

        Returns:
            Deletion result dictionary with deleted_at timestamp and cancelled_jobs count

        Raises:
            ValidationError: No tenant context available
            ResourceNotFoundError: Project not found or already deleted
        """
        # Get current tenant from context
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={"project_id": project_id})

        async with self._get_session() as session:
            project = await self._repo.get_not_deleted(session, tenant_key, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found or already deleted",
                    context={"project_id": project_id, "tenant_key": tenant_key},
                )

            now = datetime.now(UTC)
            project.status = ProjectStatus.DELETED
            project.deleted_at = now
            project.updated_at = now

            # Cascade soft delete to agent jobs - cancel all executions for this project (migrated to AgentExecution - Handover 0367a)
            executions = await self._repo.get_active_executions_for_project(session, tenant_key, project_id)

            decommissioned_jobs_count = 0
            for execution in executions:
                execution.status = "decommissioned"
                execution.completed_at = now
                decommissioned_jobs_count += 1

            await session.commit()

            self._logger.info(
                f"Soft deleted project {project_id} for tenant {tenant_key} "
                f"at {project.deleted_at.isoformat() if project.deleted_at else 'unknown time'}. "
                f"Decommissioned {decommissioned_jobs_count} agent jobs."
            )

            # Broadcast status change to all browsers
            if self._websocket_manager:
                try:
                    await self._websocket_manager.broadcast_project_update(
                        project_id=project_id,
                        update_type="status_changed",
                        project_data={
                            "name": project.name,
                            "status": ProjectStatus.DELETED.value,
                            "product_id": project.product_id,
                        },
                        tenant_key=tenant_key,
                    )
                except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                    self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

            deleted_at_iso = project.deleted_at.isoformat() if project.deleted_at else None

        # FE-6175 (RC2): a deleted project must not linger as a member of an active
        # sequence_run, or the chain views storm 404s fetching its dead members.
        # Drop it from any active run (runs its own session — after the delete
        # session above has committed + closed).
        await self._cancel_sequence_membership(project_id, tenant_key)

        return SoftDeleteResult(
            message="Project deleted successfully",
            deleted_at=deleted_at_iso,
            decommissioned_jobs=decommissioned_jobs_count,
        )

    async def _cancel_sequence_membership(self, project_id: str, tenant_key: str) -> None:
        """Drop a just-deleted project from any active sequence_run (FE-6175 RC2).

        Reuses the EXISTING SequenceRunService writers — no new method/endpoint:
          * pending run -> ``remove_member`` (which already dissolves the run at
            reduce-to-one), mirroring the /roadmap + hamburger Unlink semantics;
          * running/stalled (or otherwise ultralocked, where ``remove_member``
            refuses) -> ``release(mode="cancel")`` to end the whole run.
        Best-effort: a cascade failure must never block the soft-delete itself.
        """
        from giljo_mcp.exceptions import ValidationError as _ValidationError
        from giljo_mcp.services.sequence_run_service import SequenceRunService

        if self._test_session is not None:
            seq_service = SequenceRunService(tenant_manager=self.tenant_manager, session=self._test_session)
        else:
            seq_service = SequenceRunService(db_manager=self.db_manager, tenant_manager=self.tenant_manager)

        try:
            run = await seq_service.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)
            if not run:
                return
            run_id = run.get("id")
            if run.get("status") in ("running", "stalled"):
                await seq_service.release(run_id=run_id, mode="cancel", tenant_key=tenant_key)
                return
            try:
                await seq_service.remove_member(run_id=run_id, project_id=project_id, tenant_key=tenant_key)
            except _ValidationError:
                # Ultralocked pending run (a member is staging_complete) — remove_member
                # refuses, so end the whole run instead.
                await seq_service.release(run_id=run_id, mode="cancel", tenant_key=tenant_key)
        except Exception as cascade_error:  # noqa: BLE001 - cascade must not block the delete
            self._logger.warning(
                "Sequence-membership cascade failed for deleted project %s: %s", project_id, cascade_error
            )

    async def nuclear_delete_project(
        self, project_id: str, websocket_manager: Any | None = None
    ) -> NuclearDeleteResult:
        """
        Immediately and permanently delete a project and ALL related data (nuclear delete).

        This method performs complete cascade deletion of:
        - Agent jobs (AgentJob + AgentExecution)
        - Tasks
        - Messages
        - 360 memory entries (marked as deleted)
        - The project itself

        Special handling:
        - Deactivates project if it's currently active
        - Broadcasts WebSocket events for real-time UI cleanup
        - Ensures multi-tenant isolation (only deletes for current tenant)
        - Fully transactional (rollback on error)

        Args:
            project_id: Project UUID
            websocket_manager: Optional WebSocket manager for real-time updates

        Returns:
            Deletion details dictionary:
            - message: str
            - deleted_counts: dict with counts of each deleted entity type
            - project_name: str (name of deleted project)

        Raises:
            ValidationError: No tenant context available
            ResourceNotFoundError: Project not found or access denied

        Example:
            >>> result = await service.nuclear_delete_project("abc-123")
            >>> print(result["deleted_counts"])
            {"agents": 5, "tasks": 12, "messages": 48, ...}
        """
        # Get current tenant from context
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={"project_id": project_id})

        async with self._get_session(tenant_key) as session:
            # Fetch project with tenant validation
            project = await self._repo.get_by_id(session, tenant_key, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found or access denied",
                    context={"project_id": project_id, "tenant_key": tenant_key},
                )

            project_name = project.name
            project_product_id = project.product_id

            # Deactivate project if it's active (to avoid constraint issues)
            if project.status == ProjectStatus.ACTIVE:
                project.status = ProjectStatus.INACTIVE
                project.updated_at = datetime.now(UTC)
                await self._repo.flush(session)
                self._logger.info(f"Deactivated project {project_id} before nuclear delete")

            # Initialize deletion counters
            deleted_counts = {
                "agent_jobs": 0,
                "tasks": 0,
                "messages": 0,
            }

            # BE-9144: bulk-delete each collection in one statement instead of
            # SELECT-then-per-row ORM delete (was N+1 per collection).
            # Delete user approvals FIRST: user_approvals has RESTRICT FKs to
            # agent_executions, agent_jobs AND projects (BE-5029), so it must be
            # cleared before the cascade below or the delete is blocked with a
            # RestrictViolationError and the project is never purged (BE-6238).
            deleted_counts["user_approvals"] = await self._repo.bulk_delete_user_approvals_for_project(
                session, tenant_key, project_id
            )

            # Delete agent jobs + their executions (executions cascade is ORM-level,
            # so the repo deletes executions first — see bulk_delete_agent_jobs_for_project).
            deleted_counts["agent_jobs"] = await self._repo.bulk_delete_agent_jobs_for_project(
                session, tenant_key, project_id
            )

            # Tasks stay per-row: the self-referential parent_task_id FK has no DB
            # ondelete and the ORM 'subtasks' relationship nullifies rather than
            # cascades, so a blind bulk DELETE could diverge on a cross-project
            # subtask (a behavior change, not a perf win).
            tasks = await self._repo.get_tasks_for_project(session, tenant_key, project_id)
            for task in tasks:
                await self._repo.delete_entity(session, task)
            deleted_counts["tasks"] = len(tasks)

            # Delete messages (recipients/acknowledgments/completions cascade at the DB level).
            deleted_counts["messages"] = await self._repo.bulk_delete_messages_for_project(
                session, tenant_key, project_id
            )

            # Mark 360 memory entries as deleted by user (preserve historical reference)
            # Handover 0390b: Use repository instead of JSONB mutation
            memory_entries_marked = 0
            if project.product_id:
                from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository

                repo = ProductMemoryRepository()
                memory_entries_marked = await repo.mark_entries_deleted(
                    session=session,
                    project_id=project_id,
                    tenant_key=tenant_key,
                )

                if memory_entries_marked > 0:
                    self._logger.info(
                        f"Marked {memory_entries_marked} 360 memory entries as deleted for project {project_id}"
                    )

            deleted_counts["memory_entries_marked"] = memory_entries_marked

            # Finally, delete the project itself
            await self._repo.delete_entity(session, project)

            # Commit transaction
            await session.commit()

            self._logger.info(
                f"Nuclear delete completed for project {project_id} ({project_name}): "
                f"{deleted_counts['agent_jobs']} agents, "
                f"{deleted_counts['tasks']} tasks, "
                f"{deleted_counts['messages']} messages, "
                f"{deleted_counts['memory_entries_marked']} 360 memory entries marked"
            )

            # Broadcast WebSocket event for real-time UI cleanup
            if websocket_manager:
                try:
                    await websocket_manager.broadcast_project_update(
                        project_id=project_id,
                        update_type="deleted",
                        project_data={
                            "name": project_name,
                            "deleted_counts": deleted_counts,
                            "product_id": project_product_id,
                        },
                        tenant_key=tenant_key,
                    )
                except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                    self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

            return NuclearDeleteResult(
                message=f"Project '{project_name}' permanently deleted",
                deleted_counts=deleted_counts,
                project_name=project_name,
            )

    async def _purge_project_records(self, session: AsyncSession, project: Project) -> dict[str, Any]:
        """Cascade delete a soft-deleted project and its child records."""
        project_info = {
            "id": project.id,
            "name": project.name,
            "tenant_key": project.tenant_key,
            "deleted_at": project.deleted_at.isoformat() if project.deleted_at else None,
        }

        # Mark 360 memory entries as deleted by user (preserve historical reference)
        # Uses ProductMemoryRepository for table-based operations (Handover 0390c)
        if project.product_id:
            from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository

            repo = ProductMemoryRepository()
            deleted_count = await repo.mark_entries_deleted(
                session=session,
                project_id=project.id,
                tenant_key=project.tenant_key,
            )
            if deleted_count > 0:
                self._logger.info(f"Marked {deleted_count} memory entries as deleted for project {project.id}")

        # TENANT ISOLATION: All cascade deletes filter by tenant_key
        tenant_key = project.tenant_key

        # Delete user approvals first: RESTRICT FKs to agent_executions, agent_jobs
        # AND projects (BE-5029) block the cascade below unless cleared first (BE-6238).
        user_approvals = await self._repo.get_user_approvals_for_project(session, tenant_key, project.id)
        for approval in user_approvals:
            await self._repo.delete_entity(session, approval)

        # Delete agent jobs (migrated to AgentJob - Handover 0367a)
        agent_jobs = await self._repo.get_agent_jobs_for_project(session, tenant_key, project.id)
        for job in agent_jobs:
            await self._repo.delete_entity(session, job)

        tasks = await self._repo.get_tasks_for_project(session, tenant_key, project.id)
        for task in tasks:
            await self._repo.delete_entity(session, task)

        messages = await self._repo.get_messages_for_deletion(session, tenant_key, project.id)
        for message in messages:
            await self._repo.delete_entity(session, message)

        await self._repo.delete_entity(session, project)
        return project_info

    async def purge_all_deleted_projects(self, product_id: str | None = None) -> ProjectPurgeResult:
        """
        Nuclear delete all soft-deleted projects for the current tenant,
        optionally scoped to a product.

        Uses nuclear_delete_project for each project to ensure complete removal.
        Called when user clicks "Delete All" button in deleted projects modal.

        Args:
            product_id: Optional product ID to scope purge

        Returns:
            Purge result dictionary with purged_count and project details list

        Raises:
            ValidationError: No tenant context available
        """
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={})

        async with self._get_session(tenant_key) as session:
            deleted_projects = await self._repo.get_deleted_projects(session, tenant_key, product_id)

            if not deleted_projects:
                return ProjectPurgeResult(purged_count=0, projects=[])

        # Use nuclear delete for each project
        purged_projects = []
        for project in deleted_projects:
            try:
                await self.nuclear_delete_project(project.id)
                purged_projects.append(
                    {
                        "id": project.id,
                        "name": project.name,
                        "tenant_key": project.tenant_key,
                        "deleted_at": project.deleted_at.isoformat() if project.deleted_at else None,
                    }
                )
            except Exception as _exc:
                self._logger.exception("Failed to nuclear delete project {project.id}")

        self._logger.info(
            "[Nuclear Purge] Permanently deleted %s project(s) for tenant %s",
            len(purged_projects),
            tenant_key,
        )

        return ProjectPurgeResult(purged_count=len(purged_projects), projects=purged_projects)

    async def purge_expired_deleted_projects(self, days_before_purge: int = 10) -> ProjectPurgeResult:
        """
        Nuclear delete projects deleted more than specified days ago.

        Uses nuclear_delete_project to ensure complete removal of expired projects.
        This function performs COMPLETE cascade deletion:
        1. Deactivates if active
        2. Deletes ALL child agents (AgentJob + AgentExecution)
        3. Deletes ALL tasks
        4. Deletes ALL messages
        5. Deletes ALL context indexes
        6. Deletes ALL large document indexes
        7. Deletes ALL sessions
        8. Deletes ALL vision documents
        9. Deletes the project record

        Called from startup.py on server start for automatic cleanup.

        Args:
            days_before_purge: Number of days before permanent deletion (default: 10)

        Returns:
            ProjectPurgeResult: Pydantic model with:
                - purged_count: int - Number of projects purged
                - projects: list[dict] - Details of purged projects

        Raises:
            BaseGiljoError: Database not available

        Example:
            >>> result = await service.purge_expired_deleted_projects()
            >>> print(f"Nuclear purged {result.purged_count} expired projects")
        """
        from datetime import timedelta

        if not self.db_manager:
            self._logger.error("[Nuclear Purge] Cannot purge - database manager not available")
            raise BaseGiljoError(message="Database not available", context={})

        async with self._get_session() as session:
            # Find projects deleted more than specified days ago
            cutoff_date = datetime.now(UTC) - timedelta(days=days_before_purge)

            expired_projects = await self._repo.get_expired_deleted_projects(session, cutoff_date)

            if not expired_projects:
                self._logger.info(
                    f"[Nuclear Purge] No expired deleted projects to purge (cutoff: {days_before_purge} days)"
                )
                return ProjectPurgeResult(purged_count=0, projects=[])

        # Use nuclear delete for each expired project
        purged_projects = []
        for project in expired_projects:
            try:
                await self.nuclear_delete_project(project.id)
                purged_projects.append(
                    {
                        "id": project.id,
                        "name": project.name,
                        "tenant_key": project.tenant_key,
                        "deleted_at": project.deleted_at.isoformat() if project.deleted_at else None,
                    }
                )
                self._logger.info(
                    f"[Nuclear Purge] Auto-purged expired project {project.id} "
                    f"(deleted {(datetime.now(UTC) - project.deleted_at).days} days ago)"
                )
            except Exception as _exc:
                self._logger.exception("Failed to nuclear delete expired project {project.id}")

        self._logger.info(f"[Nuclear Purge] Successfully purged {len(purged_projects)} expired deleted projects")

        return ProjectPurgeResult(purged_count=len(purged_projects), projects=purged_projects)

    async def restore_project(self, project_id: str, tenant_key: str) -> OperationResult:
        """
        Restore a completed, cancelled, or soft-deleted project to inactive status.

        BE-6049b serial handling (decision C):
        - A **soft-deleted** project freed its serial the moment it was deleted
          (the global ``max+1`` counter excludes ``deleted_at IS NOT NULL`` rows),
          so its old number may already have been reused. On restore it is
          re-assigned a FRESH continue-upward serial via the global counter — the
          old number is never reused.
        - A **cancelled or completed** project never left the active pool (its
          serial was never freed), so it KEEPS its existing number.

        Args:
            project_id: Project UUID
            tenant_key: Tenant key for multi-tenant isolation

        Returns:
            Success message dictionary

        Raises:
            ResourceNotFoundError: Project not found or access denied

        Example:
            >>> result = await service.restore_project("abc-123", "tenant-key-456")
        """
        async with self._get_session(tenant_key) as session:
            # TENANT ISOLATION: get_by_id filters by both project_id AND tenant_key,
            # so a cross-tenant project_id resolves to None -> ResourceNotFoundError.
            project = await self._repo.get_by_id(session, tenant_key, project_id)

            if project is None:
                raise ResourceNotFoundError(
                    message="Project not found or access denied",
                    context={"project_id": project_id, "tenant_key": tenant_key},
                )

            # Only a soft-deleted project freed its serial; re-allocate a fresh
            # continue-upward number via the global counter (decision C — the old
            # number is never reused). No cap here: the assignment cap lives on the
            # create paths (project_service/task_service); a restore continues the
            # product's existing high-water mark, which display tolerates (BE-6049a).
            if project.deleted_at is not None:
                await self._repo.lock_rows_for_series_shared(session, tenant_key, project.product_id)
                fresh_series = await self._repo.get_next_series_number_shared(session, tenant_key, project.product_id)
                project.series_number = fresh_series

            now = datetime.now(UTC)
            project.status = ProjectStatus.INACTIVE
            project.completed_at = None
            project.deleted_at = None
            project.updated_at = now

            await session.commit()

            self._logger.info(f"Restored project {project_id}")

            return OperationResult(
                message=f"Project {project_id} restored successfully",
            )
