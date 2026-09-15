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
from giljo_mcp.exceptions import BaseGiljoError, ResourceNotFoundError
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.identity import validate_agent_display_name


logger = logging.getLogger(__name__)


class AgentJobManager:

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

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def spawn_execution(
        self,
        job_id: str,
        agent_display_name: str,
        tenant_key: str,
        spawned_by: str | None = None,
    ) -> tuple[str, str]:
        try:
            agent_display_name = validate_agent_display_name(agent_display_name)

            repo = AgentJobRepository(None)
            async with self._get_session(tenant_key) as session:
                new_agent_id = str(uuid4())
                execution = AgentExecution(
                    agent_id=new_agent_id,
                    job_id=job_id,
                    tenant_key=tenant_key,
                    agent_display_name=agent_display_name,
                    status="waiting",
                    spawned_by=spawned_by,
                    agent_name=agent_display_name.title(),
                    tool_type="universal",
                    started_at=datetime.now(UTC),
                )

                try:
                    await repo.add_execution_for_existing_job(session, tenant_key, job_id, execution)
                except ValueError as exc:
                    raise ResourceNotFoundError(
                        message=f"AgentJob with job_id={job_id} not found for tenant {tenant_key}",
                        context={"job_id": job_id, "tenant_key": tenant_key},
                    ) from exc

                self._logger.info(
                    f"Spawned execution: agent_id={new_agent_id} for job_id={job_id}, tenant={tenant_key}"
                )

                return (job_id, new_agent_id)

        except (ResourceNotFoundError, BaseGiljoError):
            raise
        except Exception as e:
            self._logger.exception("Failed to spawn execution")
            raise BaseGiljoError(message=str(e), context={"operation": "spawn_execution", "job_id": job_id}) from e


    async def complete_job(
        self,
        job_id: str,
        tenant_key: str,
    ) -> int:
        try:
            repo = AgentJobRepository(None)
            async with self._get_session(tenant_key) as session:
                job, executions = await repo.complete_job_with_executions(session, tenant_key, job_id)

                if not job:
                    raise ResourceNotFoundError(message=f"Job {job_id} not found", context={"job_id": job_id})

                self._logger.info(f"Completed job {job_id} and marked {len(executions)} execution(s) as complete")

                return len(executions)

        except (ResourceNotFoundError, BaseGiljoError):
            raise
        except Exception as e:
            self._logger.exception("Failed to complete job")
            raise BaseGiljoError(message=str(e), context={"operation": "complete_job"}) from e

    async def list_team_agents(
        self,
        job_id: str,
        tenant_key: str,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            repo = AgentJobRepository(None)
            async with self._get_session(tenant_key) as session:
                executions = await repo.list_team_executions(session, tenant_key, job_id, include_inactive)

                team_members = [
                    {
                        "agent_id": execution.agent_id,
                        "job_id": execution.job_id,
                        "agent_display_name": execution.agent_display_name,
                        "status": execution.status,
                        "agent_name": execution.agent_name,
                        "tenant_key": execution.tenant_key,
                    }
                    for execution in executions
                ]

                self._logger.info(
                    f"Found {len(team_members)} teammates for job {job_id} (include_inactive={include_inactive})"
                )

                return team_members

        except Exception as _exc:
            self._logger.exception("Failed to list team agents")
            return []
