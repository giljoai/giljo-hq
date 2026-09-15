# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.service_responses import ProjectSummaryResult
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.project_helpers import compute_completion_percent
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


class ProjectSummaryService:

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
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def get_project_summary(self, project_id: str, tenant_key: str | None = None) -> ProjectSummaryResult:
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()

        async with self._get_session(effective_tenant_key) as session:
            project = await self._repo.get_by_id(session, effective_tenant_key, project_id)

            if not project:
                raise ResourceNotFoundError(message="Project not found", context={"project_id": project_id})

            job_counts = await self._repo.get_agent_status_counts(session, effective_tenant_key, project_id)

            total_jobs = sum(job_counts.values())
            completed_jobs = job_counts.get("complete", 0)
            blocked_jobs = job_counts.get("blocked", 0)
            active_jobs = job_counts.get("working", 0)
            pending_jobs = job_counts.get("waiting", 0)

            completion_percentage = compute_completion_percent(
                completed_jobs, total_jobs, job_counts.get("decommissioned", 0)
            )

            last_activity_at = await self._repo.get_last_activity_at(session, effective_tenant_key, project_id)

            product_name = ""
            if project.product_id:
                product = await self._repo.get_product_by_id(session, effective_tenant_key, project.product_id)
                if product:
                    product_name = product.name

            return ProjectSummaryResult(
                id=project.id,
                name=project.name,
                status=project.status,
                mission=project.mission,
                total_jobs=total_jobs,
                completed_jobs=completed_jobs,
                blocked_jobs=blocked_jobs,
                active_jobs=active_jobs,
                pending_jobs=pending_jobs,
                completion_percentage=completion_percentage,
                created_at=project.created_at.isoformat() if project.created_at else None,
                last_activity_at=last_activity_at.isoformat() if last_activity_at else None,
                product_id=project.product_id or "",
                product_name=product_name,
            )
