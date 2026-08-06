# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Agent state management methods extracted from OrchestrationService.

Handles reactivation, dismissal, agent status transitions, and post-completion
side effects (memory warnings, auto-messages, WebSocket broadcasts).
"""

import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import IMMUTABLE_PROJECT_STATUSES
from giljo_mcp.exceptions import (
    AuthorizationError,
    OrchestrationError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import (
    AgentExecution,
    AgentJob,
)
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.schemas.service_responses import (
    DismissResult,
    ErrorReportResult,
    ReactivationResult,
)
from giljo_mcp.services._error_helpers import not_found_or_wrong_state_error
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.agent_terminal_cursor_service import resolve_terminal_agent_cursors
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


class OrchestrationAgentStateService:
    """Handles agent state transitions, reactivation, dismissal, and completion side effects.

    Extracted from OrchestrationService (Handover 0950) to reduce file size.
    All DB queries filter by tenant_key for multi-tenant isolation.
    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    # Handover 0880: Valid statuses for set_agent_status (agent-settable resting/blocked states)
    _AGENT_SETTABLE_STATUSES: ClassVar[set[str]] = {"blocked", "idle", "sleeping"}

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
        self._job_repo = AgentJobRepository(db_manager)

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def _not_found_or_wrong_state_error(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        *,
        expected_status: str,
        method: str,
    ) -> ResourceNotFoundError:
        """Disambiguate a status-filtered lookup miss (BE-8003b).

        ``find_blocked_execution_for_job`` / ``find_complete_execution_for_job`` /
        ``find_active_execution_for_job`` return None for TWO different reasons
        that used to collapse into one ambiguous "not found or not in status X"
        message: the job_id does not exist in this tenant at all, or it exists
        but its latest execution is in a different status. TSK-9003: the shared
        builder (also used by job_completion_service / mission_service /
        progress_service) lives in ``_error_helpers`` -- this stays a thin
        wrapper so the four existing call sites here are untouched.
        """
        return await not_found_or_wrong_state_error(
            session,
            tenant_key,
            job_id,
            expected_status=expected_status,
            method=method,
            db_manager=self.db_manager,
            job_repo=self._job_repo,
        )

    async def _broadcast_completion(
        self,
        tenant_key: str,
        job_id: str,
        job: "AgentJob",
        execution: "AgentExecution",
        old_status: str | None,
        duration_seconds: float | None,
    ) -> None:
        """Broadcast job completion status change via WebSocket."""
        try:
            if self._websocket_manager:
                await self._websocket_manager.broadcast_to_tenant(
                    tenant_key=tenant_key,
                    event_type="agent:status_changed",
                    data={
                        "job_id": job_id,
                        "project_id": str(job.project_id) if job.project_id else None,
                        # BE-6229: ride the chain_conductor flag (mirrors REST serializer).
                        "chain_conductor": bool(
                            (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                        ),
                        "agent_display_name": execution.agent_display_name,
                        "agent_name": execution.agent_name,
                        "old_status": old_status,
                        # CE-0032: broadcast the ACTUAL post-mutation status.
                        # Was hardcoded 'complete' which only happened to be
                        # right because _apply_completion_status always set
                        # status='complete' too. CE-0032's staging-end leaves
                        # the orch's exec at 'waiting'; the hardcoded literal
                        # would lie to the frontend and undo the backend
                        # truth, re-introducing the UI Complete-label bug.
                        "status": execution.status,
                        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                        "duration_seconds": execution.duration_seconds,  # BE-5107
                        "working_started_at": execution.working_started_at.isoformat()
                        if execution.working_started_at
                        else None,
                        "has_result": True,
                    },
                )
                self._logger.info(f"[WEBSOCKET] Broadcasted complete_job status change for {job_id}")
        except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
            self._logger.warning(f"[WEBSOCKET] Failed to broadcast complete_job: {ws_error}")

    # BE-6209d: cap for the one-line summary carried by the inbox completion_report
    # pointer. Short summaries (the common case) pass through untouched; only a long
    # or multi-paragraph summary is collapsed — the full text stays in execution.result.
    _COMPLETION_SUMMARY_MAX_LEN: ClassVar[int] = 200

    @staticmethod
    def _one_line_summary(summary: Any, max_len: int = _COMPLETION_SUMMARY_MAX_LEN) -> str:
        """Collapse a (possibly multi-paragraph) result summary to a single short line.

        BE-6209d: the inbox completion_report is a pointer, not the payload, so the
        summary it carries must stay short — first non-empty line, whitespace-collapsed,
        length-capped. The full untruncated summary remains in ``execution.result``
        (``get_agent_result``). Never raises: a missing / non-str / empty summary
        degrades to a stable, non-empty placeholder so the notification is always usable.
        """
        text = str(summary).strip() if summary is not None else ""
        if not text:
            return "Work completed"
        # First non-blank line, with internal whitespace collapsed.
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        collapsed = " ".join(first_line.split())
        if not collapsed:
            return "Work completed"
        if len(collapsed) > max_len:
            collapsed = collapsed[: max_len - 3].rstrip() + "..."
        return collapsed

    async def _handle_completion_side_effects(
        self,
        session: Any,
        job: "AgentJob",
        execution: "AgentExecution",
        result: dict[str, Any],
        tenant_key: str,
        warnings: list[str],
    ) -> None:
        """Handle post-completion side effects: memory warnings and auto-messages.

        Handover 0710: Check if orchestrator needs 360 memory reminder.
        0497b: Auto-generate completion message to orchestrator.
        """
        # Handover 0710: Check if orchestrator needs 360 memory reminder
        if execution.agent_display_name == "orchestrator":
            # Get project to check staging status
            project = await self._job_repo.get_project_by_id(session, tenant_key, str(job.project_id))

            # Only warn for non-staging orchestrators with a product
            skip_staging = project and project.staging_status in ("staging", "staged", "staging_complete")
            has_product = project and project.product_id

            if not skip_staging and has_product:
                # Check if any 360 memory entry exists for this project
                has_memory = await self._job_repo.check_memory_entry_exists(session, tenant_key, str(job.project_id))

                if not has_memory:
                    warnings.append(
                        "REMINDER: No 360 Memory entry found for this project. "
                        "Consider calling write_memory_entry() to preserve project "
                        "knowledge for future orchestrators."
                    )

        # action_required tag resolution removed in INF-5025b

        # 0497b: Auto-generate completion message to orchestrator
        if job.project_id and execution.agent_display_name != "orchestrator":
            orch_exec = await self._job_repo.find_orchestrator_execution(session, tenant_key, str(job.project_id))
            if orch_exec and orch_exec.agent_id != execution.agent_id:
                # BE-6209d: the inbox completion_report is a NOTIFICATION/pointer,
                # not a second copy of the full result body. The canonical store is
                # execution.result (the audit row / dashboard record), fetched in
                # full via get_agent_result(job_id). Previously this carried the
                # whole result["summary"] inline, so an orchestrator that processed
                # BOTH channels paid for the full body twice. Carry a single-line
                # summary + an explicit get_agent_result pointer instead; the full,
                # untruncated summary still lives in execution.result, unchanged.
                one_line = self._one_line_summary(result.get("summary"))
                content = (
                    f"COMPLETION REPORT from {execution.agent_display_name} "
                    f"(job {job.job_id}): {one_line} "
                    f'-- full result via get_agent_result(job_id="{job.job_id}").'
                )
                await self._job_repo.create_auto_completion_message(
                    session=session,
                    tenant_key=tenant_key,
                    project_id=str(job.project_id),
                    from_agent_id=str(execution.agent_id),
                    from_display_name=execution.agent_display_name,
                    content=content,
                    recipient_agent_id=orch_exec.agent_id,
                )
                # Handover 0821: Single batch UPDATE for completion report counters
                # prevents cross-statement deadlock with concurrent broadcasts
                from giljo_mcp.repositories.message_repository import MessageRepository

                _msg_repo = MessageRepository()
                await _msg_repo.batch_update_counters(
                    session=session,
                    tenant_key=tenant_key,
                    sent_increments={execution.agent_id: 1},
                    waiting_increments={orch_exec.agent_id: 1},
                )

    async def reactivation_guidance_for_agent(self, agent_id: str, tenant_key: str | None = None) -> dict | None:
        """Guidance for an auto-blocked Hub reader (BE-9012b, D5, §6 row 10).

        The bus emitted the "how to exit blocked" instruction on its drain-read
        (``receive_mixin._build_reactivation_guidance``). Reactivation now happens on
        project-bound Hub posts (D5), so the same guidance must reach an auto-blocked
        agent when it reads the thread — the ``get_thread_history`` MCP wrapper calls
        this with the reader's ``as_participant`` id. Returns None unless the agent is
        POST-COMPLETION auto-blocked (``status=='blocked'`` with ``completed_at`` set),
        not a mid-work ``set_agent_status(blocked)`` (which resumes via report_progress).
        Tenant-scoped (ADR-009): the lookup is keyed by ``tenant_key``, never per-user.
        """
        tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not tenant_key or not agent_id:
            return None
        async with self._get_session(tenant_key) as session:
            execution = await self._job_repo.get_execution_by_agent_id(session, tenant_key, agent_id)
            if not (execution and execution.status == "blocked" and execution.completed_at is not None):
                return None
            return {
                "your_status": "blocked",
                "your_job_id": str(execution.job_id),
                "instruction": (
                    "You were COMPLETE and a directed, action-required post reactivated you. "
                    "Review the post(s) above, then call "
                    f'resolve_reactivation(job_id="{execution.job_id}", action="resume" to pick the '
                    'work back up | "dismiss" if no action is needed, reason="brief reason").'
                ),
            }

    async def reactivate_job(self, job_id: str, tenant_key: str | None = None, reason: str = "") -> ReactivationResult:
        """
        Resume work on a completed job after receiving a follow-up message.

        Handover 0827c: Only works when the execution is in 'blocked' status
        (auto-set by 0827b when a message arrives for a completed agent).

        Transitions: execution blocked->working, job completed->active.
        Accumulates prior working duration and increments reactivation counter.

        Args:
            job_id: Job UUID
            tenant_key: Optional tenant key (uses current if not provided)
            reason: Why the agent is reactivating

        Returns:
            ReactivationResult with status, reactivation_count, and instruction

        Raises:
            ResourceNotFoundError: Job not found or execution not in blocked status
            ProjectStateError: Project is already closed out
        """
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": "reactivate_job"})
            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": "reactivate_job"})

            async with self._get_session(tenant_key) as session:
                # Find execution in blocked status
                execution = await self._job_repo.find_blocked_execution_for_job(session, tenant_key, job_id)

                if not execution:
                    raise await self._not_found_or_wrong_state_error(
                        session, tenant_key, job_id, expected_status="blocked", method="reactivate_job"
                    )

                # Get job
                job = await self._job_repo.get_agent_job_by_job_id(session, tenant_key, job_id)
                if not job:
                    raise ResourceNotFoundError(
                        message=f"Job {job_id} not found", context={"job_id": job_id, "method": "reactivate_job"}
                    )

                # Check project is not closed out
                if job.project_id:
                    project = await self._job_repo.get_project_by_id(session, tenant_key, str(job.project_id))
                    if project and project.status in IMMUTABLE_PROJECT_STATUSES:
                        raise ProjectStateError(
                            message="Cannot reactivate - project is already closed out.",
                            context={"job_id": job_id, "project_status": project.status},
                        )

                # Accumulate prior working duration
                if execution.completed_at and execution.started_at:
                    elapsed = (execution.completed_at - execution.started_at).total_seconds()
                    current_accumulated = execution.accumulated_duration_seconds or 0.0
                    execution.accumulated_duration_seconds = current_accumulated + elapsed

                # Transition execution: blocked -> working
                old_status = execution.status
                execution.status = "working"
                execution.completed_at = None
                execution.started_at = datetime.now(UTC)
                execution.block_reason = None

                # Increment reactivation counter
                reactivation_count = (execution.reactivation_count or 0) + 1
                execution.reactivation_count = reactivation_count

                # Transition job: completed -> active
                if job.status == "completed":
                    job.status = "active"
                    job.completed_at = None

                await self._job_repo.flush(session)

                project_id = str(job.project_id) if job.project_id else None

                self._logger.info("Job %s reactivated (#%d): %s", job_id, reactivation_count, sanitize(reason))

            # Broadcast status change (outside session)
            try:
                if self._websocket_manager:
                    await self._websocket_manager.broadcast_to_tenant(
                        tenant_key=tenant_key,
                        event_type="agent:status_changed",
                        data={
                            "job_id": job_id,
                            "project_id": project_id,
                            # BE-6229: ride the chain_conductor flag (mirrors REST serializer).
                            "chain_conductor": bool(
                                (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                            ),
                            "agent_display_name": execution.agent_display_name,
                            "agent_name": execution.agent_name,
                            "old_status": old_status,
                            "status": "working",
                            "reactivation_count": reactivation_count,
                            "duration_seconds": execution.duration_seconds,  # BE-5107
                            "working_started_at": execution.working_started_at.isoformat()
                            if execution.working_started_at
                            else None,
                        },
                    )
            except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                self._logger.warning("[WEBSOCKET] Failed to broadcast reactivation: %s", ws_error)

            return ReactivationResult(
                status="reactivated",
                job_id=job_id,
                reactivation_count=reactivation_count,
                instruction=(
                    "You have been reactivated. Follow these steps:\n"
                    "1. Review the message(s) that triggered reactivation.\n"
                    "2. Call report_progress with todo_append to ADD new steps "
                    "(do NOT replace your existing completed steps).\n"
                    "3. Do the work, reporting progress as normal.\n"
                    "4. Call complete_job() when finished."
                ),
            )
        except (ValidationError, ResourceNotFoundError, ProjectStateError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps unexpected errors in OrchestrationError
            self._logger.exception("Failed to reactivate job")
            raise OrchestrationError(
                message="Failed to reactivate job", context={"job_id": job_id, "error": str(e)}
            ) from e

    async def dismiss_reactivation(self, job_id: str, tenant_key: str | None = None, reason: str = "") -> DismissResult:
        """
        Acknowledge a post-completion message without resuming work.

        Handover 0827c: Returns a blocked (auto-blocked from complete) agent
        back to complete status. Used when the message is informational.

        Args:
            job_id: Job UUID
            tenant_key: Optional tenant key (uses current if not provided)
            reason: Why no action is needed

        Returns:
            DismissResult with status and instruction

        Raises:
            ResourceNotFoundError: Job not found or execution not in blocked status
        """
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": "dismiss_reactivation"})
            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": "dismiss_reactivation"})

            async with self._get_session(tenant_key) as session:
                # Find execution in blocked status
                execution = await self._job_repo.find_blocked_execution_for_job(session, tenant_key, job_id)

                if not execution:
                    raise await self._not_found_or_wrong_state_error(
                        session, tenant_key, job_id, expected_status="blocked", method="dismiss_reactivation"
                    )

                # Return to complete (restore previous state)
                old_status = execution.status
                execution.status = "complete"
                execution.block_reason = None

                # Restore job status if it was completed before
                job = await self._job_repo.get_agent_job_by_job_id(session, tenant_key, job_id)

                if job and job.status == "active":
                    # Only restore if no other executions are still active
                    other_active = await self._job_repo.find_other_active_executions(
                        session, tenant_key, job_id, execution.id
                    )
                    if not other_active:
                        job.status = "completed"

                await self._job_repo.flush(session)

                project_id = str(job.project_id) if job and job.project_id else None

                self._logger.info("Job %s reactivation dismissed: %s", job_id, reason)

            # Broadcast status change (outside session)
            try:
                if self._websocket_manager:
                    await self._websocket_manager.broadcast_to_tenant(
                        tenant_key=tenant_key,
                        event_type="agent:status_changed",
                        data={
                            "job_id": job_id,
                            "project_id": project_id,
                            # BE-6229: ride the chain_conductor flag (mirrors REST serializer).
                            "chain_conductor": bool(
                                (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                            )
                            if job
                            else False,
                            "agent_display_name": execution.agent_display_name,
                            "agent_name": execution.agent_name,
                            "old_status": old_status,
                            "status": "complete",
                            "duration_seconds": execution.duration_seconds,  # BE-5107
                            "working_started_at": execution.working_started_at.isoformat()
                            if execution.working_started_at
                            else None,
                        },
                    )
            except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                self._logger.warning("[WEBSOCKET] Failed to broadcast dismiss: %s", ws_error)

            return DismissResult(
                status="dismissed",
                job_id=job_id,
                instruction="Message acknowledged. No action needed. You remain in complete status.",
            )
        except (ValidationError, ResourceNotFoundError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps unexpected errors in OrchestrationError
            self._logger.exception("Failed to dismiss reactivation")
            raise OrchestrationError(
                message="Failed to dismiss reactivation", context={"job_id": job_id, "error": str(e)}
            ) from e

    async def close_job(self, job_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        """
        Mark a completed job as closed (final orchestrator acceptance). Handover 0435b.

        Transition: complete → closed. Only valid from 'complete' status.
        Closed jobs are terminal — they will not be auto-blocked on incoming messages
        and are not expected to receive further work.

        BE-9292b: 'complete' is normally self-reported by the agent, but an agent
        that stalled never reports. The orchestrator is NOT stuck with
        force-decommission in that case: ``complete_job`` accepts any non-terminal
        execution (``TERMINAL_EXECUTION_STATUSES``), so a 'silent' agent whose
        deliverable has been verified can be completed by the orchestrator and then
        closed here — reaching an ACCEPTING terminal state rather than the
        failed/replaced/abandoned label. The wrong-state error raised below names
        that path (see ``_error_helpers._wrong_state_next_action``).

        Args:
            job_id: Job UUID
            tenant_key: Optional tenant key (uses current if not provided)

        Returns:
            Dict with job_id, old_status, new_status

        Raises:
            ValidationError: Invalid input
            ResourceNotFoundError: Job not found or not in 'complete' status
        """
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": "close_job"})
            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": "close_job"})

            project_id = None
            async with self._get_session(tenant_key) as session:
                execution = await self._job_repo.find_complete_execution_for_job(session, tenant_key, job_id)

                if not execution:
                    raise await self._not_found_or_wrong_state_error(
                        session, tenant_key, job_id, expected_status="complete", method="close_job"
                    )

                execution.status = "closed"

                job = await self._job_repo.get_agent_job_by_job_id(session, tenant_key, job_id)
                project_id = str(job.project_id) if job and job.project_id else None

                # BE-9242: a closed job is terminal -- "not expected to receive
                # further work" per this method's own contract above. Any live
                # (unacked) message cursor it still holds would otherwise linger
                # forever (nobody can reactivate a closed agent to drain it).
                # Genuinely action-required posts are forwarded to the live
                # orchestrator, never silently dropped; see
                # agent_terminal_cursor_service for the two-sided contract.
                if project_id:
                    await resolve_terminal_agent_cursors(
                        session,
                        tenant_key=tenant_key,
                        project_id=project_id,
                        agent_id=execution.agent_id,
                        agent_label=execution.agent_display_name or execution.agent_name or execution.agent_id,
                        terminal_status="closed",
                    )

                await self._job_repo.flush(session)
                self._logger.info("Job %s closed (final acceptance)", job_id)

            if self._websocket_manager:
                try:
                    await self._websocket_manager.broadcast_to_tenant(
                        tenant_key=tenant_key,
                        event_type="agent:status_changed",
                        data={
                            "job_id": job_id,
                            "project_id": project_id,
                            # BE-6229: ride the chain_conductor flag (mirrors REST serializer).
                            "chain_conductor": bool(
                                (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                            )
                            if job
                            else False,
                            "agent_display_name": execution.agent_display_name,
                            "agent_name": execution.agent_name,
                            "old_status": "complete",
                            "status": "closed",
                            "duration_seconds": execution.duration_seconds,  # BE-5107
                            "working_started_at": execution.working_started_at.isoformat()
                            if execution.working_started_at
                            else None,
                        },
                    )
                except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience
                    self._logger.warning("[WEBSOCKET] Failed to broadcast close: %s", ws_error)

            return {
                "job_id": job_id,
                "old_status": "complete",
                "new_status": "closed",
                "message": "Job closed — final acceptance by orchestrator.",
            }
        except (ValidationError, ResourceNotFoundError):
            raise
        except Exception as e:  # Broad catch: service boundary
            self._logger.exception("Failed to close job")
            raise OrchestrationError(message="Failed to close job", context={"job_id": job_id, "error": str(e)}) from e

    async def set_agent_status(
        self,
        job_id: str,
        status: str,
        reason: str = "",
        wake_in_minutes: int | None = None,
        tenant_key: str | None = None,
    ) -> ErrorReportResult:
        """
        Set agent resting or blocked status (Handover 0880: expanded from report_error).

        Handles three agent-settable states:
        - blocked: agent needs human help (shows "Needs Input")
        - idle: agent dispatched work, resting (shows "Monitoring")
        - sleeping: agent will auto-check in N minutes (shows "Sleeping")

        Auto-wake: report_progress() transitions idle/sleeping/blocked → working.

        Args:
            job_id: Job UUID (looks up latest active execution)
            status: Target status — "blocked", "idle", or "sleeping"
            reason: Human-readable reason (displayed in dashboard)
            wake_in_minutes: Sleep interval hint for "sleeping" status
            tenant_key: Optional tenant key (uses current if not provided)

        Returns:
            ErrorReportResult with status and block_reason

        """
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": "set_agent_status"})

            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": "set_agent_status"})

            if status not in self._AGENT_SETTABLE_STATUSES:
                raise ValidationError(
                    message=f"Invalid status: {status}. Must be one of {sorted(self._AGENT_SETTABLE_STATUSES)}",
                    context={"method": "set_agent_status", "job_id": job_id},
                )

            # For blocked status, reason is required (backward compat with report_error)
            if status == "blocked" and not reason.strip():
                raise ValidationError(
                    message="reason is required for blocked status",
                    context={"method": "set_agent_status", "job_id": job_id},
                )

            # Build block_reason string (stores reason + optional wake metadata)
            block_reason = reason
            if status == "sleeping" and wake_in_minutes:
                block_reason = (
                    f"{reason} | wake_in_minutes={wake_in_minutes}" if reason else f"wake_in_minutes={wake_in_minutes}"
                )

            job = None
            async with self._get_session(tenant_key) as session:
                execution = await self._job_repo.find_active_execution_for_job(session, tenant_key, job_id)

                if not execution:
                    raise await self._not_found_or_wrong_state_error(
                        session,
                        tenant_key,
                        job_id,
                        expected_status="in-progress (not complete/closed/decommissioned)",
                        method="set_agent_status",
                    )

                # TENANT ISOLATION: Filter by tenant_key
                job = await self._job_repo.get_agent_job_by_job_id(session, tenant_key, job_id)

                # Staging-phase status lock: orchestrator may not flip its own
                # status while project.staging_status != 'staging_complete'.
                # report_progress is the only allowed signal in that window;
                # spawned non-orchestrator agents bypass the lock entirely.
                if execution.agent_display_name == "orchestrator" and job and job.project_id:
                    project = await self._job_repo.get_project_by_id(session, tenant_key, str(job.project_id))
                    if project is not None and project.staging_status != "staging_complete":
                        raise AuthorizationError(
                            message=(
                                "Status changes are server-locked during staging. "
                                "Ask the user inline; the dashboard agent grid is empty "
                                "during staging anyway."
                            ),
                            error_code="STAGING_LOCK",
                            context={
                                "code": "STAGING_LOCK",
                                "job_id": job_id,
                                "agent_display_name": execution.agent_display_name,
                                "staging_status": project.staging_status,
                            },
                        )

                old_status = execution.status
                execution.status = status
                execution.block_reason = block_reason if block_reason else None

                # BE-3006b: flush inside the session scope; the get_session_async
                # owner commits on block exit, BEFORE the broadcast below (which
                # runs outside the scope) — events emit only after commit.
                await self._job_repo.flush(session)

            # WebSocket broadcast for real-time UI updates
            try:
                if self._websocket_manager:
                    ws_data = {
                        "job_id": job_id,
                        "project_id": str(job.project_id) if job and job.project_id else None,
                        # BE-6229: ride the chain_conductor flag (mirrors REST serializer).
                        "chain_conductor": bool(
                            (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                        )
                        if job
                        else False,
                        "agent_display_name": execution.agent_display_name,
                        "agent_name": execution.agent_name,
                        "old_status": old_status,
                        "status": status,
                        "block_reason": block_reason,
                        "duration_seconds": execution.duration_seconds,  # BE-5107
                        "working_started_at": execution.working_started_at.isoformat()
                        if execution.working_started_at
                        else None,
                    }
                    await self._websocket_manager.broadcast_to_tenant(
                        tenant_key=tenant_key,
                        event_type="agent:status_changed",
                        data=ws_data,
                    )
                    self._logger.info(f"[WEBSOCKET] Broadcasted set_agent_status ({status}) for {job_id}")
            except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                self._logger.warning(f"[WEBSOCKET] Failed to broadcast set_agent_status: {ws_error}")

            status_labels = {"blocked": "Needs Input", "idle": "Monitoring", "sleeping": "Sleeping"}
            return ErrorReportResult(
                job_id=job_id,
                message=f"Status set to {status_labels.get(status, status)}",
                status=status,
                block_reason=block_reason or reason,
            )
        except (ValidationError, ResourceNotFoundError, AuthorizationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to set agent status")
            raise OrchestrationError(
                message="Failed to set agent status", context={"job_id": job_id, "error": str(e)}
            ) from e
