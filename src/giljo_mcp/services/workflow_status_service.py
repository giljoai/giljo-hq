# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import DatabaseError, ResourceNotFoundError
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.schemas.service_responses import (
    AgentTodoCounts,
    AgentWorkflowDetail,
    ThreadUnreadDetail,
    WorkflowStatus,
    build_next_action,
)
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.project_helpers import compute_completion_percent
from giljo_mcp.services.settings_service import resolve_checkin_cadence_safe
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


class WorkflowStatusService:

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
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._test_session
        )

    async def get_workflow_status(
        self,
        project_id: str,
        tenant_key: str,
        exclude_job_id: str | None = None,
    ) -> WorkflowStatus:
        try:
            job_repo = AgentJobRepository(None)
            ops_repo = AgentOperationsRepository()
            async with self._get_session(tenant_key) as session:
                project = await job_repo.get_project_by_id(session, tenant_key, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message=f"Project '{project_id}' not found",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )

                executions = await ops_repo.get_workflow_executions(session, tenant_key, project_id, exclude_job_id)

                job_type_map = {ex.job_id: ex.job_type or "" for ex in executions}
                active_count = sum(1 for ex in executions if ex.status == "working")
                completed_count = sum(1 for ex in executions if ex.status == "complete")
                closed_count = sum(1 for ex in executions if ex.status == "closed")
                pending_count = sum(1 for ex in executions if ex.status == "waiting")
                blocked_count = sum(1 for ex in executions if ex.status == "blocked")
                silent_count = sum(1 for ex in executions if ex.status == "silent")
                decommissioned_count = sum(1 for ex in executions if ex.status == "decommissioned")
                total_count = len(executions)

                done_count = completed_count + closed_count
                actionable_count = total_count - decommissioned_count
                progress_percent = compute_completion_percent(done_count, total_count, decommissioned_count)

                if total_count == 0:
                    current_stage = "Not started"
                elif done_count == actionable_count:
                    current_stage = "Completed"
                elif blocked_count > 0 and silent_count > 0:
                    current_stage = f"In Progress ({blocked_count} blocked, {silent_count} silent)"
                elif blocked_count > 0:
                    current_stage = f"In Progress ({blocked_count} blocked)"
                elif silent_count > 0:
                    current_stage = f"In Progress ({silent_count} silent)"
                elif active_count > 0:
                    current_stage = "In Progress"
                elif pending_count > 0:
                    current_stage = "Pending"
                else:
                    current_stage = "Unknown"

                if exclude_job_id:
                    caller_note = "Your job was excluded from these counts."
                else:
                    caller_note = "Note: You (the calling agent) are included in the active count above."

                if blocked_count > 0 or silent_count > 0:
                    caller_note += (
                        " This project looks wedged (blocked/silent agents present) -- call "
                        "diagnose_project_state(project_id) for the stuck condition and the "
                        "suggested recovery step."
                    )

                ready_to_advance = getattr(project, "closeout_executed_at", None) is not None
                next_action: dict[str, Any] | None = None
                if blocked_count > 0 or silent_count > 0:
                    next_action = build_next_action(
                        tool="diagnose_project_state",
                        args_hint={"project_id": project_id},
                        why=(
                            "This project looks wedged (blocked/silent agents present) -- get the "
                            "stuck condition and the suggested recovery step."
                        ),
                    )
                elif total_count > 0 and done_count == actionable_count and not ready_to_advance:
                    next_action = build_next_action(
                        tool="write_project_closeout",
                        args_hint={"project_id": project_id},
                        why="All agents finished -- call write_project_closeout to record the project closeout.",
                    )

                agent_details = await self._build_agent_details(
                    session, tenant_key, project_id, executions, job_type_map, ops_repo
                )

                checkin_cadence_minutes = await resolve_checkin_cadence_safe(session, tenant_key, project)

                return WorkflowStatus(
                    active_agents=active_count,
                    completed_agents=completed_count,
                    closed_agents=closed_count,
                    pending_agents=pending_count,
                    blocked_agents=blocked_count,
                    silent_agents=silent_count,
                    decommissioned_agents=decommissioned_count,
                    current_stage=current_stage,
                    progress_percent=round(progress_percent, 2),
                    total_agents=total_count,
                    caller_note=caller_note,
                    agents=agent_details,
                    auto_checkin_enabled=bool(getattr(project, "auto_checkin_enabled", False)),
                    auto_checkin_interval=getattr(project, "auto_checkin_interval", None),
                    checkin_cadence_minutes=checkin_cadence_minutes,
                    project_closeout_at=(
                        project.closeout_executed_at.isoformat()
                        if getattr(project, "closeout_executed_at", None) is not None
                        else None
                    ),
                    staging_status=getattr(project, "staging_status", None),
                    ready_to_advance=ready_to_advance,
                    next_action=next_action,
                )

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to get workflow status")
            raise DatabaseError(
                message=f"Failed to get workflow status: {e!s}",
                context={"project_id": project_id, "tenant_key": tenant_key},
            ) from e

    async def _build_agent_details(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        executions: list[Any],
        job_type_map: dict[str, str],
        ops_repo: AgentOperationsRepository,
    ) -> list[AgentWorkflowDetail]:
        if not executions:
            return []

        job_ids = [ex.job_id for ex in executions]
        todo_map = await ops_repo.get_todo_counts_by_job(session, tenant_key, job_ids)

        agent_ids = [ex.agent_id for ex in executions if ex.agent_id]
        unread_map = await ops_repo.get_live_unread_counts_by_agent(session, tenant_key, project_id, agent_ids)
        action_required_map = await ops_repo.get_live_action_required_unread_counts_by_agent(
            session, tenant_key, project_id, agent_ids
        )
        thread_breakdown_map = await ops_repo.get_live_unread_counts_by_agent_and_thread(
            session, tenant_key, project_id, agent_ids
        )

        agent_details: list[AgentWorkflowDetail] = []
        for execution in executions:
            counts = todo_map.get(execution.job_id, {})
            agent_details.append(
                AgentWorkflowDetail(
                    job_id=execution.job_id,
                    agent_id=execution.agent_id,
                    agent_name=execution.agent_name or "",
                    display_name=execution.agent_display_name or "",
                    status=execution.status or "",
                    job_type=job_type_map.get(execution.job_id, ""),
                    unread_messages=unread_map.get(execution.agent_id, 0),
                    action_required_unread=action_required_map.get(execution.agent_id, 0),
                    unread_by_thread=[
                        ThreadUnreadDetail(thread_id=tid, unread_count=cnt)
                        for tid, cnt in thread_breakdown_map.get(execution.agent_id, {}).items()
                    ],
                    todos=AgentTodoCounts(
                        completed=counts.get("completed", 0),
                        in_progress=counts.get("in_progress", 0),
                        pending=counts.get("pending", 0),
                        skipped=counts.get("skipped", 0),
                    ),
                )
            )
        return agent_details
