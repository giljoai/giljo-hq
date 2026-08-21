# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MissionService - Agent mission retrieval and orchestrator instructions.

Extracted from OrchestrationService (Handover 0769) as part of the facade pattern
refactoring. Owns mission retrieval (get_agent_mission), staging context, mission
updates, and agent-template resolution; orchestration concerns delegate to
MissionOrchestrationService.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    DatabaseError,
    OrchestrationError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import (
    AgentExecution,
    AgentJob,
    AgentTemplate,
)
from giljo_mcp.platform_registry import EXECUTION_MODE_TO_TOOL, MULTI_TERMINAL, Platform, get_preset
from giljo_mcp.repositories.mission_repository import MissionRepository
from giljo_mcp.schemas.responses.orchestration import (
    IDENTITY_ORCHESTRATOR_DEFAULT,
    IDENTITY_RESOLVED,
)
from giljo_mcp.schemas.service_responses import (
    MissionResponse,
    MissionUpdateResult,
)
from giljo_mcp.services._error_helpers import not_found_or_wrong_state_error
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.comm_thread_enrolment import resolve_and_enrol
from giljo_mcp.services.conductor_chain_injector import inject_conductor_chain_drive
from giljo_mcp.services.conductor_mission_mirror import mirror_chain_mission_for_conductor
from giljo_mcp.services.execution_mode_gate import effective_execution_mode
from giljo_mcp.services.loop_directive_composer import compose_loop_directive
from giljo_mcp.services.mission_assembly import (
    assemble_mission_context,
    compose_template_identity,
    compose_unresolved_identity,
    compute_is_chain_conductor,
    compute_protocol_etag,
)
from giljo_mcp.services.mission_implementation_gate import (
    check_implementation_gate,
    is_chain_member,
)
from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.services.orchestrator_product_resolver import compose_identity_with_provenance
from giljo_mcp.services.protocol_survival import finalize_mission_wire_fields
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


# HO1020: execution_mode -> protocol tool. Callers apply .get(mode, "multi_terminal")
# so unknown modes route to the generic branch, not Claude Code Task() syntax.
# BE-6041b: antigravity_cli -> 'antigravity' (tool_type drops the _cli suffix).
# BE-3010a: single source is the PlatformRegistry; aliased to the prior name so
# in-module callers (and their .get(mode, "multi_terminal") fail-safe) are unchanged.
_EXECUTION_MODE_TO_TOOL = EXECUTION_MODE_TO_TOOL

# BE-6213 P1: a worker spawned while its CHAIN sub-orchestrator is still staging
# hits the implementation gate. The chain has no human "Implement" button, so the
# legacy solo wording ("click the Implement button") would strand it on an
# infinite human-wait. Chain workers auto-activate when the sub-orch ends staging,
# so they just re-call get_job_mission. Solo workers keep the legacy message
# (Deletion Test on the solo gate).
_CHAIN_WORKER_STAGING_BLOCK_MESSAGE = (
    "Your CHAIN ORCHESTRATOR is still STAGING this project -- there is no "
    "'Implement' button and no human gate in chain mode. Do NOT wait for a "
    "human. Your gate opens automatically the moment the orchestrator ends "
    "staging; call get_job_mission again then (and periodically until) to "
    "receive your mission."
)


class MissionService:
    """
    Service for agent mission retrieval and orchestrator instructions.

    Extracted from OrchestrationService to reduce module size.
    """

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
        self._template_generator = None
        self._repo = MissionRepository()
        self._orchestration = MissionOrchestrationService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            test_session=test_session,
            websocket_manager=self._websocket_manager,
        )

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def get_agent_mission(
        self,
        job_id: str,
        tenant_key: str,
        protocol_etag: str | None = None,
        preset_name: str | None = None,
        detected_harness: str | None = None,
        section: str = "",
    ) -> MissionResponse:
        """Get agent-specific mission. Atomic job start: first fetch transitions
        waiting -> working; subsequent fetches are idempotent re-reads.

        preset_name (BE-8003f): MCP-boundary harness preset (web_sandbox/desktop_app/chat,
        else None) → shell-less render ladder; None (CLI) = byte-identical (D1).
        detected_harness (BE-9079): session-detected harness token; applies DETECTED-beats-declared
        precedence so a detected session renders native spawn prose; None/"generic" = byte-identical.
        protocol_etag (BE-6208g/6211c): caller's cached static-block hash; on a match the
        static block is omitted (protocol_unchanged=True); the fresh etag always rides back,
        prose byte-identical either way. Raises ResourceNotFoundError / DatabaseError.
        section (BE-9083d, recovery-only): a protocol_toc section name; the response then
        carries ONLY that byte-identical slice of the full render (ValidationError on an
        unknown name). Default "" keeps the full response — sections are never the default.
        """
        # BE-8003f: resolve the harness preset once (None on CLI → byte-identical);
        # threaded into the protocol assembly + the conductor chain injector below.
        preset = get_preset(preset_name)
        try:
            status_changed = False
            old_status: str | None = None
            execution: AgentExecution | None = None
            job: AgentJob | None = None
            all_project_executions: list[AgentExecution] = []
            mission_lookup: dict[str, str] = {}
            agent_identity: str | None = None
            identity_status: str = IDENTITY_RESOLVED
            current_team_state: list[dict] | None = None
            project = None

            async with self._get_session(tenant_key) as session:
                job, execution = await self._fetch_job_and_execution(session, job_id, tenant_key)

                # Handover 0709: Implementation phase gate
                if job.project_id:
                    project, gate_response = await self._check_implementation_gate(
                        session,
                        job,
                        job_id,
                        tenant_key,
                    )
                    if gate_response is not None:
                        return gate_response

                # BE-9012d resolve + TSK-9459 structural enrolment, on the SAME session as
                # the render (no cross-session read/write skew). The ORCHESTRATOR used to
                # be excluded here, so it alone was never handed its own thread id and
                # never joined -- see comm_thread_enrolment for why that is a mechanism gap.
                comm_thread_id = await resolve_and_enrol(self, session, job, execution, tenant_key)

                # Fetch team context and orchestrator state
                all_project_executions, mission_lookup, current_team_state = await self._fetch_team_context(
                    session, job, execution, job_id, tenant_key
                )

                # BE-6177: for a chained orchestrator the protocol header mode comes
                # from the RUN, not the project column (a project-less conductor would
                # otherwise default to multi_terminal and render a header that
                # contradicts CH_CAPABILITY). None on the solo path (byte-identical).
                # BE-6211g (move c): resolved BEFORE identity so the project-less
                # conductor's identity can be role-trimmed via is_chain_conductor below.
                chain_execution_mode = await self._resolve_chain_execution_mode(
                    session,
                    job,
                    execution,
                    tenant_key,
                )

                # BE-6211g (move c): the project-less chain conductor (active run +
                # no project) gets a role-scoped identity. SHARED helper with
                # mission_assembly.py so the identity trim and the protocol-body trim
                # can never disagree on conductor-ness for one run. Solo / sub-orch ->
                # False -> role=None -> byte-identical identity.
                is_chain_conductor = compute_is_chain_conductor(chain_execution_mode, job.project_id)

                # Resolve agent identity from template (Handover 0825)
                agent_identity, identity_status, identity_source = await self._resolve_mission_template(
                    session,
                    job,
                    execution,
                    tenant_key,
                    is_chain_conductor=is_chain_conductor,
                    chain_execution_mode=chain_execution_mode,
                )

                # Atomic start semantics on FIRST mission fetch
                if execution.status == "waiting":
                    now = datetime.now(UTC)
                    old_status = execution.status
                    execution.status = "working"
                    execution.started_at = now
                    execution.last_progress_at = now
                    status_changed = True

                    await session.commit()
                    await self._repo.refresh(session, execution)

                    self._logger.info(
                        "[JOB SIGNALING] Mission started via get_agent_mission",
                        extra={
                            "job_id": sanitize(job_id),
                            "agent_id": sanitize(execution.agent_id),
                            "agent_display_name": sanitize(execution.agent_display_name),
                            "old_status": sanitize(old_status),
                            "new_status": sanitize(execution.status),
                        },
                    )

            # WebSocket emissions happen after the database transaction is complete
            if execution and status_changed and old_status is not None:
                try:
                    if self._websocket_manager:
                        await self._websocket_manager.broadcast_to_tenant(
                            tenant_key=tenant_key,
                            event_type="agent:status_changed",
                            data={
                                "job_id": job_id,
                                "project_id": str(job.project_id) if job.project_id else None,
                                # BE-6229: ride the chain_conductor flag (mirrors REST serializer)
                                # so the FE JobsTab filter excludes the conductor on the live path.
                                "chain_conductor": bool(
                                    (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                                ),
                                "agent_id": execution.agent_id,
                                "agent_display_name": execution.agent_display_name,
                                "agent_name": execution.agent_name,
                                "old_status": old_status,
                                "status": "working",
                                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                                "duration_seconds": execution.duration_seconds,  # BE-5107
                                "working_started_at": execution.working_started_at.isoformat()
                                if execution.working_started_at
                                else None,
                            },
                        )

                    self._logger.info(
                        "[WEBSOCKET] Emitted status change events for get_agent_mission",
                        extra={"job_id": sanitize(job_id), "agent_id": sanitize(execution.agent_id)},
                    )
                except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                    self._logger.warning(f"[WEBSOCKET] Failed to emit status events: {ws_error}")

            if not execution or not job:
                raise ResourceNotFoundError(
                    message=f"Agent job {job_id} not found",
                    context={"job_id": job_id, "tenant_key": tenant_key},
                )

            # BE-5008 + FE-9296b: toggles + resolved cadence (assembly is session-free).
            from giljo_mcp.services.settings_service import load_integrations_and_cadence

            integrations, checkin_cadence_minutes = await load_integrations_and_cadence(
                self._get_session, tenant_key, project
            )

            mission_response = self._assemble_mission_context(
                job=job,
                execution=execution,
                project=project,
                agent_identity=agent_identity,
                all_project_executions=all_project_executions,
                mission_lookup=mission_lookup,
                current_team_state=current_team_state,
                tenant_key=tenant_key,
                integrations=integrations,
                chain_execution_mode=chain_execution_mode,
                preset=preset,
                comm_thread_id=comm_thread_id,
                detected_harness=detected_harness,
                checkin_cadence_minutes=checkin_cadence_minutes,
                identity_status=identity_status,  # BE-9333 signal + BE-9402 serve gate
                identity_source=identity_source,  # FE-9408 provenance, gated with the identity
            )
            # BE-6177 Bug 4 (chain-blind runtime); BE-9092: proto alias keeps the inject arg-line <=120.
            proto = mission_response.full_protocol
            mission_response.full_protocol = await inject_conductor_chain_drive(
                self, proto, job, execution, project, tenant_key, preset=preset, detected_harness=detected_harness
            )
            # BE-6054c: append the loop/sleep directive when the user armed a loop on a thread for this agent.
            mission_response.full_protocol = await compose_loop_directive(
                mission_response.full_protocol, self._get_session, tenant_key, str(execution.agent_id), self._logger
            )

            # BE-6208g/6211c etag emission + BE-9083a truncation sentinels + BE-9083d
            # section fetch: one wire finalizer owns the marker → hash → section →
            # match-strip → sentinel+TOC order (see protocol_survival for the rationale).
            finalize_mission_wire_fields(mission_response, protocol_etag, section=section)

            return mission_response

        except (ResourceNotFoundError, ValidationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get agent mission")
            raise DatabaseError(
                message=f"Unexpected error: {e!s}", context={"job_id": job_id, "tenant_key": tenant_key}
            ) from e

    async def _get_agent_template_internal(
        self, role: str, tenant_key: str, session: AsyncSession | None = None
    ) -> AgentTemplate | None:
        """
        Get agent template for role with cascade resolution.

        Resolution: tenant-specific -> system default.

        Args:
            role: Agent role name (e.g., "implementer", "tester")
            tenant_key: Tenant key for multi-tenant isolation
            session: Optional AsyncSession (if not provided, creates new session)

        Returns:
            AgentTemplate instance or None if no template found
        """
        if session:
            template = await self._repo.get_template_by_role(session, tenant_key, role)
            if template:
                self._logger.info(f"[_get_agent_template_internal] Found template for role={role}, tenant={tenant_key}")
            else:
                self._logger.warning(
                    f"[_get_agent_template_internal] No template found for role={role}, tenant={tenant_key}"
                )
            return template
        async with self._get_session(tenant_key) as db_session:
            return await self._get_agent_template_internal(role, tenant_key, db_session)

    async def _fetch_job_and_execution(
        self,
        session: AsyncSession,
        job_id: str,
        tenant_key: str,
    ) -> tuple[AgentJob, AgentExecution]:
        """Fetch the job and its latest active execution, raising on not-found."""
        job = await self._repo.get_job(session, tenant_key, job_id)

        if not job:
            raise ResourceNotFoundError(
                message=f"Agent job {job_id} not found", context={"job_id": job_id, "tenant_key": tenant_key}
            )

        execution = await self._repo.get_active_execution(session, tenant_key, job_id)

        if not execution:
            raise await not_found_or_wrong_state_error(
                session,
                tenant_key,
                job_id,
                expected_status="active",
                method="get_agent_mission",
                db_manager=self.db_manager,
            )

        return job, execution

    async def _check_implementation_gate(
        self,
        session: AsyncSession,
        job: AgentJob,
        job_id: str,
        tenant_key: str,
    ) -> tuple[Any, MissionResponse | None]:
        """BE-9073: back-compat shim — logic lives in mission_implementation_gate.check_implementation_gate."""
        return await check_implementation_gate(
            self._logger,
            session,
            job,
            job_id,
            tenant_key,
            repo=self._repo,
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
        )

    async def _is_chain_member(self, session: AsyncSession, project_id: Any, tenant_key: str) -> bool:
        """BE-9073: back-compat shim — logic lives in mission_implementation_gate.is_chain_member."""
        return await is_chain_member(
            self._logger,
            session,
            project_id,
            tenant_key,
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
        )

    async def _resolve_chain_execution_mode(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        tenant_key: str,
    ) -> str | None:
        """Resolve the chain header mode for a chained orchestrator (BE-6177 / BE-6205).

        The full_protocol header (the EXECUTION_MODE / FORBIDDEN-Task banner in
        agent_lifecycle.py) is gated on the mode passed to ``_generate_agent_protocol``.
        For a chain member that mode MUST agree with CH_CAPABILITY for the same run:

          * The DEDICATED conductor is project-LESS (``job.project_id IS NULL``). Under
            the BE-6205 model the conductor ALWAYS spawns each sub-orchestrator in a
            FRESH TERMINAL (every execution_mode) and NEVER via Task(), so its header
            must be TERMINAL-based, never Task()-steering. We therefore PIN the
            conductor header to ``multi_terminal`` (the terminal / FORBIDDEN-Task banner)
            regardless of the run's worker-spawn mode — this REVERSES the a4c9e7995
            logic that resolved the run mode (claude_code_cli) and suppressed the banner.
            (The run's real worker-spawn mode still reaches CH_CHAIN_DRIVE / the spawn
            table via ``chain_ctx.execution_mode``; this resolver feeds the header only.)
          * A sub_orchestrator (project-BOUND) keeps resolving the RUN's mode: its header
            describes how IT spawns its WORKERS (Task() in a subagent mode), which is
            correct for the sub-orch.

        Returns ``multi_terminal`` for a project-less conductor on an active run, the
        run's ``execution_mode`` for a sub_orchestrator on an active run, else None (the
        common solo path → caller keeps the project-derived mode, byte-identical render).
        Orchestrator jobs only; never raises (best-effort, must never break delivery).
        """
        if job.job_type != "orchestrator":
            return None
        try:
            from giljo_mcp.services.sequence_run_service import SequenceRunService

            svc = SequenceRunService(
                db_manager=self.db_manager,
                tenant_manager=self.tenant_manager,
                session=session,
            )
            if job.project_id:
                run = await svc.find_active_run_for_project(project_id=str(job.project_id), tenant_key=tenant_key)
                if run is None:
                    return None
                return run.get("execution_mode")
            # Project-less DEDICATED conductor: resolve the run only to confirm it IS a
            # conductor, then pin the header to multi_terminal (terminal-based spawn).
            run = await svc.find_active_run_for_conductor(
                conductor_agent_id=str(execution.agent_id), tenant_key=tenant_key
            )
            if run is None:
                return None
            return MULTI_TERMINAL
        except Exception:  # noqa: BLE001 - best-effort; never break mission delivery
            self._logger.warning("[BE-6177] chain header mode resolution failed (non-fatal); using project mode")
            return None

    async def _fetch_team_context(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        job_id: str,
        tenant_key: str,
    ) -> tuple[list[AgentExecution], dict[str, str], list[dict] | None]:
        """Fetch project-wide executions and build team context for orchestrator.

        Returns:
            Tuple of (all_project_executions, mission_lookup, current_team_state).
        """
        current_team_state: list[dict] | None = None

        if not job.project_id:
            return [execution], {job.job_id: job.mission}, None

        rows = await self._repo.get_project_executions_with_jobs(session, tenant_key, job.project_id)
        all_project_executions = [row[0] for row in rows]

        mission_lookup: dict[str, str] = {}
        for _, job_row in rows:
            mission_lookup[job_row.job_id] = job_row.mission

        # Handover 0830: Build live team state for the orchestrator.
        # BE-6008: also build it for SPECIALISTS so the multi_terminal read-time
        # roster chapter (ch_team) reflects live peer status, not the spawn-time
        # snapshot baked into the mission text.
        current_team_state = []
        for exec_row, job_row in rows:
            if job_row.job_id == job_id:
                continue
            current_team_state.append(
                {
                    "agent_name": exec_row.agent_name,
                    "agent_display_name": exec_row.agent_display_name,
                    "job_id": job_row.job_id,
                    "agent_id": str(exec_row.agent_id),
                    "execution_status": exec_row.status,
                    "phase": job_row.phase,
                }
            )
        current_team_state.sort(key=lambda x: x.get("phase") or 0)

        return all_project_executions, mission_lookup, current_team_state

    async def _resolve_mission_template(
        self,
        session: AsyncSession,
        job: AgentJob,
        execution: AgentExecution,
        tenant_key: str,
        is_chain_conductor: bool = False,
        chain_execution_mode: str | None = None,
    ) -> tuple[str | None, str, str | None]:
        """Resolve agent identity from template or orchestrator defaults.

        Handover 0825: Identity is resolved at read-time, not baked at spawn.

        BE-6211g (move c): ``is_chain_conductor`` (default False -> byte-identical
        for every solo / sub-orch / specialist path) role-trims the project-less
        chain conductor's composed orchestrator identity.

        Returns:
            ``(agent_identity, identity_status, identity_source)``. BE-9333: identity
            is never None any more -- a job whose template does not resolve gets an
            explicit block saying so plus a ``template_unresolved`` /
            ``template_unbound`` status, because a bare None was indistinguishable
            from a healthy response. FE-9408: ``identity_source`` is the provenance
            line, None for every path but the composed orchestrator one -- a bound
            TEMPLATE identity does not come off the override ladder, so it has no rung
            to report and must not claim one.
        """
        agent_identity: str | None = None
        job_id = job.job_id

        if getattr(job, "template_id", None):
            identity_template = await self._repo.get_template_by_id(session, tenant_key, job.template_id)

            if identity_template:
                agent_identity = compose_template_identity(identity_template, execution)
                self._logger.info(
                    "[AGENT_IDENTITY] Resolved identity from template at read time",
                    extra={"job_id": job_id, "template_id": job.template_id},
                )

        # Handover 0830/0966: Orchestrator identity — resolve from seeded template
        # instead of hardcoded fallback, so the orchestrator retains full behavioral
        # guidance across the staging→implementation session boundary.
        # HO1025: pass the project's execution-mode-derived tool so the
        # Claude-Code-specific TaskCreate harness override only renders for
        # Claude Code orchestrators (codex/gemini/multi_terminal omit it).
        # BE-9333 (audit F1): this fallback is for an orchestrator that was NEVER BOUND (no
        # `orchestrator` row is seeded, so that is the normal case). Keyed on job_type alone it
        # also caught a job that WAS bound and whose template has since been DELETED, silently
        # substituting the seeded default and reporting it healthy -- the very substitution this
        # project removes, surviving because job_type is the display name verbatim. A set
        # `template_id` here means the lookup above ran and failed (a resolved one would have
        # filled agent_identity), so fall through to the degraded branch instead.
        if job.job_type == "orchestrator" and not agent_identity and not getattr(job, "template_id", None):
            # HO1027: Use the canonical composer so the system harness (MCP
            # Tool Usage, CHECK-IN PROTOCOL, HARNESS REMINDER OVERRIDE) is
            # always appended — even when the tenant admin has saved a
            # custom seed override via SystemPromptService.
            project = await self._repo.get_project_by_id(session, tenant_key, job.project_id)
            project_exec_mode = getattr(project, "execution_mode", "multi_terminal") if project else "multi_terminal"
            # BE-9335: same resolver as the protocol body (identity must not contradict it).
            mode = effective_execution_mode(project_exec_mode, chain_execution_mode)
            tool = _EXECUTION_MODE_TO_TOOL.get(mode, "multi_terminal")

            # BE-6211g (move c): the project-less chain conductor receives a role-
            # scoped identity (trimmed of context-response / verify-all-agents /
            # worker-spawn blocks it must not act on). role=None for every other
            # orchestrator -> byte-identical to today.
            role = "conductor" if is_chain_conductor else None
            # BE-9385d: product override -> tenant override -> seeded default, with the
            # project-less conductor resolved through its run; never raises, a failed
            # read degrades to the seed exactly as HO1027 required. FE-9408: the same
            # composition, plus the line saying which rung produced it.
            agent_identity, identity_source, prompt_scope = await compose_identity_with_provenance(
                self, session, job, execution, tenant_key, project, tool=tool, role=role
            )
            self._logger.info(
                "[AGENT_IDENTITY] Composed orchestrator identity (override+harness or seed+harness)",
                # BE-9385d: prompt_scope replaces is_override -- it says WHICH rung
                # answered (product/tenant/default), which strictly subsumes it.
                extra={"job_id": job_id, "tool": tool, "prompt_scope": prompt_scope},
            )
            return agent_identity, IDENTITY_ORCHESTRATOR_DEFAULT, identity_source

        # BE-9333: nothing loaded. Say so in the field the agent actually reads, and log it --
        # the read path was previously silent at BOTH levels (no flag, no line). `not` rather
        # than `is None` so an empty composition can never slip through as a healthy identity;
        # compose_template_identity always emits its framing line, so this changes nothing today.
        if not agent_identity:
            agent_identity, status = compose_unresolved_identity(job, execution)
            self._logger.warning(
                "[AGENT_IDENTITY] No template resolved -- agent runs with no role framing",
                extra={"job_id": job_id, "template_id": job.template_id, "identity_status": status},
            )
            return agent_identity, status, None

        return agent_identity, IDENTITY_RESOLVED, None

    @staticmethod
    def _compute_protocol_etag(agent_identity: str | None, full_protocol: str | None) -> str:
        """BE-6211f: back-compat shim — logic lives in mission_assembly.compute_protocol_etag."""
        return compute_protocol_etag(agent_identity, full_protocol)

    def _assemble_mission_context(
        self,
        job: AgentJob,
        execution: AgentExecution,
        project: Any,
        agent_identity: str | None,
        all_project_executions: list[AgentExecution],
        mission_lookup: dict[str, str],
        current_team_state: list[dict] | None,
        tenant_key: str,
        integrations: dict | None = None,
        chain_execution_mode: str | None = None,
        preset: Platform | None = None,
        comm_thread_id: str | None = None,
        detected_harness: str | None = None,
        checkin_cadence_minutes: int | None = None,
        identity_status: str = IDENTITY_RESOLVED,
        identity_source: str | None = None,
    ) -> MissionResponse:
        """BE-6211f: back-compat shim — logic lives in mission_assembly.assemble_mission_context."""
        return assemble_mission_context(
            self._logger,
            job=job,
            execution=execution,
            project=project,
            agent_identity=agent_identity,
            all_project_executions=all_project_executions,
            mission_lookup=mission_lookup,
            current_team_state=current_team_state,
            tenant_key=tenant_key,
            integrations=integrations,
            chain_execution_mode=chain_execution_mode,
            preset=preset,
            comm_thread_id=comm_thread_id,
            detected_harness=detected_harness,
            checkin_cadence_minutes=checkin_cadence_minutes,
            identity_status=identity_status,
            identity_source=identity_source,
        )

    async def _resolve_comm_thread_id(
        self,
        session: AsyncSession,
        job: AgentJob,
        tenant_key: str,
    ) -> str | None:
        """Resolve the project's bound Hub thread for the BE-9012d worker wiring.

        Constructs ``CommThreadService`` on the SAME session as the mission render
        (no cross-session read) and delegates to the shared resolver
        (``resolve_or_create_bound_thread``) — the identical precedence the D9 bus
        shims and the D1(a) 360-pane use. Best-effort, mirroring
        ``_resolve_chain_execution_mode`` / ``_is_chain_member`` above: a resolution
        failure must never break mission delivery — the worker protocol simply
        degrades to its "no coordination thread bound" prose (None).
        """
        try:
            from giljo_mcp.services.comm_thread_service import CommThreadService

            comm_service = CommThreadService(self.db_manager, self.tenant_manager, session=session)
            thread = await comm_service.resolve_or_create_bound_thread(
                project_id=str(job.project_id), tenant_key=tenant_key
            )
            return thread.get("thread_id")
        except Exception:  # noqa: BLE001 - best-effort; never break mission delivery
            self._logger.warning(
                "[BE-9012d] comm thread resolution failed (non-fatal); worker protocol renders without a bound thread",
                extra={"job_id": job.job_id, "project_id": str(job.project_id)},
            )
            return None

    async def get_staging_instructions(
        self, job_id: str, tenant_key: str, preset_name: str | None = None, detected_harness: str | None = None
    ) -> dict[str, Any]:
        """
        Fetch orchestrator mission with framing-based context instructions (Handover 0350b).

        Delegates to MissionOrchestrationService (extracted in Handover 0950n).

        BE-8003f (D2 activation): pass ``preset_name`` (the MCP-boundary harness token)
        straight through so the conductor staging script renders its shell-less ladder.
        None (every CLI caller) → byte-identical (D1).

        BE-9035b: ``detected_harness`` (the harness token resolved from the session
        clientInfo, or None/``"generic"``) is threaded the same way so the
        orchestrator-protocol builder can apply the DETECTED-beats-declared render
        precedence. None/generic → byte-identical.
        """
        return await self._orchestration.get_staging_instructions(
            job_id, tenant_key, preset_name=preset_name, detected_harness=detected_harness
        )

    async def update_agent_mission(self, job_id: str, tenant_key: str, mission: str) -> MissionUpdateResult:
        """
        Update the mission field of an AgentJob.

        Handover 0380: Used by orchestrators to persist their execution plan during staging.
        This allows fresh-session orchestrators to retrieve the plan via get_job_mission()
        during implementation phase.

        Handover 0730b: Exception-based error handling (no success wrapper).

        Args:
            job_id: The AgentJob.job_id (work order UUID)
            tenant_key: Tenant isolation key
            mission: The execution plan/mission to persist

        Returns:
            {"job_id": job_id, "mission_updated": True, "mission_length": len(mission)}

        Raises:
            ResourceNotFoundError: Agent job not found
            OrchestrationError: Failed to update agent mission
        """
        try:
            async with self._get_session() as session:
                job = await self._repo.get_job(session, tenant_key, job_id)

                if not job:
                    raise ResourceNotFoundError(
                        message=f"Agent job {job_id} not found",
                        error_code="NOT_FOUND",
                        context={
                            "job_id": job_id,
                            "tenant_key": tenant_key,
                            "method": "update_agent_mission",
                            "troubleshooting": [
                                "Verify job_id is correct",
                                "Ensure tenant_key matches",
                            ],
                        },
                    )

                job.mission = mission

                # BE-6008 Phase-2 write: a staged agent's mission is now authored,
                # so unlock it by transitioning the execution staged -> waiting.
                # Tenant-scoped lookup; no-op for already-launched agents.
                execution = await self._repo.get_execution_with_job(session, tenant_key, job_id)
                if execution is not None and execution.status == "staged":
                    execution.status = "waiting"

                await session.commit()

                # Emit WebSocket event for UI update
                if self._websocket_manager:
                    try:
                        await self._websocket_manager.broadcast_to_tenant(
                            tenant_key=tenant_key,
                            event_type="job:mission_updated",
                            data={
                                "job_id": job_id,
                                "job_type": job.job_type,
                                "mission_length": len(mission),
                                "project_id": str(job.project_id) if job.project_id else None,
                            },
                        )
                        logger.info(
                            f"[WEBSOCKET] Broadcasted job:mission_updated for {sanitize(job_id)}",
                            extra={"job_id": sanitize(job_id), "tenant_key": sanitize(tenant_key)},
                        )
                    except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                        logger.warning(f"[WEBSOCKET] Failed to broadcast job:mission_updated: {ws_error}")

                # Handover 0826 / CE-0026: Server-side staging completion signal.
                # When an orchestrator persists its mission and sub-agents exist,
                # staging is structurally complete -- delegate to the shared
                # ``mark_staging_complete`` helper so this path, ``complete_job``,
                # and any future caller all converge on a single canonical
                # implementation (CE-0026: helper extracted to project_helpers).
                if job.job_type == "orchestrator" and job.project_id:
                    agent_count = await self._repo.count_non_orchestrator_agents(session, tenant_key, job.project_id)

                    if agent_count > 0:
                        project = await self._repo.get_project_by_id(session, tenant_key, job.project_id)
                        if project:
                            from giljo_mcp.services.project_helpers import mark_staging_complete

                            flipped = await mark_staging_complete(
                                session,
                                project,
                                source="mission_service.update_agent_mission",
                                websocket_manager=self._websocket_manager,
                                agent_count=agent_count,
                            )
                            if flipped:
                                await session.commit()

                # BE-6186: when the CHAIN CONDUCTOR writes its job mission, that
                # mission IS the chain mission (the cross-project plan). Mirror it
                # into sequence_runs.chain_mission (the FE-facing column) so the
                # dashboard shows it. Conductor-only (job_metadata.chain_conductor):
                # a NON-conductor job never fires this, so no leakage. Best-effort:
                # the mirror NEVER fails update_agent_mission (an ultralocked-run
                # refusal or a transient error leaves the primary write intact).
                await self._mirror_chain_mission_for_conductor(session, job, tenant_key, mission)

                logger.info(
                    f"[UPDATE_AGENT_MISSION] Updated mission for job {sanitize(job_id)}",
                    extra={
                        "job_id": sanitize(job_id),
                        "job_type": sanitize(job.job_type),
                        "mission_length": len(mission),
                        "tenant_key": sanitize(tenant_key),
                    },
                )

                # Handover 0731c: Typed return (MissionUpdateResult)
                return MissionUpdateResult(
                    job_id=job_id,
                    mission_updated=True,
                    mission_length=len(mission),
                )

        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            logger.exception("Failed to update agent mission")
            raise OrchestrationError(
                message="Failed to update agent mission",
                error_code="INTERNAL_ERROR",
                context={"job_id": job_id, "error": str(e)},
            ) from e

    async def _mirror_chain_mission_for_conductor(
        self,
        session: AsyncSession,
        job: AgentJob,
        tenant_key: str,
        mission: str,
    ) -> None:
        """Mirror a chain conductor's job mission into sequence_runs.chain_mission (BE-6186).

        Conductor-only (job_metadata.chain_conductor); a NON-conductor job no-ops, so
        no leakage. Delegates to the best-effort module helper so a failure (e.g. an
        ultralocked-run refusal once Implement is reached) never breaks the primary
        update_agent_mission write. Tenant-scoped; the write routes through
        SequenceRunService (the owning service).
        """
        await mirror_chain_mission_for_conductor(
            session=session,
            job=job,
            tenant_key=tenant_key,
            mission=mission,
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            repo=self._repo,
            websocket_manager=self._websocket_manager,
        )
