# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
JobQueryService - Agent job listing and queries.

Sprint 002e: Extracted from OrchestrationService to reduce god-class size.
list_jobs is completely self-contained (169 lines) -- pure read query with pagination.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import OrchestrationError, ResourceNotFoundError
from giljo_mcp.models import AgentExecution, AgentJob
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.schemas.service_responses import JobListResult
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class JobQueryService:
    """Service for listing and querying agent jobs.

    Extracted from OrchestrationService (Sprint 002e).
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

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def list_jobs(
        self,
        tenant_key: str,
        project_id: str | None = None,
        status_filter: str | None = None,
        agent_display_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> JobListResult:
        """List agent jobs with flexible filtering.

        Handover 0358b: Migrated to dual-model (AgentJob + AgentExecution).
        Supports filtering by project, status, and agent display name with pagination.
        All jobs are filtered by tenant_key for multi-tenant isolation.

        Args:
            tenant_key: Tenant key for isolation (required)
            project_id: Filter by project UUID (optional)
            status_filter: Filter by execution status (optional)
            agent_display_name: Filter by agent display name (optional)
            limit: Maximum results (default 100, max 500)
            offset: Pagination offset (default 0)

        Returns:
            JobListResult with jobs, total count, limit and offset
        """
        try:
            ops_repo = AgentOperationsRepository()
            async with self._get_session(tenant_key) as session:
                rows, total = await ops_repo.list_jobs_paginated(
                    session,
                    tenant_key,
                    project_id,
                    status_filter,
                    agent_display_name,
                    limit,
                    offset,
                )

                # BE-6200 (#3): messages_waiting_count must be the LIVE pending count
                # (excluding completion_report system notifications), not the
                # denormalized AgentExecution.messages_waiting_count column, which is
                # inflated by auto-sent completion reports — so a completed agent whose
                # only "waiting" messages are completion_reports showed a phantom
                # "N msgs" badge in the /jobs view. ONE GROUP BY keyed per
                # (project_id, agent_id) across the page (no N+1). Project-less rows
                # (chain conductor, project_id None) resolve to 0 (no project-scoped
                # messages), which is the correct behavior.
                live_project_ids = [str(job.project_id) for _ex, job in rows if job.project_id]
                live_agent_ids = [ex.agent_id for ex, _job in rows if ex.agent_id]
                live_unread = await ops_repo.get_live_unread_counts_by_project_agent(
                    session, tenant_key, live_project_ids, live_agent_ids
                )
                # BE-9273: the action-required SUBSET of live_unread (same
                # "genuinely actionable" definition the closeout gate blocks
                # on), surfaced per (project_id, agent_id) so the dashboard can
                # distinguish "someone is waiting on THIS agent to act" from
                # plain unread. Mirrors the live_unread query immediately above.
                live_action_required = await ops_repo.get_live_action_required_unread_counts_by_project_agent(
                    session, tenant_key, live_project_ids, live_agent_ids
                )

                job_dicts = [
                    self._build_job_dict(execution, job, live_unread, live_action_required) for execution, job in rows
                ]

                self._logger.info(
                    f"Listed {len(job_dicts)} jobs (total={total}, "
                    f"project={sanitize(project_id)}, status={sanitize(status_filter)})"
                )

                return JobListResult(
                    jobs=job_dicts,
                    total=total,
                    limit=limit,
                    offset=offset,
                )

        except Exception as e:
            self._logger.exception("Failed to list jobs")
            raise OrchestrationError(
                message="Failed to list jobs", context={"tenant_key": tenant_key, "error": str(e)}
            ) from e

    async def get_job_detail(self, tenant_key: str, job_id: str) -> dict:
        """Read ONE job as the same wire dict the list endpoint serves.

        BE-9330: the single-job route used to build its dict from
        ``get_agent_mission()`` -- the agent MISSION-DELIVERY payload, not a job
        record. That payload has a legitimately-empty blocked variant (the
        implementation-launch gate constructs it with ``job_id`` + block wording
        only), so a staging orchestrator's REQUIRED ``created_at`` arrived None
        and the endpoint 500'd; and it refuses any job whose execution is not
        'active', so a COMPLETED job 404'd as "wrong_state" from a read-only
        details endpoint. Both go away by reading the row.

        Raises:
            ResourceNotFoundError: no such job for this tenant (404 at the route).
        """
        try:
            ops_repo = AgentOperationsRepository()
            async with self._get_session(tenant_key) as session:
                rows, _total = await ops_repo.list_jobs_paginated(
                    session,
                    tenant_key,
                    limit=500,
                    job_id=job_id,
                )

                if not rows:
                    raise ResourceNotFoundError(
                        message=f"Job {job_id} not found",
                        context={"job_id": job_id, "tenant_key": tenant_key},
                    )

                # A job can own several executions (succession). The details view
                # describes the CURRENT executor, so pick the newest run the same
                # way AgentJobRepository.get_latest_execution_for_job does -- by
                # started_at desc, with a never-started row sorting last rather
                # than raising on the None comparison.
                execution, job = max(rows, key=lambda row: (row[0].started_at is not None, row[0].started_at))

                live_unread = {}
                live_action_required = {}
                if job.project_id and execution.agent_id:
                    live_unread = await ops_repo.get_live_unread_counts_by_project_agent(
                        session, tenant_key, [str(job.project_id)], [execution.agent_id]
                    )
                    live_action_required = await ops_repo.get_live_action_required_unread_counts_by_project_agent(
                        session, tenant_key, [str(job.project_id)], [execution.agent_id]
                    )

                return self._build_job_dict(execution, job, live_unread, live_action_required)

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to get job detail")
            raise OrchestrationError(
                message="Failed to get job detail",
                context={"job_id": job_id, "tenant_key": tenant_key, "error": str(e)},
            ) from e

    def _build_job_dict(
        self,
        execution: AgentExecution,
        job: AgentJob,
        live_unread: dict,
        live_action_required: dict,
    ) -> dict:
        """Build the wire dict for one (execution, job) row.

        BE-9330: the SINGLE producer of the shape ``job_to_response`` consumes.
        Both the list read and the single-job read go through here, so the two
        endpoints cannot disagree about the same row -- which is exactly what
        happened while the single-job route hand-built its own dict and silently
        dropped ``created_at`` (500) and ``completed_at`` (a finished job
        reported as never having completed).
        """
        self._logger.debug(
            f"[LIST_JOBS DEBUG] Agent {execution.agent_display_name} (job={job.job_id}, agent={execution.agent_id}): "
            f"{execution.messages_sent_count} sent, {execution.messages_waiting_count} waiting, {execution.messages_read_count} read"
        )

        steps_summary = self._derive_steps_summary(job)

        return {
            "job_id": job.job_id,
            "agent_id": execution.agent_id,
            "execution_id": execution.id,
            "tenant_key": execution.tenant_key,
            "project_id": job.project_id,
            # BE-6200 (#6 follow-up): flat conductor discriminator.
            # Lifted out of job_metadata so the FE can filter the
            # project-less chain conductor (and its pre-spawned
            # impl-phase execution, which DOES carry a project_id)
            # out of a project's agent lane. Kept flat, not nested
            # in job_metadata, because the WS progress handler
            # overwrites job_metadata with todo_steps.
            "chain_conductor": bool((job.job_metadata or {}).get("chain_conductor", False)),
            "agent_display_name": execution.agent_display_name,
            "agent_name": execution.agent_name,
            # ``AgentJob.mission`` is nullable BY DESIGN (NULL while staged: a
            # chain conductor is minted without one, and a specialist has none
            # until its Phase-2 mission is written), but ``JobResponse.mission``
            # is a required str. Coerce here, at the single producer, rather than
            # weakening the schema -- that would only push the None downstream.
            "mission": job.mission or "",
            "phase": job.phase,
            "status": execution.status,
            "progress": execution.progress,
            "spawned_by": execution.spawned_by,
            "tool_type": execution.tool_type,
            "context_chunks": [],
            "messages_sent_count": execution.messages_sent_count,
            "messages_waiting_count": live_unread.get((str(job.project_id), execution.agent_id), 0)
            if job.project_id
            else 0,
            # BE-9273: the subset of messages_waiting_count that will
            # actually block complete_job (requires_action + non-
            # auto_generated, not yet acked). A badge>0 with this at 0
            # is NOT blocking -- surfaced distinctly, same contract as
            # AgentWorkflowDetail.action_required_unread.
            "action_required_unread": (
                live_action_required.get((str(job.project_id), execution.agent_id), 0) if job.project_id else 0
            ),
            "messages_read_count": execution.messages_read_count,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "steps": steps_summary,
            "todo_items": [
                {"content": item.content, "status": item.status}
                for item in sorted(job.todo_items or [], key=lambda x: x.sequence)
            ],
            "result": execution.result,
            "template_id": job.template_id,
            "accumulated_duration_seconds": execution.accumulated_duration_seconds or 0.0,
            "reactivation_count": execution.reactivation_count or 0,
            "duration_seconds": execution.duration_seconds,  # BE-5107
            "working_started_at": execution.working_started_at.isoformat() if execution.working_started_at else None,
        }

    async def get_job_messages(
        self,
        tenant_key: str,
        job_id: str,
        limit: int = 50,
    ) -> dict:
        """Get messages for an agent job (for MessageAuditModal).

        Returns messages where the agent is sender or recipient,
        with resolved display names for both directions.

        Args:
            tenant_key: Tenant key for isolation
            job_id: Agent job ID to retrieve messages for
            limit: Maximum messages to retrieve (default 50, max 200)

        Returns:
            Dict with job_id, agent_id, and messages list

        Raises:
            ResourceNotFoundError: Job not found for this tenant
            OrchestrationError: Query failure
        """
        try:
            ops_repo = AgentOperationsRepository()
            async with self._get_session(tenant_key) as session:
                execution, agent_lookup, messages = await ops_repo.get_job_messages_for_agent(
                    session, tenant_key, job_id, limit
                )

                if not execution:
                    raise ResourceNotFoundError(
                        message="Job not found",
                        context={"job_id": job_id, "tenant_key": tenant_key},
                    )

                return {
                    "job_id": job_id,
                    "agent_id": execution.agent_id,
                    "agent_lookup": agent_lookup,
                    "messages": messages,
                }

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to get job messages")
            raise OrchestrationError(
                message="Failed to get job messages",
                context={"job_id": job_id, "error": str(e)},
            ) from e

    def _derive_steps_summary(self, job: AgentJob) -> dict | None:
        """Derive steps summary — live todo rows are the single source of truth (BE-9000k).

        The live ``job.todo_items`` rows (already eager-loaded for this view) are
        authoritative; the ``job_metadata['todo_steps']`` cache is a drift-prone
        denormalized copy consulted ONLY when no live rows exist — the counts-only
        reporting path (``report_progress`` with total/completed step counts but no
        ``todo_items`` list writes the cache without creating rows). This mirrors the
        messages_waiting_count precedent in ``list_jobs`` (the live query wins; the
        denormalized copy is ignored whenever live data is present), so a stale
        cache can no longer override the true row counts.
        """
        try:
            # Live rows win when present (single source of truth).
            if job.todo_items:
                total = len(job.todo_items)
                completed = sum(1 for item in job.todo_items if item.status == "completed")
                skipped = sum(1 for item in job.todo_items if item.status == "skipped")
                if total > 0:
                    return {"total": total, "completed": completed, "skipped": skipped}
            # Fallback: counts-only cache (agent reported step totals without rows).
            metadata = job.job_metadata or {}
            todo_steps = metadata.get("todo_steps") or {}
            total_steps = todo_steps.get("total_steps")
            completed_steps = todo_steps.get("completed_steps")
            skipped_steps = todo_steps.get("skipped_steps", 0)
            if (
                isinstance(total_steps, int)
                and total_steps > 0
                and isinstance(completed_steps, int)
                and 0 <= completed_steps <= total_steps
            ):
                return {
                    "total": total_steps,
                    "completed": completed_steps,
                    "skipped": skipped_steps if isinstance(skipped_steps, int) else 0,
                }
        except (KeyError, ValueError, TypeError, AttributeError):
            self._logger.warning(
                "[LIST_JOBS] Failed to derive steps summary from job_metadata",
                exc_info=True,
            )
        return None

    # ---- BE-5022b: Service wrappers for AgentJobRepository read methods ----

    async def get_execution_by_agent_id(
        self,
        tenant_key: str,
        agent_id: str,
        session: AsyncSession | None = None,
    ) -> AgentExecution | None:
        """Get agent execution by agent_id with tenant isolation.

        BE-5022b: Service wrapper for AgentJobRepository.get_execution_by_agent_id().

        Args:
            tenant_key: Tenant isolation key
            agent_id: Agent UUID
            session: Optional existing session

        Returns:
            AgentExecution or None
        """
        repo = AgentJobRepository(None)
        if session is not None:
            return await repo.get_execution_by_agent_id(session=session, tenant_key=tenant_key, agent_id=agent_id)
        async with self._get_session(tenant_key) as new_session:
            return await repo.get_execution_by_agent_id(session=new_session, tenant_key=tenant_key, agent_id=agent_id)

    async def get_execution_by_job_id(
        self,
        tenant_key: str,
        job_id: str,
        session: AsyncSession | None = None,
    ) -> AgentExecution | None:
        """Get agent execution by job_id with tenant isolation.

        BE-5022b: Service wrapper for AgentJobRepository.get_execution_by_job_id().

        Args:
            tenant_key: Tenant isolation key
            job_id: Job UUID
            session: Optional existing session

        Returns:
            AgentExecution or None
        """
        repo = AgentJobRepository(None)
        if session is not None:
            return await repo.get_execution_by_job_id(session=session, tenant_key=tenant_key, job_id=job_id)
        async with self._get_session(tenant_key) as new_session:
            return await repo.get_execution_by_job_id(session=new_session, tenant_key=tenant_key, job_id=job_id)

    async def get_agent_job_by_job_id(
        self,
        tenant_key: str,
        job_id: str,
        session: AsyncSession | None = None,
    ) -> AgentJob | None:
        """Get an agent job record by job_id with tenant isolation.

        BE-5022b: Service wrapper for AgentJobRepository.get_agent_job_by_job_id().

        Args:
            tenant_key: Tenant isolation key
            job_id: Job UUID
            session: Optional existing session

        Returns:
            AgentJob or None
        """
        repo = AgentJobRepository(None)
        if session is not None:
            return await repo.get_agent_job_by_job_id(session=session, tenant_key=tenant_key, job_id=job_id)
        async with self._get_session(tenant_key) as new_session:
            return await repo.get_agent_job_by_job_id(session=new_session, tenant_key=tenant_key, job_id=job_id)

    async def get_latest_execution_for_job(
        self,
        tenant_key: str,
        job_id: str,
        session: AsyncSession | None = None,
    ) -> AgentExecution | None:
        """Get the most recent execution for a job_id with tenant isolation.

        BE-5022b: Service wrapper for AgentJobRepository.get_latest_execution_for_job().

        Args:
            tenant_key: Tenant isolation key
            job_id: Job UUID
            session: Optional existing session

        Returns:
            AgentExecution or None
        """
        repo = AgentJobRepository(None)
        if session is not None:
            return await repo.get_latest_execution_for_job(session=session, tenant_key=tenant_key, job_id=job_id)
        async with self._get_session(tenant_key) as new_session:
            return await repo.get_latest_execution_for_job(session=new_session, tenant_key=tenant_key, job_id=job_id)
