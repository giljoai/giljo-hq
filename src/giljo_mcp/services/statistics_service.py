# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.repositories.job_statistics_repository import JobStatisticsRepository
from giljo_mcp.repositories.product_statistics_repository import (
    ProductStatisticsRepository,
)
from giljo_mcp.services._session_helpers import optional_tenant_session


logger = logging.getLogger(__name__)


class StatisticsService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        test_session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self._test_session = test_session
        self._job_repo = JobStatisticsRepository(db_manager)
        self._product_repo = ProductStatisticsRepository(db_manager)
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def get_dashboard_stats(
        self,
        tenant_key: str,
        product_id: str | None = None,
    ) -> dict[str, Any]:
        async with self._get_session(tenant_key) as session:
            return {
                "project_status_dist": await self._product_repo.get_project_status_distribution(
                    session, tenant_key, product_id=product_id
                ),
                "taxonomy_dist": await self._product_repo.get_project_taxonomy_distribution(
                    session, tenant_key, product_id=product_id
                ),
                "agent_role_dist": await self._job_repo.get_agent_role_distribution(
                    session, tenant_key, product_id=product_id
                ),
                "recent_projects": await self._product_repo.get_recent_projects(
                    session, tenant_key, product_id=product_id
                ),
                "recent_memories": await self._product_repo.get_recent_memory_entries(
                    session, tenant_key, product_id=product_id
                ),
                "task_status_dist": await self._product_repo.get_task_status_distribution(
                    session, tenant_key, product_id=product_id
                ),
                "execution_mode_dist": await self._product_repo.get_execution_mode_distribution(
                    session, tenant_key, product_id=product_id
                ),
                "products": await self._product_repo.get_product_project_counts(session, tenant_key),
                "total_commits": await self._product_repo.get_total_commits(session, tenant_key, product_id=product_id),
            }


    async def get_api_metrics(
        self,
        tenant_key: str,
    ) -> Any:
        async with self._get_session(tenant_key) as session:
            return await self._job_repo.get_api_metrics(session, tenant_key)


    async def get_system_stats(
        self,
        tenant_key: str,
    ) -> dict[str, int]:
        async with self._get_session(tenant_key) as session:
            total_agents = await self._job_repo.count_total_agents(session, tenant_key)
            return {
                "total_projects": await self._product_repo.count_total_projects(session, tenant_key),
                "active_projects": await self._product_repo.count_projects_by_status(session, tenant_key, "active"),
                "completed_projects": await self._product_repo.count_projects_by_status(
                    session, tenant_key, "completed"
                ),
                "total_agents": total_agents,
                "active_agents": await self._job_repo.count_active_agents(session, tenant_key),
                "total_messages": await self._product_repo.count_total_messages(session, tenant_key),
                "pending_messages": await self._product_repo.count_messages_by_status(session, tenant_key, "pending"),
                "total_tasks": await self._product_repo.count_total_tasks(session, tenant_key),
                "completed_tasks": await self._product_repo.count_completed_tasks(session, tenant_key),
                "total_agents_spawned": total_agents,
                "total_jobs_completed": await self._job_repo.count_completed_agents(session, tenant_key),
                "projects_staged": await self._product_repo.count_projects_staged(session, tenant_key),
                "projects_cancelled": await self._product_repo.count_projects_by_status(
                    session, tenant_key, "cancelled"
                ),
            }
