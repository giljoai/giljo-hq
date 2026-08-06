# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Service for the user_approvals primitive (BE-5029 Phase A).

The single validated write path. ``create_pending`` is atomic: it inserts the
user_approvals row, flips the agent's execution status to ``awaiting_user``, and
emits a WebSocket broadcast in the same transaction. If any step fails the
transaction rolls back.

Edition Scope: Both.
"""

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
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.repositories.user_approval_repository import UserApprovalRepository
from giljo_mcp.schemas.jsonb_validators import (
    validate_user_approval_context,
    validate_user_approval_options,
)
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


async def build_awaiting_user_blocker(
    session: AsyncSession, execution: AgentExecution, tenant_key: str
) -> dict[str, Any]:
    """Closeout blocker dict for an agent parked on a pending user_approval.

    Returns the standard blocker shape with ``approval_id`` resolved so callers
    can deep-link to ``POST /api/approvals/{id}/decide``.
    """
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


class UserApprovalService:
    """Single owning service for user_approvals writes."""

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
        # BE-9012d: the bus's send_message notify was replaced by a Hub post to the
        # project's bound thread (CommThreadService.resolve_or_create_bound_thread +
        # post_to_thread) — see _notify_orchestrator_of_decision.
        self._comm_thread_service = comm_thread_service

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        return optional_tenant_session(self.db_manager, effective_tenant_key, self._test_session)

    async def _resolve_execution(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution:
        """Resolve the most recent AgentExecution for a job within the tenant."""
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
        """Atomically create a pending approval and flip the agent to awaiting_user.

        BE-9153: ``park_execution`` (default True — every pre-existing caller is
        byte-identical) may be set False to create the approval WITHOUT parking the
        agent in ``awaiting_user`` and WITHOUT broadcasting the park. That is the
        chain-settlement path: a findings-bearing chain link is accepted
        PROVISIONALLY (the agent completes, the conductor advances) while its
        approval joins the settlement queue that gates the CHAIN's own closeout.

        Single-pending-per-agent invariant: a second pending approval for the same
        execution is rejected with ValidationError (matches ``blocked`` semantics).

        BE-9054 (a): orchestrator-only. The dashboard's Approve/Reject UI
        (CloseoutModal -> ApprovalCard) binds to the ORCHESTRATOR's job, so an
        approval created by a worker job would park that agent in awaiting_user
        with no UI able to clear it. Rejected here with
        ``error_code="ORCHESTRATOR_ONLY_APPROVAL"``; the MCP tool adapter converts
        that into the BE-6081 structured domain rejection.

        BE-9054 (b): the execution's pre-approval status is recorded under the
        server-reserved ``pre_approval_status`` context key (agent-supplied values
        for that key are stripped — never trusted) so ``mark_decided`` can restore
        it instead of hardcoding ``working``. Only recorded when it differs from
        ``working`` (absence == restore to ``working``).
        """
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
            # Server-reserved key: an agent-supplied value must never drive the
            # post-decide status restore (it could smuggle in 'complete' and skip
            # completion gates).
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

            # BE-9153: the chain-settlement path (park_execution=False) creates the
            # approval but leaves the execution free to complete (provisional link
            # closeout); no awaiting_user park, no park broadcast.
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
    ) -> tuple[list[UserApproval], int]:
        """Read-only list of pending approvals scoped to ``tenant_key``.

        Tenant isolation: the repository query filters by ``tenant_key``.
        Cross-tenant rows are unreachable. Returns ``(rows, total_count)``.
        """
        if limit < 1 or limit > 200:
            raise ValidationError(f"limit must be 1..200 (got {limit})")
        if offset < 0:
            raise ValidationError(f"offset must be >= 0 (got {offset})")

        async with self._get_session(tenant_key) as session:
            rows = await self._repo.list_pending_for_tenant(
                session,
                tenant_key=tenant_key,
                limit=limit,
                offset=offset,
            )
            total = await self._repo.count_pending_for_tenant(
                session,
                tenant_key=tenant_key,
            )
        return rows, total

    async def mark_decided(
        self,
        *,
        tenant_key: str,
        approval_id: str,
        option_id: str,
        user_id: str | None,
    ) -> UserApproval:
        """Atomically resolve a pending approval and resume the awaiting agent.

        Single transaction: validates option_id, validates pending status, sets
        ``decided_*`` fields, flips the bound execution from ``awaiting_user``
        back to its pre-approval status (BE-9054 (b): recorded by
        ``create_pending`` under the ``pre_approval_status`` context key;
        ``working`` when absent — legacy rows and the common case), then
        broadcasts the resume on the existing ``agent:status_changed`` channel.
        An already-finished agent (e.g. ``complete``) is therefore no longer
        resurrected to ``working``, which used to block its own closeout.
        Cross-tenant access is rejected as ``ResourceNotFoundError`` (do not
        leak existence).
        """
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
            )
            if decided is None:
                # Lost race: another caller flipped status between get and update.
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
        """BE-9153: re-check a chain's closeout when one of its SETTLEMENT approvals is decided.

        A findings-bearing chain link was accepted provisionally; its settlement
        approval gates the CHAIN's own closeout (see
        ``project_helpers.complete_chain_run_if_finished``). Deciding it (via the REST
        ``/decide`` endpoint or the MCP inline-approval path — both route through
        ``mark_decided``) must re-trigger that check so the run purges once the LAST
        settlement approval is resolved.

        Best-effort / non-fatal: the decide's status flip + broadcast already
        committed upstream; a drain failure here must NEVER fail the decide.
        """
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
        """Post a 'user decided' message to the orchestrator's Hub bound thread so the
        agent learns the choice on its next get_thread_history poll.

        BE-9012d: the bus's send_message notify was retired; this now resolves the
        project's bound Hub thread and posts a DIRECTED, action-required message to
        the agent's agent_id (mirrors the wake semantics the bus notify used to carry
        — see the MCP wrapper / REST adapter's auto_block_for_thread_post pairing for
        the same directed+requires_action pattern).

        Best-effort: failure here must not roll back the decide transaction. The
        status flip + WebSocket broadcast have already happened upstream; the Hub
        post is the explicit semantic channel the agent reads.
        """
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
            # BE-9292a-F2: a DECLINED post is RETURNED, not raised (the BE-6081 domain
            # rejection shape), so the except below never sees it. Until BE-9292a this
            # call could not be declined at all — it forwards no baton, and only the
            # baton target was screened; screening the addressee made a refusal reachable
            # here. Left unread it would drop the gate-cleared notice in total silence
            # while the orchestrator polls a thread that will never tell it. Best-effort
            # stays best-effort: this reports, it does not raise.
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
                    "duration_seconds": execution.duration_seconds,  # BE-5107
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
                    "duration_seconds": execution.duration_seconds,  # BE-5107
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
