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
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._test_session
        )

    async def delete_project(self, project_id: str) -> SoftDeleteResult:
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

            executions = await self._repo.get_active_executions_for_project(session, tenant_key, project_id)

            decommissioned_jobs_count = 0
            for execution in executions:
                execution.status = "decommissioned"
                execution.completed_at = now
                decommissioned_jobs_count += 1

            await self._cancel_sequence_membership(session, project_id, tenant_key)
            await session.commit()

            self._logger.info(
                f"Soft deleted project {project_id} for tenant {tenant_key} "
                f"at {project.deleted_at.isoformat() if project.deleted_at else 'unknown time'}. "
                f"Decommissioned {decommissioned_jobs_count} agent jobs."
            )

            if self._websocket_manager:
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

            deleted_at_iso = project.deleted_at.isoformat() if project.deleted_at else None

        return SoftDeleteResult(
            message="Project deleted successfully",
            deleted_at=deleted_at_iso,
            decommissioned_jobs=decommissioned_jobs_count,
        )

    async def _cancel_sequence_membership(self, session: AsyncSession, project_id: str, tenant_key: str) -> None:
        from giljo_mcp.exceptions import ValidationError as _ValidationError
        from giljo_mcp.services.sequence_run_service import SequenceRunService

        seq_service = SequenceRunService(tenant_manager=self.tenant_manager, session=session)

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
            await seq_service.release(run_id=run_id, mode="cancel", tenant_key=tenant_key)

    async def nuclear_delete_project(
        self, project_id: str, websocket_manager: Any | None = None
    ) -> NuclearDeleteResult:
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={"project_id": project_id})

        async with self._get_session(tenant_key) as session:
            project = await self._repo.get_by_id(session, tenant_key, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found or access denied",
                    context={"project_id": project_id, "tenant_key": tenant_key},
                )

            project_name = project.name
            project_product_id = project.product_id

            if project.status == ProjectStatus.ACTIVE:
                project.status = ProjectStatus.INACTIVE
                project.updated_at = datetime.now(UTC)
                await self._repo.flush(session)
                self._logger.info(f"Deactivated project {project_id} before nuclear delete")

            deleted_counts = {
                "agent_jobs": 0,
                "tasks": 0,
                "messages": 0,
            }

            deleted_counts["user_approvals"] = await self._repo.bulk_delete_user_approvals_for_project(
                session, tenant_key, project_id
            )

            deleted_counts["agent_jobs"] = await self._repo.bulk_delete_agent_jobs_for_project(
                session, tenant_key, project_id
            )

            tasks = await self._repo.get_tasks_for_project(session, tenant_key, project_id)
            for task in tasks:
                await self._repo.delete_entity(session, task)
            deleted_counts["tasks"] = len(tasks)

            deleted_counts["messages"] = await self._repo.bulk_delete_messages_for_project(
                session, tenant_key, project_id
            )

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

            await self._repo.delete_entity(session, project)

            await session.commit()

            self._logger.info(
                f"Nuclear delete completed for project {project_id} ({project_name}): "
                f"{deleted_counts['agent_jobs']} agents, "
                f"{deleted_counts['tasks']} tasks, "
                f"{deleted_counts['messages']} messages, "
                f"{deleted_counts['memory_entries_marked']} 360 memory entries marked"
            )

            if websocket_manager:
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

            return NuclearDeleteResult(
                message=f"Project '{project_name}' permanently deleted",
                deleted_counts=deleted_counts,
                project_name=project_name,
            )

    async def _purge_project_records(self, session: AsyncSession, project: Project) -> dict[str, Any]:
        project_info = {
            "id": project.id,
            "name": project.name,
            "tenant_key": project.tenant_key,
            "deleted_at": project.deleted_at.isoformat() if project.deleted_at else None,
        }

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

        tenant_key = project.tenant_key

        user_approvals = await self._repo.get_user_approvals_for_project(session, tenant_key, project.id)
        for approval in user_approvals:
            await self._repo.delete_entity(session, approval)

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
        tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={})

        async with self._get_session(tenant_key) as session:
            deleted_projects = await self._repo.get_deleted_projects(session, tenant_key, product_id)

            if not deleted_projects:
                return ProjectPurgeResult(purged_count=0, projects=[])

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
        from datetime import timedelta

        if not self.db_manager:
            self._logger.error("[Nuclear Purge] Cannot purge - database manager not available")
            raise BaseGiljoError(message="Database not available", context={})

        async with self._get_session() as session:
            cutoff_date = datetime.now(UTC) - timedelta(days=days_before_purge)

            expired_projects = await self._repo.get_expired_deleted_projects(session, cutoff_date)

            if not expired_projects:
                self._logger.info(
                    f"[Nuclear Purge] No expired deleted projects to purge (cutoff: {days_before_purge} days)"
                )
                return ProjectPurgeResult(purged_count=0, projects=[])

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
        async with self._get_session(tenant_key) as session:
            project = await self._repo.get_by_id(session, tenant_key, project_id)

            if project is None:
                raise ResourceNotFoundError(
                    message="Project not found or access denied",
                    context={"project_id": project_id, "tenant_key": tenant_key},
                )

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
