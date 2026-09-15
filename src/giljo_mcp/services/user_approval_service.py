# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import VALID_USER_APPROVAL_STATUSES, UserApproval
from giljo_mcp.repositories.user_approval_repository import UserApprovalRepository
from giljo_mcp.schemas.jsonb_validators import (
    validate_user_approval_context,
    validate_user_approval_options,
)
from giljo_mcp.schemas.user_approval import UserApprovalRead
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


async def build_awaiting_user_blocker(
    session: AsyncSession, execution: AgentExecution, tenant_key: str
) -> dict[str, Any]:
    stmt = select(UserApproval.id).where(
        UserApproval.tenant_key == tenant_key,
        UserApproval.agent_execution_id == execution.id,
        UserApproval.status == "pending",
    )
    approval_id = (await session.execute(stmt)).scalar_one_or_none()
    return {
        "agent_id": execution.agent_id,
        "agent_name": getattr(execution, "agent_name", None) or execution.agent_display_name,
        "status": "awaiting_user",
        "job_id": execution.job_id,
        "issue_type": "awaiting_user_approval",
        "approval_id": approval_id,
        "suggested_action": f"Resolve approval {approval_id} via POST /api/approvals/{approval_id}/decide.",
    }


def _compute_approval_banner_state(*, project: Project | None, execution: AgentExecution | None) -> str:
    if (
        project is not None
        and project.staging_status == "staging_complete"
        and project.implementation_launched_at is None
    ):
        return "waiting_at_staging"
    if execution is not None and execution.status == "blocked":
        return "blocked"
    return "decision_needed"


class UserApprovalService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        websocket_manager: Any | None = None,
        test_session: AsyncSession | None = None,
        comm_thread_service: Any | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._websocket_manager = websocket_manager
        self._test_session = test_session
        self._repo = UserApprovalRepository(db_manager)
        self._comm_thread_service = comm_thread_service

    def _get_session(self, tenant_key: str | None = None):
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        return optional_tenant_session(self.db_manager, effective_tenant_key, self._test_session)

    async def _resolve_execution(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution:
        result = await session.execute(
            select(AgentExecution)
            .where(
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.job_id == job_id,
            )
            .order_by(AgentExecution.started_at.desc().nullslast())
            .limit(1)
        )
        execution = result.scalar_one_or_none()
        if execution is None:
            raise ResourceNotFoundError(f"No AgentExecution for job_id={job_id}")
        return execution

    async def _verify_job(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        job_id: str,
        project_id: str,
    ) -> AgentJob:
        result = await session.execute(
            select(AgentJob).where(
                AgentJob.tenant_key == tenant_key,
                AgentJob.job_id == job_id,
            )
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise ResourceNotFoundError(f"No AgentJob for job_id={job_id}")
        if job.project_id != project_id:
            raise ValidationError(f"job_id={job_id} does not belong to project_id={project_id}")
        return job

    async def create_pending(
        self,
        *,
        tenant_key: str,
        job_id: str,
        project_id: str,
        reason: str,
        options: list[dict],
        context: dict | None,
        park_execution: bool = True,
    ) -> UserApproval:
        validated_options = validate_user_approval_options(options)
        validated_context = validate_user_approval_context(context)

        async with self._get_session(tenant_key) as session:
            job = await self._verify_job(
                session,
                tenant_key=tenant_key,
                job_id=job_id,
                project_id=project_id,
            )
            if job.job_type != "orchestrator":
                raise ValidationError(
                    message=(
                        "request_approval is orchestrator-only: the dashboard approval card binds "
                        "to the orchestrator's job, so a worker approval would park the agent in "
                        "awaiting_user with nothing able to clear it. Escalate the decision to "
                        "your orchestrator via post_to_thread instead."
                    ),
                    error_code="ORCHESTRATOR_ONLY_APPROVAL",
                    context={"job_id": job_id, "job_type": job.job_type},
                )
            execution = await self._resolve_execution(
                session,
                tenant_key=tenant_key,
                job_id=job_id,
            )

            existing = await self._repo.get_pending_for_agent(
                session,
                tenant_key=tenant_key,
                agent_execution_id=execution.id,
            )
            if existing is not None:
                raise ValidationError(f"Agent execution {execution.id} already has a pending approval ({existing.id})")

            old_status = execution.status
            stored_context = dict(validated_context) if validated_context else {}
            stored_context.pop("pre_approval_status", None)
            if old_status and old_status != "working":
                stored_context["pre_approval_status"] = old_status

            approval = await self._repo.create(
                session,
                tenant_key=tenant_key,
                agent_execution_id=execution.id,
                job_id=job_id,
                project_id=project_id,
                reason=reason,
                options=validated_options,
                context=stored_context or None,
            )

            if park_execution:
                execution.status = "awaiting_user"

            await session.commit()
            await session.refresh(approval)
            await session.refresh(execution)

        if park_execution:
            await self._broadcast_status_change(
                tenant_key=tenant_key,
                job_id=job_id,
                project_id=project_id,
                execution=execution,
                old_status=old_status,
                approval_id=approval.id,
            )
        return approval

    async def list_pending(
        self,
        *,
        tenant_key: str,
        limit: int = 50,
        offset: int = 0,
        status: str = "pending",
    ) -> tuple[list[UserApprovalRead], int]:
        if limit < 1 or limit > 200:
            raise ValidationError(f"limit must be 1..200 (got {limit})")
        if offset < 0:
            raise ValidationError(f"offset must be >= 0 (got {offset})")
        if status not in VALID_USER_APPROVAL_STATUSES:
            raise ValidationError(f"status must be one of {sorted(VALID_USER_APPROVAL_STATUSES)} (got {status!r})")

        async with self._get_session(tenant_key) as session:
            rows = await self._repo.list_pending_for_tenant(
                session,
                tenant_key=tenant_key,
                limit=limit,
                offset=offset,
                status=status,
            )
            total = await self._repo.count_pending_for_tenant(
                session,
                tenant_key=tenant_key,
                status=status,
            )
            reads = await self._build_reads_with_banner_context(session, tenant_key=tenant_key, rows=rows)
        return reads, total

    async def _build_reads_with_banner_context(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        rows: list[UserApproval],
    ) -> list[UserApprovalRead]:
        if not rows:
            return []

        project_ids = {row.project_id for row in rows}
        execution_ids = {row.agent_execution_id for row in rows}

        projects_result = await session.execute(
            select(Project).where(Project.tenant_key == tenant_key, Project.id.in_(project_ids))
        )
        projects_by_id = {p.id: p for p in projects_result.scalars().all()}

        executions_result = await session.execute(
            select(AgentExecution).where(AgentExecution.tenant_key == tenant_key, AgentExecution.id.in_(execution_ids))
        )
        executions_by_id = {e.id: e for e in executions_result.scalars().all()}

        reads = []
        for row in rows:
            project = projects_by_id.get(row.project_id)
            execution = executions_by_id.get(row.agent_execution_id)
            reads.append(
                UserApprovalRead(
                    id=row.id,
                    tenant_key=row.tenant_key,
                    agent_execution_id=row.agent_execution_id,
                    job_id=row.job_id,
                    project_id=row.project_id,
                    reason=row.reason,
                    options=row.options,
                    context=row.context,
                    status=row.status,
                    decided_option_id=row.decided_option_id,
                    decided_by_user_id=row.decided_by_user_id,
                    decided_via=row.decided_via,
                    requested_at=row.requested_at,
                    decided_at=row.decided_at,
                    banner_state=_compute_approval_banner_state(project=project, execution=execution),
                    taxonomy_alias=project.taxonomy_alias if project is not None else None,
                    product_id=project.product_id if project is not None else None,
                )
            )
        return reads

    async def mark_decided(
        self,
        *,
        tenant_key: str,
        approval_id: str,
        option_id: str,
        user_id: str | None,
        decided_via: str,
    ) -> UserApproval:
        if decided_via not in ("ui", "mcp"):
            raise ValidationError(f"decided_via must be 'ui' or 'mcp' (got {decided_via!r})")

        async with self._get_session(tenant_key) as session:
            approval = await self._repo.get_by_id(
                session,
                tenant_key=tenant_key,
                approval_id=approval_id,
            )
            if approval is None:
                raise ResourceNotFoundError(f"UserApproval id={approval_id} not found")

            if approval.status != "pending":
                raise ValidationError(f"UserApproval id={approval_id} is not pending (status={approval.status})")

            valid_option_ids = {opt.get("id") for opt in (approval.options or [])}
            if option_id not in valid_option_ids:
                raise ValidationError(
                    f"option_id={option_id!r} not in approval.options (valid: {sorted(valid_option_ids)})"
                )

            decided = await self._repo.mark_decided(
                session,
                tenant_key=tenant_key,
                approval_id=approval_id,
                decided_option_id=option_id,
                decided_by_user_id=user_id,
                decided_via=decided_via,
            )
            if decided is None:
                raise ValidationError(f"UserApproval id={approval_id} was modified concurrently; retry")

            execution = await self._resolve_execution(
                session,
                tenant_key=tenant_key,
                job_id=decided.job_id,
            )
            old_status = execution.status
            if old_status == "awaiting_user":
                pre_approval_status = (decided.context or {}).get("pre_approval_status")
                if isinstance(pre_approval_status, str) and pre_approval_status not in ("", "awaiting_user"):
                    execution.status = pre_approval_status
                else:
                    execution.status = "working"

            await session.commit()
            await session.refresh(decided)
            await session.refresh(execution)

        await self._broadcast_resume(
            tenant_key=tenant_key,
            job_id=decided.job_id,
            project_id=decided.project_id,
            execution=execution,
            old_status=old_status,
            approval_id=decided.id,
            decided_option_id=option_id,
        )
        await self._notify_orchestrator_of_decision(
            tenant_key=tenant_key,
            execution=execution,
            decided=decided,
            option_id=option_id,
        )
        await self._drain_chain_settlement_if_applicable(decided=decided, tenant_key=tenant_key)
        return decided

    async def _drain_chain_settlement_if_applicable(self, *, decided: UserApproval, tenant_key: str) -> None:
        ctx = decided.context or {}
        if ctx.get("chain_settlement") is not True:
            return
        conductor_agent_id = ctx.get("conductor_agent_id")
        if not conductor_agent_id:
            return
        try:
            from giljo_mcp.services.project_helpers import complete_chain_run_if_finished

            await complete_chain_run_if_finished(
                db_manager=self.db_manager,
                tenant_manager=self.tenant_manager,
                conductor_agent_id=str(conductor_agent_id),
                tenant_key=tenant_key,
                test_session=self._test_session,
                websocket_manager=self._websocket_manager,
            )
        except Exception:  # noqa: BLE001 — best-effort settlement drain; never fail the decide
            logger.warning("[BE-9153] chain settlement drain failed (non-fatal)", exc_info=True)

    async def _notify_orchestrator_of_decision(
        self,
        *,
        tenant_key: str,
        execution: AgentExecution,
        decided: UserApproval,
        option_id: str,
    ) -> None:
        if self._comm_thread_service is None:
            return
        agent_id = execution.agent_id
        if not agent_id:
            return
        option_label = option_id
        for opt in decided.options or []:
            if isinstance(opt, dict) and opt.get("id") == option_id:
                option_label = opt.get("label") or option_id
                break
        content = (
            f"User decided your approval request.\n"
            f"Choice: {option_label} (option_id={option_id})\n"
            f"Original question: {decided.reason}\n\n"
            f"The awaiting_user gate is cleared. You may proceed."
        )
        try:
            thread = await self._comm_thread_service.resolve_or_create_bound_thread(
                project_id=decided.project_id, tenant_key=tenant_key
            )
            posted = await self._comm_thread_service.post_to_thread(
                thread_id=thread["thread_id"],
                content=content,
                from_agent="user",
                to_participant=agent_id,
                message_type="direct",
                priority="normal",
                requires_action=True,
                tenant_key=tenant_key,
            )
            if isinstance(posted, dict) and posted.get("success") is False:
                logger.warning(
                    "[USER_APPROVAL] Hub declined the decision notice approval=%s job=%s to=%s: %s",
                    decided.id,
                    decided.job_id,
                    agent_id,
                    posted.get("error"),
                )
        except Exception as exc:  # noqa: BLE001 - Hub delivery is non-critical
            logger.warning(
                "[USER_APPROVAL] Failed to notify orchestrator of decision approval=%s job=%s: %s",
                decided.id,
                decided.job_id,
                exc,
            )

    async def _broadcast_resume(
        self,
        *,
        tenant_key: str,
        job_id: str,
        project_id: str,
        execution: AgentExecution,
        old_status: str | None,
        approval_id: str,
        decided_option_id: str,
    ) -> None:
        if not self._websocket_manager:
            return
        try:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="agent:status_changed",
                data={
                    "job_id": job_id,
                    "project_id": project_id,
                    "tenant_key": tenant_key,
                    "agent_display_name": execution.agent_display_name,
                    "old_status": old_status,
                    "status": execution.status,
                    "user_approval_id": approval_id,
                    "decided_option_id": decided_option_id,
                    "duration_seconds": execution.duration_seconds,
                    "working_started_at": execution.working_started_at.isoformat()
                    if execution.working_started_at
                    else None,
                },
            )
        except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
            logger.warning(
                "[WEBSOCKET] Failed to broadcast user_approval resume for job=%s: %s",
                job_id,
                ws_error,
            )

    async def _broadcast_status_change(
        self,
        *,
        tenant_key: str,
        job_id: str,
        project_id: str,
        execution: AgentExecution,
        old_status: str | None,
        approval_id: str,
    ) -> None:
        if not self._websocket_manager:
            return
        try:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="agent:status_changed",
                data={
                    "job_id": job_id,
                    "project_id": project_id,
                    "tenant_key": tenant_key,
                    "agent_display_name": execution.agent_display_name,
                    "old_status": old_status,
                    "status": "awaiting_user",
                    "user_approval_id": approval_id,
                    "duration_seconds": execution.duration_seconds,
                    "working_started_at": execution.working_started_at.isoformat()
                    if execution.working_started_at
                    else None,
                },
            )
        except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
            logger.warning(
                "[WEBSOCKET] Failed to broadcast user_approval status change for job=%s: %s",
                job_id,
                ws_error,
            )
