# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
JobCompletionService - Agent job completion orchestration.

Sprint 002e: Extracted from OrchestrationService to reduce god-class size.
Contains complete_job and its 8 helper methods (~330 lines).
"""

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
    staging_directive_for,
)
from giljo_mcp.services.protocol_survival import build_complete_job_footer
from giljo_mcp.tenant import TenantManager


if TYPE_CHECKING:
    from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService

logger = logging.getLogger(__name__)


# BE-9012b (D7): the three closeout/chain-drive TODO regexes moved to
# ``giljo_mcp.domain.todo_kinds`` and now run ONCE at the write boundary
# (``progress_service`` stamps ``agent_todo_items.todo_kind``). The completion gate
# below reads that durable marker instead of re-matching wording at complete_job
# time (§6 rows 4-6), falling back to ``classify_todo_kind`` only for legacy rows
# written before the column existed (NULL-tolerant read, Data-facing DoD answer (a)).

# BE-9060 item 2: the staging-end machinery (detection, flag-flip + directive
# shaping, C1 conductor guard, and the directive prose constants) was extracted
# VERBATIM to ``job_completion_staging``. The constants are re-exported from the
# import block above so existing importers (tests) keep working; the class keeps
# thin delegating methods so its call sites and test seams are untouched.


class JobCompletionService:
    """Service for agent job completion orchestration.

    Extracted from OrchestrationService (Sprint 002e).
    """

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
        """Get a session, preferring an injected test session when provided."""
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
        """Mark job as complete (AgentExecution, async safe).

        Args:
            job_id: Job UUID (looks up latest active execution)
            result: Job result data dict
            tenant_key: Optional tenant key (uses current if not provided)
            acknowledge_closeout_todo: RETIRED (BE-9012b, §6 rows 3-6) —
                accepted-and-ignored during the shim window so in-flight callers do
                not 422. The self-referential closeout TODO now auto-clears
                STRUCTURALLY off ``agent_todo_items.todo_kind`` (stamped at write),
                on the orchestrator's own closeout call — no flag needed.
            acknowledge_messages_on_complete: RETIRED (BE-9012b, §6 row 3) —
                accepted-and-ignored. The gate blocks only on genuine action-required,
                non-auto-generated posts, so the drain-before-gate escape hatch is
                unnecessary (informational posts never block; the normal drain is the
                D6 cursor mark_read).

        Returns:
            CompleteJobResult with success status
        """
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

            # BE-3006d: validate the agent-supplied result against the
            # AgentExecutionResult JSONB schema before it reaches the
            # agent_executions.result column. extra="allow" keeps the blob
            # extensible; this only type-checks the known fields. Map the pydantic
            # failure onto our ValidationError so the broad except below re-raises
            # it as a clean 422 (not wrapped into a sanitized 500), and so a
            # malformed value never lands in JSONB. Single boundary — covers both
            # staging-end and normal paths.
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

                    # CE-0032: detect staging-end BEFORE validation so the
                    # TODOs-bypass key can read project flags. The detector
                    # loads the project and returns it for downstream reuse,
                    # avoiding a second query.
                    is_staging_end, staging_end_project = await self._is_staging_end_orchestrator_call(
                        session, job, execution, tenant_key
                    )

                    # BE-6177 (C1): in the IMPLEMENTATION phase a chain CONDUCTOR may
                    # NOT self-complete while its run still has incomplete projects —
                    # that orphans the chain mid-drive. Skipped at staging-end (the
                    # staging-end complete_job is REQUIRED to flip staging_status; the
                    # conductor self-registers during staging, so without this skip the
                    # guard would wrongly block legitimate end-of-staging). No-op for
                    # every non-conductor → solo complete_job stays byte-identical.
                    if not is_staging_end:
                        await self._guard_conductor_chain_incomplete(session, job, execution, tenant_key, job_id)

                    # BE-6083: the orchestrator-closeout phase is an orchestrator
                    # job that is NOT the staging-end transition. The closeout
                    # TODO is self-referential ("call complete_job"), so the
                    # gate auto-acks it here without the agent passing the
                    # chicken-and-egg acknowledge_closeout_todo flag.
                    is_closeout_phase = job.job_type == "orchestrator" and not is_staging_end

                    # BE-6198 (Fix #2): is this a chain SUB-ORCHESTRATOR (a project-bound
                    # member, NOT the project-less conductor)? Its staging-end gate is
                    # crossed by the conductor in software, so the staging-end prose must
                    # tell it to POLL, not "press Implement". Strictly gated: project_id
                    # NOT None (excludes the conductor) AND an active chain run contains
                    # the project. Solo projects (no active run) and the conductor both
                    # return False, keeping their staging-end byte-identical.
                    is_chain_member_suborch = bool(
                        is_staging_end
                        and getattr(job, "project_id", None) is not None
                        and await self._is_chain_member_suborch(session, job.project_id, tenant_key)
                    )

                    # BE-9012b (D7): acknowledge_closeout_todo / acknowledge_messages_on_complete
                    # are retired (accepted-and-ignored on the public complete_job shim), so they
                    # are no longer threaded into the reframed gate.
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

                    # BE-9153: signal-gated closeout_mode enforcement. No-op unless this
                    # is an orchestrator closeout in hitl mode carrying signal; may raise
                    # CLOSEOUT_APPROVAL_REQUIRED (solo block) or create a chain settlement
                    # approval (provisional). Returns the resolved mode for the checklist.
                    closeout_mode = await enforce_closeout_approval_mode(
                        self,
                        session=session,
                        job=job,
                        execution=execution,
                        tenant_key=tenant_key,
                        result=result,
                        is_closeout_phase=is_closeout_phase,
                    )

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

                    # BE-6189 + BE-6199: tear down the conductor's finished run
                    # (best-effort) and detect the project-less chain conductor, which
                    # needs chain-aware responses. Extracted (BE-9153, budget) — returns
                    # is_conductor so _handle_staging_end + _phase_response agree.
                    is_conductor = await self._finalize_conductor_chain(
                        session, job, execution, tenant_key, is_staging_end=is_staging_end
                    )

                    # CE-0026 / CE-0032: state-machine branch for staging-phase
                    # orchestrator. Flips project.staging_status (idempotent)
                    # and returns a STOP directive. CE-0032 removed the
                    # CE-0029 Item 2 pre-spawn — the same orch exec stays
                    # alive in status='waiting' until the user pastes the
                    # impl prompt.
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

                    # BE-3006b: flush inside the scope; the get_session_async
                    # owner commits on block exit, BEFORE the broadcast below
                    # (which runs outside the scope) — events emit only after
                    # commit. See TRANSACTION_OWNERSHIP_CONVENTION.md.
                    await session.flush()
                else:
                    await self._raise_for_missing_execution(session, job_id, tenant_key)

            if execution:
                await self._broadcast_completion(tenant_key, job_id, job, execution, old_status, duration_seconds)

            closeout_checklist = None
            # CE-0027 / CE-0032: closeout_checklist (request_approval, deferred
            # findings) is implementation-phase closeout guidance. Skip it for
            # staging-end orchestrator calls — they get the staging_directive
            # instead. Under CE-0032's single-exec model the prior key on
            # execution.project_phase no longer disambiguates phases (every
            # orch exec has project_phase='staging'); is_staging_end (derived
            # from project flags) is the authoritative phase signal.
            is_impl_phase_orch = job and getattr(job, "job_type", "") == "orchestrator" and not is_staging_end
            if is_impl_phase_orch:
                # INF-5076: orchestrators are coordinators, not committers — commits
                # flow through write_project_closeout(git_commits=[...])
                # on the next call, not through complete_job's result. The previous
                # git-commits warning here fired on every correctly-structured
                # closeout. Agents that actually commit (implementer, tester) are
                # not orchestrators and never reached this branch, so removing the
                # warning loses no coverage.
                try:
                    # BE-9153: pass the resolved closeout_mode so the checklist surfaces
                    # the tenant's setting + the signal keys (instruction-loop repair).
                    closeout_checklist = build_closeout_checklist(closeout_mode)
                except Exception:  # noqa: BLE001
                    # BE-3006d: degrade gracefully — closeout_checklist is optional guidance; None is the fallback.
                    logger.warning("Failed to build closeout checklist during job completion", exc_info=True)
                    closeout_checklist = None

            # BE-6083: make the three-way overload TRANSPARENT. complete_job means
            # one of three things switched on hidden server-side state; the
            # response now self-explains which phase ran + the next action so the
            # agent never has to know its own project_phase to interpret it.
            # is_conductor (BE-6199 #4 / BE-6221e) was computed once inside the
            # session block above and is reused here so the directive and the
            # next_action agree for the project-less chain conductor.
            phase, phase_message, next_action = self._phase_response(
                is_staging_end=is_staging_end,
                is_closeout_phase=is_impl_phase_orch,
                is_conductor=is_conductor,
                is_chain_member_suborch=is_chain_member_suborch,
            )
            # BE-9083b: lifecycle footer from the SAME phase + chain flags as _phase_response, so they never disagree.
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

    async def _is_chain_member_suborch(self, session: AsyncSession, project_id: Any, tenant_key: str) -> bool:
        """Return True if the project belongs to an ACTIVE chain run (BE-6198 Fix #2).

        Mirrors mission_service._is_chain_member. Best-effort: a resolution failure
        returns False so the staging-end response falls back to the solo "press
        Implement" wording and completion is NEVER broken by a chain lookup. The
        caller has already excluded the project-less conductor (project_id is None).
        """
        try:
            from giljo_mcp.services.sequence_run_service import SequenceRunService

            svc = SequenceRunService(
                db_manager=self.db_manager,
                tenant_manager=self.tenant_manager,
                session=session,
            )
            run = await svc.find_active_run_for_project(project_id=str(project_id), tenant_key=tenant_key)
            return run is not None
        except Exception:  # noqa: BLE001 - best-effort chain detection; never break completion
            self._logger.warning("[BE-6198] chain-member check failed (non-fatal); falling back to solo staging-end")
            return False

    async def _guard_conductor_chain_incomplete(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        tenant_key: str,
        job_id: str,
    ) -> None:
        """Delegate to :func:`job_completion_staging.guard_conductor_chain_incomplete` (BE-6177 C1)."""
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
        """Fetch the AgentJob record for completion, raising if not found."""
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
        """Check action-required messages and incomplete TODOs; raise if blocked.

        BE-9012b (D7, §6 rows 1-6): the two gates were reframed server-side to
        dissolve the "closeout dance":

        * The messages gate blocks ONLY on genuine ``requires_action``,
          non-``auto_generated`` posts unacted-on (the repo query filters both);
          informational posts and system completion_reports never block.
        * The self-referential closeout TODO auto-clears STRUCTURALLY off
          ``agent_todo_items.todo_kind`` (stamped at write by progress_service) on
          the orchestrator's own closeout call (``is_closeout_phase``, BE-6083 phase
          detection preserved). A legacy NULL-kind TODO falls back to the shared
          classifier. Ordinary work TODOs still block.

        ``acknowledge_closeout_todo`` / ``acknowledge_messages_on_complete`` are
        RETIRED to accepted-and-ignored (row 3): kept on the signature so in-flight
        callers do not 422, but they no longer drive either gate.
        """
        # BE-5059 Phase B: refuse completion when this execution is parked on a
        # pending user_approval. The TODOs/messages gates do not catch this --
        # an agent in awaiting_user has by definition deferred a decision to the
        # human and cannot self-complete.
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

        # BE-6208c: an agent's OWN outbound Hub post must never arm its own
        # completion gate. A self-authored message addressed back to this agent
        # (or fan-out where the author is also a recipient) is not pending work
        # the agent owes itself. Exclude it before the gate evaluates; the
        # acknowledge_messages_on_complete escape hatch below still drains
        # whatever genuine cross-agent messages remain.
        # BE-6213 P0 / BE-6216: the project-less chain CONDUCTOR posts to its own
        # standalone Hub thread under a free-text LABEL, not its execution UUID, so a
        # self-fanned broadcast slips the UUID-only self-match above and would block
        # its own finale complete_job. Exclude the conductor's self-posts -- but ONLY
        # its UNIQUE label (agent_name, e.g. "Chain Conductor"), NOT its generic
        # agent_display_name. BE-6213 originally broadened to BOTH names; but
        # agent_display_name is the non-unique "orchestrator" (conductor_job_minter.py),
        # the SAME label every sub-orchestrator posts Hub notes under to the conductor's
        # NULL-project escalation thread. Excluding it SILENTLY DROPPED a genuine sub-orch
        # escalation at the finale gate (neither blocked nor auto-acked) -- the exact
        # display-name collision BE-6213 guarded against on the NON-conductor path but left
        # live for the conductor (the escalation sink). Narrow to the unique label only;
        # the conductor posts its OWN Hub notes under that same unique label
        # (CH_CHAIN_DRIVE prose), so self-posts stay self-excluded WITHOUT swallowing a
        # sub-orch post. STRICTLY behind the conductor predicate (project_id None +
        # chain_conductor), so solo / worker / sub-orch gates stay UUID-only and
        # byte-identical. Reuses the same conductor predicate as the chain-drive TODO
        # auto-ack below (BE-6212).
        is_conductor_job = getattr(job, "project_id", None) is None and bool(
            (getattr(job, "job_metadata", None) or {}).get("chain_conductor")
        )
        self_identities = {execution.agent_id}
        if is_conductor_job:
            conductor_label = getattr(execution, "agent_name", None)
            if conductor_label:
                self_identities.add(conductor_label)
        unread_messages = [m for m in unread_messages if m.from_agent_id not in self_identities]

        # BE-9012b (D7, §6 row 3): ``acknowledge_messages_on_complete`` is retired —
        # accepted-and-ignored. The gate now blocks ONLY on genuine action-required posts
        # (get_unread_messages_for_agent already filters to requires_action +
        # non-auto_generated), so the drain-before-gate escape hatch is unnecessary; the
        # parameter stays on the signature so in-flight callers do not 422.

        incomplete_todos = await repo.get_incomplete_todos(session, tenant_key, job_id)

        # CE-0027 / CE-0032: Staging-phase orchestrator TODOs ARE the
        # deliverable plan for downstream implementer/tester agents. The
        # orchestrator writes them during staging precisely BECAUSE they are
        # not yet done; the plan is what survives into implementation.
        # Blocking the staging-end complete_job on these would force the
        # agent to lie about completion status to get past the gate (the
        # test-install billing test). Skip the TODOs gate entirely for staging-
        # phase orchestrators. The unread-messages gate still applies —
        # orchestrators should not abandon their inbox at staging-end.
        #
        # CE-0032 re-keyed the bypass off the vestigial execution.project_phase
        # column onto project flags. Truth table (project|impl_launched_at):
        #   ('staging'|None) → staging-end (fires; TODOs survive into impl)
        #   ('staged'|None)  → defensive; pre-orch-start (fires; no TODOs anyway)
        #   ('staging_complete'|None) → defensive re-call after auto-flip (fires)
        #   ('staging_complete'|<ts>) → impl-end (does NOT fire; TODOs must be done)
        # The restage path (project_staging_service) clears impl_launched_at
        # so restage-after-completion lands back in the staging-end branch.
        is_staging_orchestrator = (
            job.job_type == "orchestrator"
            and project is not None
            and project.staging_status in ("staging", "staged", "staging_complete")
            and project.implementation_launched_at is None
        )
        if is_staging_orchestrator and incomplete_todos:
            self._logger.info(
                "[STAGING] Bypassing incomplete-TODOs gate for staging-phase orchestrator "
                "(%d deliverable TODOs survive into implementation)",
                len(incomplete_todos),
                extra={"job_id": job_id, "tenant_key": tenant_key},
            )
            incomplete_todos = []

        # BE-9012b (D7, §6 rows 4-6): the self-referential closeout TODO auto-clears
        # STRUCTURALLY off ``agent_todo_items.todo_kind`` (stamped once at write by
        # progress_service), not by re-matching keyword regexes here. Row 5 keeps the
        # phase detection: this runs on the agent's own closeout call (is_closeout_phase);
        # row 3 retires the ``acknowledge_closeout_todo`` flag, so it no longer gates the
        # block (accepted-and-ignored). A legacy TODO written before the column existed
        # carries NULL and falls back to ``classify_todo_kind`` (NULL-tolerant read).
        if is_closeout_phase and incomplete_todos:

            def _is_self_closeout_todo(todo) -> bool:
                # Read the durable marker; fall back to on-the-fly classification only
                # for legacy NULL rows (Data-facing DoD answer (a) — tolerate old shape).
                kind = todo.todo_kind if todo.todo_kind is not None else classify_todo_kind(todo.content or "")
                if kind == TODO_KIND_SELF_CLOSEOUT:
                    return True
                # Broad closeout-intent wording clears only on the agent's own closeout
                # call (always true inside this is_closeout_phase branch).
                if kind == TODO_KIND_CLOSEOUT_INTENT:
                    return is_closeout_phase
                # BE-6212: the conductor-only chain-drive family (poll/advance/finale)
                # is done-by-definition at the conductor's finale; STRICTLY behind the
                # conductor predicate, so a solo / sub-orch TODO with the same kind still
                # blocks (is_conductor_job is False for them).
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
        """Update execution fields for completion. Returns (old_status, duration_seconds).

        CE-0032: when ``is_staging_end`` is True, the orchestrator entity is
        pausing between staging and implementation — not ending. Set
        ``status='waiting'`` (NOT 'complete'), leave ``completed_at`` unset,
        and preserve the prior ``progress`` so the dashboard doesn't lie about
        a session-end. The same ``AgentExecution`` row will transition back to
        'working' on the next ``get_job_mission`` call when the user pastes
        the implementation prompt (existing logic in mission_service.py:174).
        ``result`` is still stored for audit trail.
        """
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
        """Mark job as completed if no other active executions remain.

        CE-0028: when this complete_job call is the staging→implementation
        transition for the orchestrator, preserve ``job.status='active'``.
        The same AgentJob carries the orchestrator across both phases; the
        implementation-phase execution attaches to this row and the job's
        completion only fires when the implementation session closes. Flipping
        the job to 'completed' at staging-end made the UI treat the project
        as fully done (closeout modal + 360-memory poll), blocking the
        Implement (play) button flow.
        """
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
        """Delegate to :func:`job_completion_staging.finalize_conductor_chain` (BE-6189/BE-6199)."""
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
        """Check if execution was decommissioned and raise appropriate error."""
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

    async def _broadcast_completion(self, tenant_key, job_id, job, execution, old_status, duration_seconds):
        """Delegate to OrchestrationAgentStateService for broadcast."""
        if self._agent_state:
            await self._agent_state._broadcast_completion(
                tenant_key, job_id, job, execution, old_status, duration_seconds
            )

    async def _handle_completion_side_effects(self, session, job, execution, result, tenant_key, warnings):
        """Delegate to OrchestrationAgentStateService for side effects."""
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
        """Delegate to :func:`job_completion_staging.is_staging_end_orchestrator_call` (CE-0026/CE-0028)."""
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
        """Delegate to :func:`job_completion_staging.handle_staging_end` (CE-0026)."""
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
            test_session=self._test_session,
        )

    @staticmethod
    def _staging_directive_for(is_chain_member_suborch: bool, is_conductor: bool = False) -> StagingDirective:
        """Delegate to :func:`job_completion_staging.staging_directive_for` (BE-6198 S1 / BE-6221e)."""
        return staging_directive_for(is_chain_member_suborch, is_conductor=is_conductor)

    @staticmethod
    def _phase_response(
        *,
        is_staging_end: bool,
        is_closeout_phase: bool,
        is_conductor: bool = False,
        is_chain_member_suborch: bool = False,
    ) -> tuple[str, str, dict[str, Any] | None]:
        """Map the detected complete_job phase to (phase, message, next_action).

        BE-6083: complete_job is overloaded three ways switched on hidden
        server-side state. This turns the hidden switch into an explicit,
        self-explaining response — the same data the staging_directive /
        closeout_checklist already carry, surfaced as plain ``message`` +
        ``next_action`` (BE-8003a canonical envelope) so any caller (not just
        orchestrators) sees what just happened and what to do next.

        Precedence matches the rest of complete_job: staging-end is detected
        first (orchestrator pausing between staging and implementation), then
        the orchestrator-closeout phase (orchestrator job that is not
        staging-end), and everything else is a deliverable worker completing.

        BE-6199 (#4): the project-less chain conductor reaches the closeout phase
        on its final self-complete but owns no project, so the solo
        write_project_closeout next_action does not apply. ``is_conductor`` swaps
        in the chain-appropriate next step. Solo / project-bound orchestrators
        (is_conductor False) keep the original closeout response byte-identical.
        """
        if is_staging_end:
            # BE-6198 (Fix #2 / S2): a chain SUB-ORCHESTRATOR's gate is opened by the
            # conductor in software — it must POLL, not wait for a human click.
            if is_chain_member_suborch:
                return (
                    "staging_end",
                    "Staging marked complete.",
                    build_next_action(tool="get_job_mission", why=_CHAIN_SUBORCH_STAGING_END_NEXT_ACTION),
                )
            # BE-6221e: the project-less chain CONDUCTOR must HALT after staging and
            # wait for the user's EXPLICIT GO (human-in-the-loop gate) — not "press
            # Implement" once and auto-drive. Its next_action carries the await-GO
            # wording so it agrees with the staging_directive + the chain prose. SOLO
            # projects (is_conductor False, is_chain_member_suborch False) keep the
            # original "human presses Implement" next_action BYTE-IDENTICAL.
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
                    why=(
                        "Stop this session now. A human presses Implement in the dashboard to start the "
                        "implementation session with a fresh orchestrator execution. Do NOT write the "
                        "project closeout from the staging session."
                    )
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

    # BE-9153: _build_closeout_checklist moved to job_completion_closeout_gate.build_closeout_checklist
    # (co-located with the closeout-approval gate + made closeout_mode-aware).
