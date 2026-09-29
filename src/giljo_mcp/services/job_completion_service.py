# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.domain.todo_kinds import (
    TODO_KIND_CHAIN_DRIVE,
    TODO_KIND_CLOSEOUT_INTENT,
    TODO_KIND_SELF_CLOSEOUT,
    classify_todo_kind,
)
from giljo_mcp.exceptions import OrchestrationError, ResourceNotFoundError, ValidationError
from giljo_mcp.models import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.schemas.jsonb_validators import validate_agent_execution_result
from giljo_mcp.schemas.responses.orchestration import SOLO_STAGING_END_NEXT_ACTION_WHY
from giljo_mcp.schemas.service_responses import CompleteJobResult, StagingDirective, build_next_action
from giljo_mcp.services._error_helpers import not_found_or_wrong_state_error
from giljo_mcp.services.job_completion_closeout_gate import (
    build_closeout_checklist,
    build_completion_blocked_error,
    enforce_closeout_approval_mode,
)
from giljo_mcp.services.job_completion_staging import (  # noqa: F401 — constant re-exports keep test imports stable
    _CHAIN_SUBORCH_STAGING_END_ACTION,
    _CHAIN_SUBORCH_STAGING_END_NEXT_ACTION,
    _CHAIN_SUBORCH_STAGING_END_NEXT_STEP,
    _CONDUCTOR_STAGING_END_ACTION,
    _CONDUCTOR_STAGING_END_NEXT_ACTION,
    _CONDUCTOR_STAGING_END_NEXT_STEP,
    finalize_conductor_chain,
    guard_conductor_chain_incomplete,
    handle_staging_end,
    is_staging_end_orchestrator_call,
    is_staging_phase_orchestrator,
    staging_directive_for,
)
from giljo_mcp.services.orchestrator_caller_guard import warn_if_never_started
from giljo_mcp.services.protocol_survival import build_complete_job_footer
from giljo_mcp.services.sequence_run_service import active_chain_run, broadcast_deferred_sequence_updates
from giljo_mcp.tenant import TenantManager


if TYPE_CHECKING:
    from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService

logger = logging.getLogger(__name__)





class JobCompletionService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        test_session: AsyncSession | None = None,
        websocket_manager: Any | None = None,
        agent_state_service: Optional["OrchestrationAgentStateService"] = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._agent_state = agent_state_service
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        if self._test_session is not None:

            @asynccontextmanager
            async def _test_session_wrapper():
                if tenant_key:
                    with tenant_session_context(self._test_session, tenant_key):
                        yield self._test_session
                else:
                    yield self._test_session

            return _test_session_wrapper()
        if tenant_key:

            @asynccontextmanager
            async def _tenant_session_wrapper():
                async with self.db_manager.get_session_async(tenant_key=tenant_key) as session:
                    with tenant_session_context(session, tenant_key):
                        yield session

            return _tenant_session_wrapper()
        return self.db_manager.get_session_async()

    async def complete_job(
        self,
        job_id: str,
        result: dict[str, Any],
        tenant_key: str | None = None,
        acknowledge_closeout_todo: bool = False,
        acknowledge_messages_on_complete: bool = False,
    ) -> CompleteJobResult:
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": "complete_job"})

            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": "complete_job"})
            if not result or not isinstance(result, dict):
                raise ValidationError(
                    message="result must be a non-empty dict",
                    context={"method": "complete_job", "result_type": type(result).__name__},
                )

            try:
                result = validate_agent_execution_result(result)
            except PydanticValidationError as exc:
                raise ValidationError(
                    message="complete_job result has an invalid shape (summary/artifacts/commits)",
                    context={"method": "complete_job", "errors": exc.errors(include_url=False)},
                ) from exc

            completion_attempt_time = datetime.now(UTC)

            job = None
            execution = None
            old_status = None
            duration_seconds = None
            warnings: list[str] = []
            staging_directive: StagingDirective | None = None
            is_staging_end: bool = False
            is_chain_member_suborch: bool = False
            closeout_mode: str = "hitl"
            repo = AgentCompletionRepository()
            async with self._get_session(tenant_key) as session:
                execution = await repo.find_active_execution_for_completion(session, tenant_key, job_id)

                if execution:
                    job = await self._fetch_job_for_completion(session, job_id, tenant_key)

                    is_staging_end, staging_end_project = await self._is_staging_end_orchestrator_call(
                        session, job, execution, tenant_key
                    )

                    if not is_staging_end:
                        await self._guard_conductor_chain_incomplete(session, job, execution, tenant_key, job_id)

                    is_closeout_phase = job.job_type == "orchestrator" and not is_staging_end

                    is_chain_member_suborch = bool(
                        is_staging_end
                        and getattr(job, "project_id", None) is not None
                        and await active_chain_run(session, job.project_id, tenant_key) is not None
                    )

                    await self._validate_completion_requirements(
                        session,
                        job,
                        execution,
                        tenant_key,
                        job_id,
                        completion_attempt_time,
                        project=staging_end_project,
                        is_closeout_phase=is_closeout_phase,
                    )

                    closeout_mode = await enforce_closeout_approval_mode(
                        self,
                        session=session,
                        job=job,
                        execution=execution,
                        tenant_key=tenant_key,
                        result=result,
                        is_closeout_phase=is_closeout_phase,
                    )

                    warn_if_never_started(job, execution, warnings)
                    old_status, duration_seconds = self._apply_completion_status(
                        execution, result, is_staging_end=is_staging_end
                    )

                    await self._finalize_job_if_last_execution(
                        session, job, execution, tenant_key, job_id, is_staging_end=is_staging_end
                    )

                    await self._handle_completion_side_effects(
                        session=session,
                        job=job,
                        execution=execution,
                        result=result,
                        tenant_key=tenant_key,
                        warnings=warnings,
                    )

                    is_conductor = await self._finalize_conductor_chain(
                        session, job, execution, tenant_key, is_staging_end=is_staging_end
                    )

                    staging_directive = await self._handle_staging_end(
                        session,
                        job,
                        execution,
                        tenant_key,
                        is_staging_end=is_staging_end,
                        project=staging_end_project,
                        is_chain_member_suborch=is_chain_member_suborch,
                        is_conductor=is_conductor,
                    )

                    await session.flush()
                    product_id_for_broadcast = (
                        await self._agent_state._resolve_product_id(session, tenant_key, job)
                        if self._agent_state
                        else None
                    )
                else:
                    await self._raise_for_missing_execution(session, job_id, tenant_key)

            await broadcast_deferred_sequence_updates(session)
            if execution:
                await self._broadcast_completion(
                    tenant_key, job_id, job, execution, old_status, duration_seconds, product_id_for_broadcast
                )

            closeout_checklist = None
            is_impl_phase_orch = job and getattr(job, "job_type", "") == "orchestrator" and not is_staging_end
            if is_impl_phase_orch:
                try:
                    closeout_checklist = build_closeout_checklist(closeout_mode)
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to build closeout checklist during job completion", exc_info=True)
                    closeout_checklist = None

            phase, phase_message, next_action = self._phase_response(
                is_staging_end=is_staging_end,
                is_closeout_phase=is_impl_phase_orch,
                is_conductor=is_conductor,
                is_chain_member_suborch=is_chain_member_suborch,
            )
            footer = build_complete_job_footer(
                phase=phase, is_conductor=is_conductor, is_chain_member_suborch=is_chain_member_suborch
            )

            return CompleteJobResult(
                status="success",
                job_id=job_id,
                message=phase_message,
                warnings=warnings,
                result_stored=True,
                phase=phase,
                next_action=next_action,
                closeout_checklist=closeout_checklist,
                staging_directive=staging_directive,
                lifecycle_footer=footer,
            )
        except (ValidationError, ResourceNotFoundError):
            raise
        except Exception as e:
            self._logger.exception("Failed to complete job")
            raise OrchestrationError(
                message="Failed to complete job", context={"job_id": job_id, "error": str(e)}
            ) from e

    async def _guard_conductor_chain_incomplete(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        tenant_key: str,
        job_id: str,
    ) -> None:
        await guard_conductor_chain_incomplete(
            session,
            job,
            execution,
            tenant_key,
            job_id,
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
        )

    async def _fetch_job_for_completion(self, session: AsyncSession, job_id: str, tenant_key: str) -> AgentJob:
        repo = AgentCompletionRepository()
        job = await repo.get_agent_job_by_job_id(session, tenant_key, job_id)
        if not job:
            raise ResourceNotFoundError(
                message=f"Job {job_id} not found", context={"job_id": job_id, "method": "complete_job"}
            )
        return job

    async def _validate_completion_requirements(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        tenant_key: str,
        job_id: str,
        completion_attempt_time: datetime,
        project: Project | None = None,
        is_closeout_phase: bool = False,
    ) -> None:
        if execution.status == "awaiting_user":
            pending_stmt = select(UserApproval).where(
                UserApproval.tenant_key == tenant_key,
                UserApproval.agent_execution_id == execution.id,
                UserApproval.status == "pending",
            )
            pending_approval = (await session.execute(pending_stmt)).scalar_one_or_none()
            approval_id = pending_approval.id if pending_approval is not None else None
            raise ValidationError(
                message=(
                    "COMPLETION_BLOCKED: Agent is awaiting user approval. "
                    "Resolve via POST /api/approvals/{id}/decide before calling complete_job()."
                ),
                error_code="AWAITING_USER_APPROVAL",
                context={
                    "job_id": job_id,
                    "approval_id": approval_id,
                    "agent_status": "awaiting_user",
                    "reasons": [
                        "Agent has a pending user_approval; user must decide before completion is allowed.",
                    ],
                },
            )

        repo = AgentCompletionRepository()
        all_unread = await repo.get_unread_messages_for_agent(session, tenant_key, job.project_id, execution.agent_id)

        unread_messages = [m for m in all_unread if self._is_before_attempt(m, completion_attempt_time)]

        is_conductor_job = getattr(job, "project_id", None) is None and bool(
            (getattr(job, "job_metadata", None) or {}).get("chain_conductor")
        )
        self_identities = {execution.agent_id}
        if is_conductor_job:
            conductor_label = getattr(execution, "agent_name", None)
            if conductor_label:
                self_identities.add(conductor_label)
        unread_messages = [m for m in unread_messages if m.from_agent_id not in self_identities]


        incomplete_todos = await repo.get_incomplete_todos(session, tenant_key, job_id)

        is_staging_orchestrator = is_staging_phase_orchestrator(job, project)
        if is_staging_orchestrator and incomplete_todos:
            self._logger.info(
                "[STAGING] Bypassing incomplete-TODOs gate for staging-phase orchestrator "
                "(%d deliverable TODOs survive into implementation)",
                len(incomplete_todos),
                extra={"job_id": job_id, "tenant_key": tenant_key},
            )
            incomplete_todos = []

        if is_closeout_phase and incomplete_todos:

            def _is_self_closeout_todo(todo) -> bool:
                kind = todo.todo_kind if todo.todo_kind is not None else classify_todo_kind(todo.content or "")
                if kind == TODO_KIND_SELF_CLOSEOUT:
                    return True
                if kind == TODO_KIND_CLOSEOUT_INTENT:
                    return is_closeout_phase
                if kind == TODO_KIND_CHAIN_DRIVE:
                    return is_conductor_job
                return False

            closeout_todos = [t for t in incomplete_todos if _is_self_closeout_todo(t)]
            remainder = [t for t in incomplete_todos if t not in closeout_todos]
            if closeout_todos:
                now = datetime.now(UTC)
                for todo in closeout_todos:
                    todo.status = "completed"
                    todo.updated_at = now
                await session.flush()
                self._logger.info(
                    "Auto-completed %d closeout TODO(s) on acknowledged complete_job for job %s",
                    len(closeout_todos),
                    job_id,
                )
            incomplete_todos = remainder

        if unread_messages or incomplete_todos:
            self._logger.info(
                "Completion blocked by protocol validation",
                extra={
                    "job_id": job_id,
                    "tenant_key": tenant_key,
                    "unread_messages": len(unread_messages),
                    "incomplete_todos": len(incomplete_todos),
                },
            )
            raise build_completion_blocked_error(
                job_id=job_id,
                unread_messages=unread_messages,
                incomplete_todos=incomplete_todos,
            )

    def _is_before_attempt(self, message, completion_attempt_time: datetime) -> bool:
        if not message.created_at:
            return True
        created_at = message.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return created_at <= completion_attempt_time

    def _apply_completion_status(
        self,
        execution: AgentExecution,
        result: dict[str, Any],
        *,
        is_staging_end: bool = False,
    ) -> tuple[str | None, float | None]:
        old_status = execution.status

        if is_staging_end:
            execution.status = "waiting"
            execution.result = result
            execution.completed_at = None
            return old_status, None

        execution.status = "complete"
        execution.completed_at = datetime.now(UTC)
        execution.progress = 100
        execution.result = result

        duration_seconds = None
        if execution.started_at and execution.completed_at:
            duration_seconds = (execution.completed_at - execution.started_at).total_seconds()
        return old_status, duration_seconds

    async def _finalize_job_if_last_execution(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        tenant_key: str,
        job_id: str,
        *,
        is_staging_end: bool = False,
    ) -> None:
        if is_staging_end:
            return

        repo = AgentCompletionRepository()
        other_active = await repo.find_other_active_executions_by_agent_id(
            session, tenant_key, job_id, execution.agent_id
        )

        if not other_active:
            job.status = "completed"
            job.completed_at = execution.completed_at

    async def _finalize_conductor_chain(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        tenant_key: str,
        *,
        is_staging_end: bool,
    ) -> bool:
        return await finalize_conductor_chain(
            session,
            job,
            execution,
            tenant_key,
            is_staging_end=is_staging_end,
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            websocket_manager=self._websocket_manager,
        )

    async def _raise_for_missing_execution(self, session: AsyncSession, job_id: str, tenant_key: str) -> None:
        repo = AgentCompletionRepository()
        decommissioned_exec = await repo.find_decommissioned_execution(session, tenant_key, job_id)

        if decommissioned_exec:
            raise ResourceNotFoundError(
                message=(
                    f"Job {job_id} was decommissioned and cannot transition to 'completed'. "
                    f"This typically happens when write_project_closeout(force=true) "
                    f"was called before complete_job()."
                ),
                context={
                    "job_id": job_id,
                    "method": "complete_job",
                    "execution_status": "decommissioned",
                    "cause": "Project was force-closed before this job called complete_job()",
                },
            )

        raise await not_found_or_wrong_state_error(
            session, tenant_key, job_id, expected_status="active", method="complete_job", db_manager=self.db_manager
        )

    async def _broadcast_completion(
        self, tenant_key, job_id, job, execution, old_status, duration_seconds, product_id=None
    ):
        if self._agent_state:
            await self._agent_state._broadcast_completion(
                tenant_key, job_id, job, execution, old_status, duration_seconds, product_id
            )

    async def _handle_completion_side_effects(self, session, job, execution, result, tenant_key, warnings):
        if self._agent_state:
            await self._agent_state._handle_completion_side_effects(
                session, job, execution, result, tenant_key, warnings
            )

    async def _is_staging_end_orchestrator_call(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        tenant_key: str,
    ) -> tuple[bool, Project | None]:
        return await is_staging_end_orchestrator_call(
            session,
            job,
            execution,
            tenant_key,
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
        )

    async def _handle_staging_end(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        tenant_key: str,
        *,
        is_staging_end: bool,
        project: Project | None,
        is_chain_member_suborch: bool = False,
        is_conductor: bool = False,
    ) -> StagingDirective | None:
        return await handle_staging_end(
            session,
            job,
            execution,
            tenant_key,
            is_staging_end=is_staging_end,
            project=project,
            is_chain_member_suborch=is_chain_member_suborch,
            is_conductor=is_conductor,
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            websocket_manager=self._websocket_manager,
        )

    @staticmethod
    def _staging_directive_for(is_chain_member_suborch: bool, is_conductor: bool = False) -> StagingDirective:
        return staging_directive_for(is_chain_member_suborch, is_conductor=is_conductor)

    @staticmethod
    def _phase_response(
        *,
        is_staging_end: bool,
        is_closeout_phase: bool,
        is_conductor: bool = False,
        is_chain_member_suborch: bool = False,
    ) -> tuple[str, str, dict[str, Any] | None]:
        if is_staging_end:
            if is_chain_member_suborch:
                return (
                    "staging_end",
                    "Staging marked complete.",
                    build_next_action(tool="get_job_mission", why=_CHAIN_SUBORCH_STAGING_END_NEXT_ACTION),
                )
            if is_conductor:
                return (
                    "staging_end",
                    "Chain staging marked complete.",
                    build_next_action(why=_CONDUCTOR_STAGING_END_NEXT_ACTION),
                )
            return (
                "staging_end",
                "Staging marked complete.",
                build_next_action(
                    tool="launch_implementation",
                    why=f"{SOLO_STAGING_END_NEXT_ACTION_WHY} Do NOT write the project closeout from the staging session.",
                ),
            )
        if is_closeout_phase:
            if is_conductor:
                return (
                    "closeout",
                    "Chain conductor job completed.",
                    build_next_action(
                        tool="write_memory_entry",
                        why="Chain complete: no project to close. Ensure the series summary is written, then you are done.",
                    ),
                )
            return (
                "closeout",
                "Orchestrator job completed; closeout recorded.",
                build_next_action(
                    tool="write_project_closeout",
                    why=(
                        "Call write_project_closeout() to write the project closeout (orchestrators "
                        "coordinate, they do not commit code)."
                    ),
                ),
            )
        return (
            "deliverable",
            "Deliverable recorded.",
            build_next_action(why="No further action — the orchestrator reviews your result and closes your job."),
        )

