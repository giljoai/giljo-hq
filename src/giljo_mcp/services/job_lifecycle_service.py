# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    AlreadyExistsError,
    DatabaseError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import AgentExecution, AgentJob
from giljo_mcp.prompts.spawn_prompt import _MULTI_TERMINAL_PROMPT_POINTER, build_agent_prompt, launch_gate_passed
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.schemas.jsonb_validators import validate_agent_job_metadata
from giljo_mcp.schemas.service_responses import SpawnResult
from giljo_mcp.services._predecessor_context import build_predecessor_context
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.dto import BroadcastAgentCreatedContext
from giljo_mcp.services.execution_mode_gate import require_execution_mode
from giljo_mcp.services.protocol_survival import build_spawn_footer
from giljo_mcp.services.sequence_chain_context import renders_multi_terminal
from giljo_mcp.system_roles import ORCHESTRATOR_AGENT_NAME
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.identity import validate_agent_display_name
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

IMMUTABLE_PROJECT_STATUSES: frozenset[str] = frozenset({"completed", "cancelled"})


class JobLifecycleService:

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

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def spawn_job(
        self,
        agent_display_name: str,
        agent_name: str,
        project_id: str,
        tenant_key: str,
        mission: str | None = None,
        parent_job_id: str | None = None,
        context_chunks: list[str] | None = None,
        phase: int | None = None,
        predecessor_job_id: str | None = None,
        inline_seed: bool = False,
    ) -> SpawnResult:
        if phase is not None and phase > 1 and (predecessor_job_id is None or not str(predecessor_job_id).strip()):
            raise ValidationError(
                message=(
                    "phase > 1 jobs require a non-empty predecessor_job_id. "
                    "Pass the job_id of the prior-phase agent whose output this "
                    "job consumes."
                ),
                context={
                    "phase": phase,
                    "predecessor_job_id": predecessor_job_id,
                    "project_id": project_id,
                    "agent_display_name": agent_display_name,
                },
            )

        try:
            repo = AgentJobRepository(None)
            async with self._get_session(tenant_key) as session:
                project = await repo.get_project_by_id(session, tenant_key, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found", context={"project_id": project_id, "tenant_key": tenant_key}
                    )

                if project.status in IMMUTABLE_PROJECT_STATUSES:
                    raise ProjectStateError(
                        message=f"Cannot modify project in '{project.status.value}' status. "
                        "Only inactive and active projects can be updated.",
                        context={"project_id": project_id, "status": project.status.value},
                    )

                reuse = await self._reuse_existing_chain_orchestrator(
                    session, agent_display_name, project_id, tenant_key, inline_seed=inline_seed
                )
                if reuse is not None:
                    return reuse

                require_execution_mode(project, project_id, tenant_key)

                if predecessor_job_id:
                    project_exec_mode = getattr(project, "execution_mode", "multi_terminal") or "multi_terminal"
                    mission = await build_predecessor_context(
                        session,
                        predecessor_job_id,
                        tenant_key,
                        project_id,
                        mission,
                        agent_display_name,
                        execution_mode=project_exec_mode,
                        logger=self._logger,
                    )

                agent_display_name = await self._validate_spawn_agent(
                    session, agent_display_name, agent_name, tenant_key, project, parent_job_id
                )

                job_id = str(uuid4())
                agent_id = str(uuid4())

                metadata_dict = {
                    "created_via": "thin_client_spawn",
                    "created_at": datetime.now(UTC).isoformat(),
                    "thin_client": True,
                }
                if context_chunks:
                    metadata_dict["context_chunks"] = context_chunks


                mission, resolved_template_id, spawn_template = await self._resolve_spawn_template(
                    session, project, agent_name, mission, tenant_key, agent_display_name
                )

                is_staged = not (mission and mission.strip())

                _, agent_execution = await self._create_job_and_execution_records(
                    session=session,
                    job_id=job_id,
                    agent_id=agent_id,
                    project=project,
                    project_id=project_id,
                    tenant_key=tenant_key,
                    mission=mission,
                    agent_display_name=agent_display_name,
                    agent_name=agent_name,
                    parent_job_id=parent_job_id,
                    phase=phase,
                    resolved_template_id=resolved_template_id,
                    metadata_dict=metadata_dict,
                    is_staged=is_staged,
                )

                await session.commit()

                thin_agent_prompt, agent_prompt_location = await self._resolve_thin_prompt(
                    session,
                    project=project,
                    project_id=project_id,
                    tenant_key=tenant_key,
                    agent_name=agent_name,
                    agent_display_name=agent_display_name,
                    job_id=job_id,
                    inline_seed=inline_seed,
                    template=spawn_template,
                )
                created_at = datetime.now(UTC)

                await self._broadcast_agent_created(
                    BroadcastAgentCreatedContext(
                        tenant_key=tenant_key,
                        project_id=project_id,
                        agent_execution=agent_execution,
                        agent_id=agent_id,
                        job_id=job_id,
                        agent_display_name=agent_display_name,
                        agent_name=agent_name,
                        mission=mission,
                        phase=phase,
                        created_at=created_at,
                        product_id=project.product_id,
                    ),
                )

                return SpawnResult(
                    job_id=job_id,
                    agent_id=agent_id,
                    execution_id=agent_execution.id,
                    agent_display_name=agent_display_name,
                    agent_prompt=thin_agent_prompt,
                    mission_stored=True,
                    thin_client=True,
                    thin_client_note=[
                        "Mission stored server-side, keyed by job_id",
                        "Agent calls get_job_mission(job_id) -> returns mission + full_protocol",
                        "Enables: fresh sessions, postponed launches, orchestrator handover",
                    ],
                    predecessor_job_id=predecessor_job_id,
                    phase=phase,
                    agent_prompt_location=agent_prompt_location,
                    lifecycle_footer=build_spawn_footer(
                        phase=(
                            "implementation"
                            if getattr(project, "implementation_launched_at", None) is not None
                            else "staging"
                        )
                    ),
                )

        except (ResourceNotFoundError, AlreadyExistsError, ValidationError, ProjectStateError):
            raise
        except Exception as e:
            self._logger.error(f"[ERROR] Failed to spawn agent job: {e}", exc_info=True)
            raise DatabaseError(
                message=f"Failed to spawn agent: {e!s}",
                context={"project_id": project_id, "agent_display_name": agent_display_name},
            ) from e

    async def _reuse_existing_chain_orchestrator(
        self,
        session: AsyncSession,
        agent_display_name: str,
        project_id: str,
        tenant_key: str,
        inline_seed: bool = False,
    ) -> SpawnResult | None:
        if agent_display_name != "orchestrator":
            return None

        from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository

        lifecycle_repo = ProjectLifecycleRepository()
        existing = await lifecycle_repo.find_existing_orchestrator(session, tenant_key, project_id)
        if existing is None:
            return None

        from giljo_mcp.services.sequence_run_service import active_chain_run

        if await active_chain_run(session, project_id, tenant_key) is None:
            return None

        project = await AgentJobRepository(None).get_project_by_id(session, tenant_key, project_id)
        thin_agent_prompt, agent_prompt_location = await self._resolve_thin_prompt(
            session,
            project=project,
            project_id=project_id,
            tenant_key=tenant_key,
            agent_name=existing.agent_name,
            agent_display_name=existing.agent_display_name,
            job_id=existing.job_id,
            inline_seed=inline_seed,
        )

        self._logger.info(
            "chain sub-orch double-spawn prevented -- reusing existing orchestrator job %s for project %s",
            existing.job_id,
            sanitize(project_id),
        )

        return SpawnResult(
            job_id=existing.job_id,
            agent_id=existing.agent_id,
            execution_id=existing.id,
            agent_display_name=existing.agent_display_name,
            agent_prompt=thin_agent_prompt,
            mission_stored=True,
            thin_client=True,
            thin_client_note=[
                "Sub-orchestrator already minted at chain staging -- reused, not duplicated",
                "Agent calls get_job_mission(job_id) -> returns mission + full_protocol",
            ],
            predecessor_job_id=None,
            phase=None,
            agent_prompt_location=agent_prompt_location,
            lifecycle_footer=build_spawn_footer(
                phase=(
                    "implementation" if getattr(project, "implementation_launched_at", None) is not None else "staging"
                )
            ),
        )

    async def _resolve_display_name(
        self,
        session: AsyncSession,
        agent_display_name: str,
        tenant_key: str,
        project_id: str,
    ) -> str:
        repo = AgentCompletionRepository()
        active_names = await repo.get_active_display_names_in_project(session, tenant_key, project_id)

        if agent_display_name not in active_names:
            return agent_display_name

        for suffix in range(2, 51):
            candidate = f"{agent_display_name}-{suffix}"
            if candidate not in active_names:
                self._logger.info(
                    "Auto-suffixed display name '%s' -> '%s' (collision in project %s)",
                    sanitize(agent_display_name),
                    sanitize(candidate),
                    sanitize(project_id),
                )
                return candidate

        raise ValidationError(
            message=(
                f"Display name suffix cap exceeded for '{agent_display_name}' "
                f"in project {project_id}. All suffixes 2-50 are taken."
            ),
            context={
                "agent_display_name": agent_display_name,
                "project_id": project_id,
                "tenant_key": tenant_key,
                "max_suffix": 50,
            },
        )

    async def _validate_spawn_agent(
        self,
        session: AsyncSession,
        agent_display_name: str,
        agent_name: str,
        tenant_key: str,
        project: Any,
        parent_job_id: str | None,
    ) -> str:
        agent_display_name = validate_agent_display_name(agent_display_name)
        repo = AgentCompletionRepository()
        is_orchestrator = agent_display_name == "orchestrator"
        project_id = project.id

        if not (is_orchestrator and agent_name == ORCHESTRATOR_AGENT_NAME):
            valid_agent_names = await repo.get_active_template_names(session, tenant_key, product_id=project.product_id)

            if agent_name not in valid_agent_names:
                if not valid_agent_names:
                    message = (
                        f"No agents assigned for this product, use your harness default (requested '{agent_name}')."
                    )
                else:
                    message = f"Invalid agent_name '{agent_name}'. Must be one of: {valid_agent_names}"
                raise ValidationError(
                    message=message,
                    context={
                        "agent_name": agent_name,
                        "agent_display_name": agent_display_name,
                        "valid_names": valid_agent_names,
                        "tenant_key": tenant_key,
                    },
                )

        if not is_orchestrator:
            return await self._resolve_display_name(session, agent_display_name, tenant_key, project_id)

        existing_orchestrator = await repo.find_active_orchestrator_in_project(session, tenant_key, project_id)

        if existing_orchestrator:
            if parent_job_id and parent_job_id == existing_orchestrator.agent_id:
                self._logger.info(
                    "Handover: Allowing successor spawn from orchestrator %s",
                    sanitize(parent_job_id),
                )
            else:
                raise AlreadyExistsError(
                    message=(f"Orchestrator already exists for project with status '{existing_orchestrator.status}'"),
                    context={
                        "project_id": project_id,
                        "tenant_key": tenant_key,
                        "existing_agent_id": existing_orchestrator.agent_id,
                        "existing_status": existing_orchestrator.status,
                    },
                )

        return agent_display_name

    async def _resolve_spawn_template(
        self,
        session: AsyncSession,
        project: Any,
        agent_name: str,
        mission: str,
        tenant_key: str,
        agent_display_name: str,
    ) -> tuple[str, str | None, Any]:
        resolved_template_id = None
        repo = AgentCompletionRepository()
        template = await repo.get_template_by_name(session, tenant_key, agent_name, product_id=project.product_id)

        if template:
            resolved_template_id = template.id
            self._logger.info(
                "[TEMPLATE_RESOLVE] Captured template_id for job",
                extra={
                    "agent_name": sanitize(agent_name),
                    "template_id": template.id,
                    "execution_mode": project.execution_mode,
                },
            )
        else:
            self._logger.warning(
                "[TEMPLATE_RESOLVE] No template resolved for agent_name=%s -- job spawns without an identity",
                sanitize(agent_name),
                extra={
                    "agent_name": sanitize(agent_name),
                    "agent_display_name": sanitize(agent_display_name),
                    "execution_mode": project.execution_mode,
                },
            )

        return mission, resolved_template_id, template

    async def _resolve_thin_prompt(
        self,
        session: AsyncSession,
        *,
        project: Any,
        project_id: str,
        tenant_key: str,
        agent_name: str,
        agent_display_name: str,
        job_id: str,
        inline_seed: bool,
        template: Any = None,
    ) -> tuple[str, str]:
        mt = await renders_multi_terminal(session, project=project, project_id=project_id, tenant_key=tenant_key)
        if mt and not inline_seed:
            return _MULTI_TERMINAL_PROMPT_POINTER.format(agent_display_name=agent_display_name), "dashboard"
        prompt = self._build_agent_prompt(
            agent_name=agent_name,
            agent_display_name=agent_display_name,
            project_name=project.name,
            job_id=job_id,
            template=template,
            multi_terminal=mt,
            launched=launch_gate_passed(project),
        )
        return prompt, "inline"

    def _build_agent_prompt(
        self,
        agent_name: str,
        agent_display_name: str,
        project_name: str,
        job_id: str,
        template: Any = None,
        *,
        multi_terminal: bool = False,
        launched: bool = False,
    ) -> str:
        return build_agent_prompt(
            agent_name,
            agent_display_name,
            project_name,
            job_id,
            template,
            multi_terminal=multi_terminal,
            launched=launched,
        )

    async def _create_job_and_execution_records(
        self,
        session: AsyncSession,
        job_id: str,
        agent_id: str,
        project: Any,
        project_id: str,
        tenant_key: str,
        mission: str | None,
        agent_display_name: str,
        agent_name: str,
        parent_job_id: str | None,
        phase: int | None,
        resolved_template_id: str | None,
        metadata_dict: dict,
        is_staged: bool = False,
    ) -> tuple[AgentJob, AgentExecution]:
        execution_status = "staged" if is_staged else "waiting"
        job_mission = mission if not is_staged else None

        agent_job = AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project_id,
            mission=job_mission,
            job_type=agent_display_name,
            status="active",
            job_metadata=validate_agent_job_metadata(metadata_dict),
            phase=phase,
            template_id=resolved_template_id,
        )

        agent_execution = AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name=agent_display_name,
            agent_name=agent_name,
            status=execution_status,
            spawned_by=parent_job_id,
            started_at=datetime.now(UTC),
        )

        repo = AgentCompletionRepository()
        agent_job, agent_execution = await repo.persist_job_and_execution(
            session=session,
            agent_job=agent_job,
            agent_execution=agent_execution,
            project=project,
            is_orchestrator=(agent_display_name == "orchestrator"),
        )

        return agent_job, agent_execution

    async def _broadcast_agent_created(
        self,
        ctx: BroadcastAgentCreatedContext,
    ) -> None:
        self._logger.info(
            f"[WEBSOCKET] Broadcasting agent:created for {ctx.agent_name} ({ctx.agent_display_name}) via direct WebSocket"
        )
        try:
            if self._websocket_manager:
                await self._websocket_manager.broadcast_to_tenant(
                    tenant_key=ctx.tenant_key,
                    event_type="agent:created",
                    data={
                        "project_id": ctx.project_id,
                        "product_id": ctx.product_id,
                        "execution_id": ctx.agent_execution.id,
                        "agent_id": ctx.agent_id,
                        "job_id": ctx.job_id,
                        "agent_display_name": ctx.agent_display_name,
                        "agent_name": ctx.agent_name,
                        "status": "waiting",
                        "thin_client": True,
                        "timestamp": ctx.created_at.isoformat(),
                        "mission": ctx.mission,
                        "phase": ctx.phase,
                    },
                )
        except Exception as ws_error:
            self._logger.error(f"[WEBSOCKET ERROR] Failed to broadcast agent:created: {ws_error}", exc_info=True)
