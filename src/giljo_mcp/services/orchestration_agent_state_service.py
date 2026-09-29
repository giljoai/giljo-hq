# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
from giljo_mcp.services._error_helpers import M_CLOSE, M_DISMISS, M_REACTIVATE, not_found_or_wrong_state_error
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.agent_terminal_cursor_service import resolve_terminal_agent_cursors
from giljo_mcp.services.orchestrator_caller_guard import require_project_orchestrator
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


class OrchestrationAgentStateService:

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
        return await not_found_or_wrong_state_error(
            session,
            tenant_key,
            job_id,
            expected_status=expected_status,
            method=method,
            db_manager=self.db_manager,
            job_repo=self._job_repo,
        )

    async def _resolve_product_id(self, session: AsyncSession, tenant_key: str, job: "AgentJob | None") -> str | None:
        if not job or not job.project_id:
            return None
        project = await self._job_repo.get_project_by_id(session, tenant_key, str(job.project_id))
        return project.product_id if project else None

    async def _broadcast_completion(
        self,
        tenant_key: str,
        job_id: str,
        job: "AgentJob",
        execution: "AgentExecution",
        old_status: str | None,
        duration_seconds: float | None,
        product_id: str | None = None,
    ) -> None:
        try:
            if self._websocket_manager:
                await self._websocket_manager.broadcast_to_tenant(
                    tenant_key=tenant_key,
                    event_type="agent:status_changed",
                    data={
                        "job_id": job_id,
                        "project_id": str(job.project_id) if job.project_id else None,
                        "product_id": product_id,
                        "chain_conductor": bool(
                            (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                        ),
                        "agent_display_name": execution.agent_display_name,
                        "agent_name": execution.agent_name,
                        "old_status": old_status,
                        "status": execution.status,
                        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                        "duration_seconds": execution.duration_seconds,
                        "working_started_at": execution.working_started_at.isoformat()
                        if execution.working_started_at
                        else None,
                        "has_result": True,
                    },
                )
                self._logger.info(f"[WEBSOCKET] Broadcasted complete_job status change for {job_id}")
        except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
            self._logger.warning(f"[WEBSOCKET] Failed to broadcast complete_job: {ws_error}")

    _COMPLETION_SUMMARY_MAX_LEN: ClassVar[int] = 200

    @staticmethod
    def _one_line_summary(summary: Any, max_len: int = _COMPLETION_SUMMARY_MAX_LEN) -> str:
        text = str(summary).strip() if summary is not None else ""
        if not text:
            return "Work completed"
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
        if execution.agent_display_name == "orchestrator":
            project = await self._job_repo.get_project_by_id(session, tenant_key, str(job.project_id))

            skip_staging = project and project.staging_status in ("staging", "staged", "staging_complete")
            has_product = project and project.product_id

            if not skip_staging and has_product:
                has_memory = await self._job_repo.check_memory_entry_exists(session, tenant_key, str(job.project_id))

                if not has_memory:
                    warnings.append(
                        "REMINDER: No 360 Memory entry found for this project. "
                        "Consider calling write_memory_entry() to preserve project "
                        "knowledge for future orchestrators."
                    )


        if job.project_id and execution.agent_display_name != "orchestrator":
            orch_exec = await self._job_repo.find_orchestrator_execution(session, tenant_key, str(job.project_id))
            if orch_exec and orch_exec.agent_id != execution.agent_id:
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
                from giljo_mcp.repositories.message_repository import MessageRepository

                _msg_repo = MessageRepository()
                await _msg_repo.batch_update_counters(
                    session=session,
                    tenant_key=tenant_key,
                    sent_increments={execution.agent_id: 1},
                    waiting_increments={orch_exec.agent_id: 1},
                )

    async def reactivation_guidance_for_agent(self, agent_id: str, tenant_key: str | None = None) -> dict | None:
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
                    f'resume_or_dismiss_job(job_id="{execution.job_id}", action="resume" to pick the '
                    'work back up | "dismiss" if no action is needed, reason="brief reason").'
                ),
            }

    async def reactivate_job(self, job_id: str, tenant_key: str | None = None, reason: str = "") -> ReactivationResult:
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": M_REACTIVATE})
            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": M_REACTIVATE})

            async with self._get_session(tenant_key) as session:
                execution = await self._job_repo.find_blocked_execution_for_job(session, tenant_key, job_id)

                if not execution:
                    raise await self._not_found_or_wrong_state_error(
                        session, tenant_key, job_id, expected_status="blocked", method=M_REACTIVATE
                    )

                job = await self._job_repo.get_agent_job_by_job_id(session, tenant_key, job_id)
                if not job:
                    raise ResourceNotFoundError(
                        message=f"Job {job_id} not found", context={"job_id": job_id, "method": M_REACTIVATE}
                    )

                product_id: str | None = None
                if job.project_id:
                    project = await self._job_repo.get_project_by_id(session, tenant_key, str(job.project_id))
                    if project and project.status in IMMUTABLE_PROJECT_STATUSES:
                        raise ProjectStateError(
                            message="Cannot reactivate - project is already closed out.",
                            context={"job_id": job_id, "project_status": project.status},
                        )
                    product_id = project.product_id if project else None

                if execution.completed_at and execution.started_at:
                    elapsed = (execution.completed_at - execution.started_at).total_seconds()
                    current_accumulated = execution.accumulated_duration_seconds or 0.0
                    execution.accumulated_duration_seconds = current_accumulated + elapsed

                old_status = execution.status
                execution.status = "working"
                execution.completed_at = None
                execution.started_at = datetime.now(UTC)
                execution.block_reason = None

                reactivation_count = (execution.reactivation_count or 0) + 1
                execution.reactivation_count = reactivation_count

                if job.status == "completed":
                    job.status = "active"
                    job.completed_at = None

                await self._job_repo.flush(session)

                project_id = str(job.project_id) if job.project_id else None

                self._logger.info("Job %s reactivated (#%d): %s", job_id, reactivation_count, sanitize(reason))

            try:
                if self._websocket_manager:
                    await self._websocket_manager.broadcast_to_tenant(
                        tenant_key=tenant_key,
                        event_type="agent:status_changed",
                        data={
                            "job_id": job_id,
                            "project_id": project_id,
                            "product_id": product_id,
                            "chain_conductor": bool(
                                (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                            ),
                            "agent_display_name": execution.agent_display_name,
                            "agent_name": execution.agent_name,
                            "old_status": old_status,
                            "status": "working",
                            "reactivation_count": reactivation_count,
                            "duration_seconds": execution.duration_seconds,
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
        except Exception as e:
            self._logger.exception("Failed to reactivate job")
            raise OrchestrationError(
                message="Failed to reactivate job", context={"job_id": job_id, "error": str(e)}
            ) from e

    async def dismiss_reactivation(self, job_id: str, tenant_key: str | None = None, reason: str = "") -> DismissResult:
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": M_DISMISS})
            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": M_DISMISS})

            async with self._get_session(tenant_key) as session:
                execution = await self._job_repo.find_blocked_execution_for_job(session, tenant_key, job_id)

                if not execution:
                    raise await self._not_found_or_wrong_state_error(
                        session, tenant_key, job_id, expected_status="blocked", method=M_DISMISS
                    )

                old_status = execution.status
                execution.status = "complete"
                execution.block_reason = None

                job = await self._job_repo.get_agent_job_by_job_id(session, tenant_key, job_id)

                if job and job.status == "active":
                    other_active = await self._job_repo.find_other_active_executions(
                        session, tenant_key, job_id, execution.id
                    )
                    if not other_active:
                        job.status = "completed"

                await self._job_repo.flush(session)

                project_id = str(job.project_id) if job and job.project_id else None
                product_id = await self._resolve_product_id(session, tenant_key, job)

                self._logger.info("Job %s reactivation dismissed: %s", job_id, reason)

            try:
                if self._websocket_manager:
                    await self._websocket_manager.broadcast_to_tenant(
                        tenant_key=tenant_key,
                        event_type="agent:status_changed",
                        data={
                            "job_id": job_id,
                            "project_id": project_id,
                            "product_id": product_id,
                            "chain_conductor": bool(
                                (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                            )
                            if job
                            else False,
                            "agent_display_name": execution.agent_display_name,
                            "agent_name": execution.agent_name,
                            "old_status": old_status,
                            "status": "complete",
                            "duration_seconds": execution.duration_seconds,
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
        except Exception as e:
            self._logger.exception("Failed to dismiss reactivation")
            raise OrchestrationError(
                message="Failed to dismiss reactivation", context={"job_id": job_id, "error": str(e)}
            ) from e

    async def close_job(
        self, job_id: str, tenant_key: str | None = None, caller_job_id: str | None = None
    ) -> dict[str, Any]:
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": M_CLOSE})
            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": M_CLOSE})

            project_id = None
            product_id = None
            async with self._get_session(tenant_key) as session:
                execution = await self._job_repo.find_complete_execution_for_job(session, tenant_key, job_id)

                if not execution:
                    raise await self._not_found_or_wrong_state_error(
                        session, tenant_key, job_id, expected_status="complete", method=M_CLOSE
                    )

                job = await self._job_repo.get_agent_job_by_job_id(session, tenant_key, job_id)
                await require_project_orchestrator(session, self._job_repo, tenant_key, job, caller_job_id)
                execution.status = "closed"
                project_id = str(job.project_id) if job and job.project_id else None
                product_id = await self._resolve_product_id(session, tenant_key, job)

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
                            "product_id": product_id,
                            "chain_conductor": bool(
                                (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                            )
                            if job
                            else False,
                            "agent_display_name": execution.agent_display_name,
                            "agent_name": execution.agent_name,
                            "old_status": "complete",
                            "status": "closed",
                            "duration_seconds": execution.duration_seconds,
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
        except Exception as e:
            self._logger.exception("Failed to close job")
            raise OrchestrationError(message="Failed to close job", context={"job_id": job_id, "error": str(e)}) from e

    async def set_agent_status(
        self,
        job_id: str,
        status: str,
        reason: str = "",
        wake_in_minutes: int | None = None,
        tenant_key: str | None = None,
        wake_on_signal: bool = False,
    ) -> ErrorReportResult:
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

            if status == "blocked" and not reason.strip():
                raise ValidationError(
                    message="reason is required for blocked status",
                    context={"method": "set_agent_status", "job_id": job_id},
                )

            block_reason = reason
            if status == "sleeping" and wake_on_signal:
                block_reason = f"{reason} | wake_mode=signal" if reason else "wake_mode=signal"
            elif status == "sleeping" and wake_in_minutes:
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

                job = await self._job_repo.get_agent_job_by_job_id(session, tenant_key, job_id)

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

                await self._job_repo.flush(session)
                product_id = await self._resolve_product_id(session, tenant_key, job)

            try:
                if self._websocket_manager:
                    ws_data = {
                        "job_id": job_id,
                        "project_id": str(job.project_id) if job and job.project_id else None,
                        "product_id": product_id,
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
                        "duration_seconds": execution.duration_seconds,
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
        except Exception as e:
            self._logger.exception("Failed to set agent status")
            raise OrchestrationError(
                message="Failed to set agent status", context={"job_id": job_id, "error": str(e)}
            ) from e
