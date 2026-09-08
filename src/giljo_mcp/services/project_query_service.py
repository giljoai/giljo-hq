# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProjectQueryService - Read-only dashboard queries for projects.

Sprint 002e: Extracted from ProjectService to reduce god-class size.
These are all read-only DB queries used by the frontend dashboard.
They have no side effects and no cross-service dependencies.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import BaseGiljoError, ValidationError
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.service_responses import ActiveProjectDetail
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


# BE-6071 F6b: shared row-formatters so the per-project methods and their batched
# (grouped-IN) siblings emit byte-identical dicts — no drift between the two paths.


def _format_agent_summary_rows(rows: list) -> dict:
    """Shape grouped (job_type, count) rows into the agent-summary dict."""
    total = sum(r.count for r in rows)
    return {"agent_count": total, "job_types": [{"type": r.job_type, "count": r.count} for r in rows]}


def _format_agent_detail_rows(pairs: list, headlines: bool) -> list[dict]:
    """Shape (AgentJob, AgentExecution) pairs into agent-detail dicts."""
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
    """Shape ProductMemoryEntry rows into memory-entry dicts."""
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
    """Read-only query service for project dashboard data.

    Extracted from ProjectService (Sprint 002e). All methods are read-only
    DB queries with no side effects.
    """

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
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._test_session
        )

    async def get_active_projects(self, product_id: str | None = None) -> list[ActiveProjectDetail]:
        """Get every currently active project for the current tenant, optionally scoped to a product.

        Returns the active projects (status='active') for ``product_id``, or every
        active project tenant-wide if ``product_id`` is omitted (kept for callers
        with no product context, per BE-9525a). BE-9525b (ruling 5 amended) dropped
        ``idx_project_single_active_per_product``, so this is genuinely plural now
        — a product may legally have more than one ACTIVE project, and there is no
        remaining single-row guarantee to resolve to instead.

        Returns:
            List of ActiveProjectDetail, one per active project in scope (may be empty)

        Raises:
            ValidationError: When no tenant context is available
            BaseGiljoError: When operation fails
        """
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
                projects = await self._repo.get_active_projects(session, tenant_key, product_id)

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
                            product_id=project.product_id,
                            created_at=project.created_at.isoformat() if project.created_at else None,
                            updated_at=project.updated_at.isoformat() if project.updated_at else None,
                            completed_at=project.completed_at.isoformat() if project.completed_at else None,
                            implementation_launched_at=(
                                project.implementation_launched_at.isoformat()
                                if project.implementation_launched_at
                                else None
                            ),
                            deleted_at=project.deleted_at.isoformat() if project.deleted_at else None,
                            agent_count=agent_count,
                            message_count=message_count,
                            project_type_id=project.project_type_id,
                            # BE-9326: nested type info, same as the ProjectDetail builders.
                            # Safe to read here: the row comes from
                            # ProjectRepository.get_active_projects, which selectinloads
                            # project_type, and this construction happens inside the session.
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

    async def get_project_agent_summary(self, project_id: str, tenant_key: str) -> dict:
        """Get a lightweight summary of agent jobs for a project.

        Returns counts and types of agents spawned, without full details.

        Args:
            project_id: Project UUID.
            tenant_key: Tenant isolation key (required).

        Returns:
            Dict with agent_count and job_types list.
        """
        try:
            async with self._get_session() as session:
                rows = await self._repo.get_agent_job_type_summary(session, tenant_key, project_id)
                return _format_agent_summary_rows(rows)
        except Exception as e:  # noqa: BLE001 -- graceful degradation for optional enrichment
            self._logger.warning("Failed to get agent summary for project %s: %s", project_id, e)
            return {"agent_count": 0, "job_types": []}

    async def get_project_agent_details(
        self,
        project_id: str,
        tenant_key: str,
        headlines: bool = False,
    ) -> list[dict]:
        """Get detailed agent job info for a project.

        BE-5042: ``headlines=True`` returns the lean projection used by audit
        mode (drops result blob and full mission text); the full projection
        remains the default for back-compat and forensic mode.

        Args:
            project_id: Project UUID.
            tenant_key: Tenant isolation key (required).
            headlines: When True, return only {job_id, display_name, status,
                completed_at} per job.

        Returns:
            List of agent job detail dicts.
        """
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
        """Get 360 memory entries for a project.

        BE-5042: ``headlines=True`` returns a lean projection (drops
        ``key_outcomes``, ``decisions_made``, ``git_commits``, ``project_name``)
        used by audit mode; ``limit`` caps the trailing window so callers can
        request the most recent N entries. Full bodies + full history remain
        the default for back-compat and forensic mode.

        Args:
            project_id: Project UUID.
            tenant_key: Tenant isolation key (required).
            headlines: When True, return only {id, sequence, entry_type,
                summary, timestamp} per entry.
            limit: Most recent N entries to return; None means full history.

        Returns:
            List of memory entry dicts.
        """
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
        """Get message history for a project (depth 3).

        BE-6071 F6c: ``limit`` caps the trailing window to the most recent N
        messages (chronological order preserved). None means full history.

        Args:
            project_id: Project UUID.
            tenant_key: Tenant isolation key (required).
            limit: Most recent N messages to return; None means full history.

        Returns:
            List of message dicts with sender, content, and timestamps.
        """
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

    # ========================================================================
    # BE-6071 F6b: batched (grouped-IN) enrichment — one query per depth facet
    # across ALL listed project_ids, replacing the per-project N+1 in
    # _build_mcp_project_list. Same output dicts (shared formatters), keyed by
    # project_id. On error each degrades to an empty map so the assembler falls
    # back to per-project defaults — identical to the per-project graceful path.
    # ========================================================================

    async def get_project_agent_summaries(
        self,
        project_ids: list[str],
        tenant_key: str,
    ) -> dict[str, dict]:
        """Batched ``get_project_agent_summary``: {project_id: {agent_count, job_types}}."""
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
        """Batched ``get_project_agent_details``: {project_id: [detail dicts]}."""
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
        """Batched ``get_project_memory_entries``: {project_id: [entry dicts]}.

        The per-project trailing-window cap (``limit``) is applied IN PYTHON after
        the single grouped fetch (per-project memory counts are small closeouts and
        the project list is ceiling-capped, so the grouped set stays bounded — no
        per-project SQL LIMIT / window function needed). Entries arrive ascending
        by sequence, so the most-recent ``limit`` is the trailing slice, already
        chronological — matching the per-project method's semantics.
        """
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
