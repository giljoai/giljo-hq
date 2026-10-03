# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from collections import Counter, defaultdict
from contextlib import nullcontext

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.job_activity import activity_word
from giljo_mcp.exceptions import OrchestrationError, ResourceNotFoundError
from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.schemas.service_responses import JobListResult
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.not_picked_up import not_picked_up_job_ids
from giljo_mcp.services.settings_service import resolve_checkin_cadence_safe
from giljo_mcp.services.silence_detector import stale_orchestrator_states
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class JobQueryService:

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

    async def list_jobs(
        self,
        tenant_key: str,
        project_id: str | None = None,
        status_filter: str | None = None,
        agent_display_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> JobListResult:
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

                live_project_ids = [str(job.project_id) for _ex, job in rows if job.project_id]
                live_agent_ids = [ex.agent_id for ex, _job in rows if ex.agent_id]
                live_unread = await ops_repo.get_live_unread_counts_by_project_agent(
                    session, tenant_key, live_project_ids, live_agent_ids
                )
                live_action_required = await ops_repo.get_live_action_required_unread_counts_by_project_agent(
                    session, tenant_key, live_project_ids, live_agent_ids
                )

                not_picked_up = await self._not_picked_up_executions(session, tenant_key, rows)
                orchestrator_states = await self._orchestrator_states(session, tenant_key, rows)
                job_dicts = [
                    self._build_job_dict(
                        execution, job, live_unread, live_action_required, not_picked_up, orchestrator_states
                    )
                    for execution, job in rows
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

                not_picked_up = await self._not_picked_up_executions(session, tenant_key, [(execution, job)])
                orchestrator_states = await self._orchestrator_states(session, tenant_key, [(execution, job)])
                return self._build_job_dict(
                    execution, job, live_unread, live_action_required, not_picked_up, orchestrator_states
                )

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to get job detail")
            raise OrchestrationError(
                message="Failed to get job detail",
                context={"job_id": job_id, "tenant_key": tenant_key, "error": str(e)},
            ) from e

    async def _not_picked_up_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        rows: list[tuple[AgentExecution, AgentJob]],
    ) -> set[str]:
        by_project: dict[str, list[tuple]] = defaultdict(list)
        for execution, job in rows:
            if execution.status == "waiting" and job.project_id:
                by_project[str(job.project_id)].append((execution.id, execution.status, job.job_id))
        if not by_project:
            return set()

        projects = (
            (
                await session.execute(
                    select(Project).where(Project.tenant_key == tenant_key, Project.id.in_(list(by_project)))
                )
            )
            .scalars()
            .all()
        )
        flagged: set[str] = set()
        for project in projects:
            cadence = await resolve_checkin_cadence_safe(session, tenant_key, project)
            flagged |= await not_picked_up_job_ids(session, tenant_key, project, by_project[str(project.id)], cadence)
        return flagged

    async def _orchestrator_states(
        self,
        session: AsyncSession,
        tenant_key: str,
        rows: list[tuple[AgentExecution, AgentJob]],
    ) -> dict:
        project_ids = sorted(
            {
                str(job.project_id)
                for execution, job in rows
                if execution.status == "silent" and job.job_type == "orchestrator" and job.project_id
            }
        )
        return await stale_orchestrator_states(session, tenant_key, project_ids=project_ids)

    def _build_job_dict(
        self,
        execution: AgentExecution,
        job: AgentJob,
        live_unread: dict,
        live_action_required: dict,
        not_picked_up: set[str] | None = None,
        orchestrator_states: dict | None = None,
    ) -> dict:
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
            "chain_conductor": bool((job.job_metadata or {}).get("chain_conductor", False)),
            "agent_display_name": execution.agent_display_name,
            "agent_name": execution.agent_name,
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
            "duration_seconds": execution.duration_seconds,
            "working_started_at": execution.working_started_at.isoformat() if execution.working_started_at else None,
            "not_picked_up": execution.id in (not_picked_up or set()),
            "activity": activity_word(execution.status, Counter(item.status for item in job.todo_items or [])),
            "orchestrator_state": (
                state.model_dump() if (state := (orchestrator_states or {}).get(job.job_id)) is not None else None
            ),
        }

    async def get_job_messages(
        self,
        tenant_key: str,
        job_id: str,
        limit: int = 50,
    ) -> dict:
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
        try:
            if job.todo_items:
                total = len(job.todo_items)
                completed = sum(1 for item in job.todo_items if item.status == "completed")
                skipped = sum(1 for item in job.todo_items if item.status == "skipped")
                if total > 0:
                    return {"total": total, "completed": completed, "skipped": skipped}
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


    async def get_execution_by_agent_id(
        self,
        tenant_key: str,
        agent_id: str,
        session: AsyncSession | None = None,
    ) -> AgentExecution | None:
        repo = AgentJobRepository(None)
        async with nullcontext(session) if session is not None else self._get_session(tenant_key) as active:
            return await repo.get_execution_by_agent_id(session=active, tenant_key=tenant_key, agent_id=agent_id)

    async def get_execution_by_job_id(
        self,
        tenant_key: str,
        job_id: str,
        session: AsyncSession | None = None,
    ) -> AgentExecution | None:
        repo = AgentJobRepository(None)
        async with nullcontext(session) if session is not None else self._get_session(tenant_key) as active:
            return await repo.get_execution_by_job_id(session=active, tenant_key=tenant_key, job_id=job_id)

    async def get_agent_job_by_job_id(
        self,
        tenant_key: str,
        job_id: str,
        session: AsyncSession | None = None,
    ) -> AgentJob | None:
        repo = AgentJobRepository(None)
        async with nullcontext(session) if session is not None else self._get_session(tenant_key) as active:
            return await repo.get_agent_job_by_job_id(session=active, tenant_key=tenant_key, job_id=job_id)

    async def get_latest_execution_for_job(
        self,
        tenant_key: str,
        job_id: str,
        session: AsyncSession | None = None,
    ) -> AgentExecution | None:
        repo = AgentJobRepository(None)
        async with nullcontext(session) if session is not None else self._get_session(tenant_key) as active:
            return await repo.get_latest_execution_for_job(session=active, tenant_key=tenant_key, job_id=job_id)
