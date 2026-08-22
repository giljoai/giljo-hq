# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
AgentJobManager Service - Coordinated CRUD for AgentJob + AgentExecution (Handover 0366b).

This service manages agent job lifecycle with dual-model architecture:
- AgentJob: Persistent work order (mission, scope) - WHAT
- AgentExecution: Executor instance (who's working, status) - WHO

Key Operations:
- complete_job() - Marks job complete and decommissions all executions

Note: cancel_job() was intentionally removed (commit d14e8ff7) - passive HTTP
architecture means agents only see cancellation on next poll (30s-5min delay).
Use project-level cancel or Ctrl+C in terminal for immediate stop.

Design Philosophy:
- Job = Work to be done (persists across succession)
- Execution = Who's doing the work (changes on succession)
- One job can have multiple executions (succession chain)
"""

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
    """
    Service for managing agent jobs with dual-model architecture.

    Handover 0366b: Updated to manage BOTH AgentJob and AgentExecution.

    Responsibilities:
    - Create and manage agent jobs (work orders)
    - Create and manage agent executions (executors)
    - Track job and execution status separately
    - Maintain succession chains (multiple executions per job)
    - Enforce tenant isolation
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        test_session: AsyncSession | None = None,
    ):
        """
        Initialize AgentJobManager.

        Args:
            db_manager: Database manager for async database operations
            tenant_manager: Tenant manager for multi-tenancy support
            test_session: Optional AsyncSession for tests to share the same transaction
        """
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._test_session = test_session
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def spawn_execution(
        self,
        job_id: str,
        agent_display_name: str,
        tenant_key: str,
        spawned_by: str | None = None,
    ) -> tuple[str, str]:
        """
        Spawn a NEW execution for an EXISTING job (Handover 0769a).

        Creates an AgentExecution (executor instance) for an existing AgentJob.
        Enables agent succession while preserving job continuity.

        Args:
            job_id: AgentJob UUID to spawn execution for (must exist)
            agent_display_name: Display name for this executor
            tenant_key: Tenant key for multi-tenant isolation
            spawned_by: Parent executor's agent_id (for succession tracking)

        Returns:
            Tuple of (job_id, agent_id)

        Raises:
            ResourceNotFoundError: Job not found for tenant
            BaseGiljoError: Database operation failed
        """
        try:
            # FE-9490: this is the succession write boundary for agent_display_name
            # (a NEW executor for an existing job) -- reject punctuation before it
            # reaches the DB. See giljo_mcp.utils.identity for the character policy.
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
                    started_at=datetime.now(UTC),  # IMP-5036 task a8d7dac0
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
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to spawn execution")
            raise BaseGiljoError(message=str(e), context={"operation": "spawn_execution", "job_id": job_id}) from e

    # ============================================================================
    # Job Completion (decommissions all executions)
    # ============================================================================

    async def complete_job(
        self,
        job_id: str,
        tenant_key: str,
    ) -> int:
        """
        Complete a job (marks job complete and decommissions all executions).

        Handover 0366b: Updates BOTH AgentJob and ALL AgentExecutions.
        Handover 0730b: Converted to exception-based error handling.

        Args:
            job_id: Job ID to complete
            tenant_key: Tenant key for multi-tenant isolation

        Returns:
            Number of executions decommissioned

        Raises:
            ResourceNotFoundError: Job not found
            BaseGiljoError: Database operation failed

        Example:
            >>> count = await manager.complete_job(
            ...     job_id="job-uuid-123",
            ...     tenant_key="tenant-abc"
            ... )
            >>> print(f"Decommissioned {count} execution(s)")
        """
        try:
            repo = AgentJobRepository(None)
            async with self._get_session(tenant_key) as session:
                job, executions = await repo.complete_job_with_executions(session, tenant_key, job_id)

                if not job:
                    raise ResourceNotFoundError(message=f"Job {job_id} not found", context={"job_id": job_id})

                self._logger.info(f"Completed job {job_id} and marked {len(executions)} execution(s) as complete")

                return len(executions)

        except (ResourceNotFoundError, BaseGiljoError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to complete job")
            raise BaseGiljoError(message=str(e), context={"operation": "complete_job"}) from e

    async def list_team_agents(
        self,
        job_id: str,
        tenant_key: str,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List agent executions (teammates) associated with this job.

        Handover 0360 Feature 2: Team Discovery Tool.

        Enables agents to discover teammates working on the same job/project.
        Returns execution details (agent_id, job_id, agent_display_name, status).

        Args:
            job_id: Job ID to get teammates for
            tenant_key: Tenant key for multi-tenant isolation
            include_inactive: If True, include completed/decommissioned executions

        Returns:
            List of dict with team member details:
            [
                {
                    "agent_id": "ae-001",
                    "job_id": "job-abc",
                    "agent_display_name": "Orchestrator",
                    "status": "working",
                    "agent_name": "Orchestrator Instance 1",
                    "tenant_key": "tenant-abc"
                },
                ...
            ]

        Example:
            >>> teammates = await manager.list_team_agents(
            ...     job_id="job-uuid-123",
            ...     tenant_key="tenant-abc",
            ...     include_inactive=False
            ... )
            >>> for member in teammates:
            ...     print(f"{member['agent_display_name']}: {member['status']}")
        """
        try:
            repo = AgentJobRepository(None)
            async with self._get_session(tenant_key) as session:
                executions = await repo.list_team_executions(session, tenant_key, job_id, include_inactive)

                # Convert to dict format
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

        except Exception as _exc:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to list team agents")
            return []
