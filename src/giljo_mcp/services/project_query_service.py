# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import is_review_pending
from giljo_mcp.exceptions import BaseGiljoError, ValidationError
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.service_responses import ActiveProjectDetail
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)




def _format_agent_summary_rows(rows: list) -> dict:
    total = sum(r.count for r in rows)
    return {"agent_count": total, "job_types": [{"type": r.job_type, "count": r.count} for r in rows]}


def _format_agent_detail_rows(pairs: list, headlines: bool) -> list[dict]:
    if headlines:
        return [
            {
                "job_id": job.job_id,
                "display_name": execution.agent_display_name,
                "status": execution.status,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }
            for job, execution in pairs
        ]
    return [
        {
            "job_id": job.job_id,
            "job_type": job.job_type,
            "status": job.status,
            "display_name": execution.agent_display_name,
            "agent_status": execution.status,
            "mission": job.mission,
            "result": execution.result,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
        for job, execution in pairs
    ]


def _format_memory_entry_rows(entries: list, headlines: bool) -> list[dict]:
    if headlines:
        return [
            {
                "id": str(entry.id),
                "sequence": entry.sequence,
                "entry_type": entry.entry_type,
                "summary": entry.summary,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            }
            for entry in entries
        ]
    return [
        {
            "id": str(entry.id),
            "entry_type": entry.entry_type,
            "sequence": entry.sequence,
            "project_name": entry.project_name,
            "summary": entry.summary,
            "key_outcomes": entry.key_outcomes or [],
            "decisions_made": entry.decisions_made or [],
            "git_commits": entry.git_commits or [],
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        }
        for entry in entries
    ]


class ProjectQueryService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        test_session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._test_session = test_session
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._repo = ProjectRepository()

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._test_session
        )

    async def get_active_projects(
        self, product_id: str | None = None, include_unreviewed: bool = False
    ) -> list[ActiveProjectDetail]:
        try:
            tenant_key = self.tenant_manager.get_current_tenant()

            self._logger.debug(f"[get_active_projects] Retrieved tenant_key from context: {tenant_key}")

            if not tenant_key:
                self._logger.error("[get_active_projects] No tenant context available!")
                raise ValidationError(
                    message="No tenant context available",
                    context={"operation": "get_active_projects"},
                )

            async with self._get_session() as session:
                projects = await self._repo.get_active_projects(session, tenant_key, product_id, include_unreviewed)

                if not projects:
                    self._logger.info(f"No active projects found for tenant {tenant_key}")
                    return []

                self._logger.info(f"Found {len(projects)} active project(s) for tenant {tenant_key}")

                details = []
                for project in projects:
                    agent_count = await self._repo.count_agent_jobs(session, tenant_key, project.id)
                    message_count = await self._repo.count_messages(session, tenant_key, project.id)
                    details.append(
                        ActiveProjectDetail(
                            id=str(project.id),
                            alias=project.alias or "",
                            name=project.name,
                            mission=project.mission or "",
                            description=project.description,
                            status=project.status,
                            staging_status=project.staging_status,
                            execution_mode=project.execution_mode,
                            product_id=project.product_id,
                            created_at=project.created_at.isoformat() if project.created_at else None,
                            updated_at=project.updated_at.isoformat() if project.updated_at else None,
                            completed_at=project.completed_at.isoformat() if project.completed_at else None,
                            implementation_launched_at=(
                                project.implementation_launched_at.isoformat()
                                if project.implementation_launched_at
                                else None
                            ),
                            reviewed_at=project.reviewed_at.isoformat() if project.reviewed_at else None,
                            review_pending=is_review_pending(project.status, project.reviewed_at),
                            deleted_at=project.deleted_at.isoformat() if project.deleted_at else None,
                            agent_count=agent_count,
                            message_count=message_count,
                            project_type_id=project.project_type_id,
                            project_type=project.project_type,
                            series_number=project.series_number,
                            subseries=project.subseries,
                            taxonomy_alias=project.taxonomy_alias,
                        )
                    )
                return details

        except ValidationError:
            raise
        except Exception as e:
            self._logger.exception("Failed to get active projects")
            raise BaseGiljoError(message=f"Failed to get active projects: {e!s}", context={}) from e

    async def get_project_agent_details(
        self,
        project_id: str,
        tenant_key: str,
        headlines: bool = False,
    ) -> list[dict]:
        try:
            async with self._get_session() as session:
                pairs = await self._repo.get_agent_details_for_project(session, tenant_key, project_id)
                return _format_agent_detail_rows(pairs, headlines)
        except Exception as e:  # noqa: BLE001 -- graceful degradation for optional enrichment
            self._logger.warning("Failed to get agent details for project %s: %s", project_id, e)
            return []

    async def get_project_memory_entries(
        self,
        project_id: str,
        tenant_key: str,
        headlines: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        try:
            async with self._get_session() as session:
                entries = await self._repo.get_memory_entries_for_project(session, tenant_key, project_id, limit=limit)
                return _format_memory_entry_rows(entries, headlines)
        except Exception as e:  # noqa: BLE001 -- graceful degradation for optional enrichment
            self._logger.warning("Failed to get memory entries for project %s: %s", project_id, e)
            return []

    async def get_project_messages(
        self,
        project_id: str,
        tenant_key: str,
        limit: int | None = None,
    ) -> list[dict]:
        try:
            async with self._get_session() as session:
                messages = await self._repo.get_messages_for_project(session, tenant_key, project_id, limit=limit)
                return [
                    {
                        "id": str(msg.id),
                        "from_agent_id": msg.from_agent_id,
                        "content": msg.content,
                        "message_type": msg.message_type,
                        "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    }
                    for msg in messages
                ]
        except Exception as e:  # noqa: BLE001 -- graceful degradation for optional enrichment
            self._logger.warning("Failed to get messages for project %s: %s", project_id, e)
            return []


    async def get_project_agent_summaries(
        self,
        project_ids: list[str],
        tenant_key: str,
    ) -> dict[str, dict]:
        if not project_ids:
            return {}
        try:
            async with self._get_session() as session:
                grouped = await self._repo.get_agent_job_type_summaries_for_projects(session, tenant_key, project_ids)
            return {pid: _format_agent_summary_rows(rows) for pid, rows in grouped.items()}
        except Exception as e:  # noqa: BLE001 -- graceful degradation for optional enrichment
            self._logger.warning("Failed to get batched agent summaries: %s", e)
            return {}

    async def get_project_agent_details_batch(
        self,
        project_ids: list[str],
        tenant_key: str,
        headlines: bool = False,
    ) -> dict[str, list[dict]]:
        if not project_ids:
            return {}
        try:
            async with self._get_session() as session:
                grouped = await self._repo.get_agent_details_for_projects(session, tenant_key, project_ids)
            return {pid: _format_agent_detail_rows(pairs, headlines) for pid, pairs in grouped.items()}
        except Exception as e:  # noqa: BLE001 -- graceful degradation for optional enrichment
            self._logger.warning("Failed to get batched agent details: %s", e)
            return {}

    async def get_project_memory_entries_batch(
        self,
        project_ids: list[str],
        tenant_key: str,
        headlines: bool = False,
        limit: int | None = None,
    ) -> dict[str, list[dict]]:
        if not project_ids:
            return {}
        try:
            async with self._get_session() as session:
                grouped = await self._repo.get_memory_entries_for_projects(session, tenant_key, project_ids)
            out: dict[str, list[dict]] = {}
            for pid, entries in grouped.items():
                windowed = entries[-limit:] if limit is not None else entries
                out[pid] = _format_memory_entry_rows(windowed, headlines)
            return out
        except Exception as e:  # noqa: BLE001 -- graceful degradation for optional enrichment
            self._logger.warning("Failed to get batched memory entries: %s", e)
            return {}
