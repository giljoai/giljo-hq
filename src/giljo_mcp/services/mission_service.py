# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    compose_agent_profile,
    compose_template_identity,
    compose_unresolved_identity,
    compute_is_chain_conductor,
    compute_protocol_etag,
)
from giljo_mcp.services.mission_implementation_gate import (
    check_implementation_gate,
    is_chain_member,
    promote_chain_member_on_first_worker_start,
)
from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.services.orchestrator_product_resolver import compose_identity_with_provenance
from giljo_mcp.services.protocol_survival import finalize_mission_wire_fields
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


_EXECUTION_MODE_TO_TOOL = EXECUTION_MODE_TO_TOOL

_CHAIN_WORKER_STAGING_BLOCK_MESSAGE = (
    "Your CHAIN ORCHESTRATOR is still STAGING this project -- there is no "
    "'Implement' button and no human gate in chain mode. Do NOT wait for a "
    "human. Your gate opens automatically the moment the orchestrator ends "
    "staging; call get_job_mission again then (and periodically until) to "
    "receive your mission."
)


class MissionService:

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

                if job.project_id:
                    project, gate_response = await self._check_implementation_gate(
                        session,
                        job,
                        job_id,
                        tenant_key,
                    )
                    if gate_response is not None:
                        return gate_response

                comm_thread_id = await resolve_and_enrol(self, session, job, execution, tenant_key)

                all_project_executions, mission_lookup, current_team_state = await self._fetch_team_context(
                    session, job, execution, job_id, tenant_key
                )

                chain_execution_mode = await self._resolve_chain_execution_mode(
                    session,
                    job,
                    execution,
                    tenant_key,
                )

                is_chain_conductor = compute_is_chain_conductor(chain_execution_mode, job.project_id)

                agent_identity, identity_status, identity_source, bound_template = await self._resolve_mission_template(
                    session,
                    job,
                    execution,
                    tenant_key,
                    is_chain_conductor=is_chain_conductor,
                    chain_execution_mode=chain_execution_mode,
                )

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

                    await promote_chain_member_on_first_worker_start(self, job, tenant_key)
            if execution and status_changed and old_status is not None:
                try:
                    if self._websocket_manager:
                        await self._websocket_manager.broadcast_to_tenant(
                            tenant_key=tenant_key,
                            event_type="agent:status_changed",
                            data={
                                "job_id": job_id,
                                "project_id": str(job.project_id) if job.project_id else None,
                                "chain_conductor": bool(
                                    (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                                ),
                                "agent_id": execution.agent_id,
                                "agent_display_name": execution.agent_display_name,
                                "agent_name": execution.agent_name,
                                "old_status": old_status,
                                "status": "working",
                                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                                "duration_seconds": execution.duration_seconds,
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
                identity_status=identity_status,
                identity_source=identity_source,
                agent_profile=compose_agent_profile(bound_template),
            )
            proto = mission_response.full_protocol
            mission_response.full_protocol = await inject_conductor_chain_drive(
                self, proto, job, execution, project, tenant_key, preset=preset, detected_harness=detected_harness
            )
            mission_response.full_protocol = await compose_loop_directive(
                mission_response.full_protocol, self._get_session, tenant_key, str(execution.agent_id), self._logger
            )

            finalize_mission_wire_fields(mission_response, protocol_etag, section=section)

            return mission_response

        except (ResourceNotFoundError, ValidationError):
            raise
        except Exception as e:
            self._logger.exception("Failed to get agent mission")
            raise DatabaseError(
                message=f"Unexpected error: {e!s}", context={"job_id": job_id, "tenant_key": tenant_key}
            ) from e

    async def _get_agent_template_internal(
        self, role: str, tenant_key: str, session: AsyncSession | None = None
    ) -> AgentTemplate | None:
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
                method="service.get_agent_mission",
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
        current_team_state: list[dict] | None = None

        if not job.project_id:
            return [execution], {job.job_id: job.mission}, None

        rows = await self._repo.get_project_executions_with_jobs(session, tenant_key, job.project_id)
        all_project_executions = [row[0] for row in rows]

        mission_lookup: dict[str, str] = {}
        for _, job_row in rows:
            mission_lookup[job_row.job_id] = job_row.mission

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
    ) -> tuple[str | None, str, str | None, Any]:
        agent_identity: str | None = None
        identity_template = None
        job_id = job.job_id
        if getattr(job, "template_id", None):
            identity_template = await self._repo.get_template_by_id(session, tenant_key, job.template_id)
            if identity_template:
                agent_identity = compose_template_identity(identity_template, execution)
                self._logger.info(
                    "[AGENT_IDENTITY] Resolved identity from template at read time",
                    extra={"job_id": job_id, "template_id": job.template_id},
                )

        if job.job_type == "orchestrator" and not agent_identity and not getattr(job, "template_id", None):
            project = await self._repo.get_project_by_id(session, tenant_key, job.project_id)
            project_exec_mode = getattr(project, "execution_mode", "multi_terminal") if project else "multi_terminal"
            mode = effective_execution_mode(project_exec_mode, chain_execution_mode)
            tool = _EXECUTION_MODE_TO_TOOL.get(mode, "multi_terminal")

            role = "conductor" if is_chain_conductor else None
            agent_identity, identity_source, prompt_scope = await compose_identity_with_provenance(
                self, session, job, execution, tenant_key, project, tool=tool, role=role
            )
            self._logger.info(
                "[AGENT_IDENTITY] Composed orchestrator identity (override+harness or seed+harness)",
                extra={"job_id": job_id, "tool": tool, "prompt_scope": prompt_scope},
            )
            return agent_identity, IDENTITY_ORCHESTRATOR_DEFAULT, identity_source, None

        if not agent_identity:
            agent_identity, status = compose_unresolved_identity(job, execution)
            self._logger.warning(
                "[AGENT_IDENTITY] No template resolved -- agent runs with no role framing",
                extra={"job_id": job_id, "template_id": job.template_id, "identity_status": status},
            )
            return agent_identity, status, None, None

        return agent_identity, IDENTITY_RESOLVED, None, identity_template

    @staticmethod
    def _compute_protocol_etag(agent_identity: str | None, full_protocol: str | None) -> str:
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
        agent_profile: dict | None = None,
    ) -> MissionResponse:
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
            agent_profile=agent_profile,
        )

    async def _resolve_comm_thread_id(
        self,
        session: AsyncSession,
        job: AgentJob,
        tenant_key: str,
    ) -> str | None:
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
        return await self._orchestration.get_staging_instructions(
            job_id, tenant_key, preset_name=preset_name, detected_harness=detected_harness
        )

    async def update_agent_mission(self, job_id: str, tenant_key: str, mission: str) -> MissionUpdateResult:
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
                            "method": "service.update_agent_mission",
                            "troubleshooting": [
                                "Verify job_id is correct",
                                "Ensure tenant_key matches",
                            ],
                        },
                    )

                job.mission = mission

                execution = await self._repo.get_execution_with_job(session, tenant_key, job_id)
                if execution is not None and execution.status == "staged":
                    execution.status = "waiting"

                await session.commit()

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

                return MissionUpdateResult(
                    job_id=job_id,
                    mission_updated=True,
                    mission_length=len(mission),
                )

        except Exception as e:
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
