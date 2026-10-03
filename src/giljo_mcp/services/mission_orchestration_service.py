# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    OrchestrationError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.platform_registry import (
    HARNESS_CLI_TOOL_TYPES,
    SUBAGENT_EXECUTION_MODES,
    Platform,
    effective_harness,
    get_preset,
    tool_for_mode,
)
from giljo_mcp.repositories.mission_repository import MissionRepository
from giljo_mcp.schemas.jsonb_validators import validate_agent_execution_result
from giljo_mcp.schemas.service_responses import build_next_action
from giljo_mcp.services.conductor_staging_builder import resolve_conductor_early_return
from giljo_mcp.services.execution_mode_gate import (
    effective_execution_mode,
    execution_mode_not_selected_message,
    execution_mode_selected,
)
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.mission_orchestration_builders import (
    NO_AGENTS_ASSIGNED_NOTE,
    STAGING_FILTER_NOTE,
    attach_protocol_and_identity,
    build_category_metadata,
    build_execution_mode_fields,
    build_orchestrator_identity_block,
    check_staging_redirect,
    maybe_build_ctx_self_close_directive,
)
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
from giljo_mcp.services.protocol_builder import _get_user_config
from giljo_mcp.services.protocol_survival import staging_orchestrator_actions
from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
from giljo_mcp.services.sequence_run_service import active_chain_run, broadcast_deferred_sequence_updates
from giljo_mcp.services.settings_service import resolve_checkin_cadence_safe
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


ORCHESTRATOR_AVAILABLE_TOOLS: tuple[str, ...] = (
    "health_check",
    "get_context",
    "spawn_job",
    "get_job_mission",
    "post_to_thread",
    "get_thread_history",
    "report_progress",
    "set_agent_status",
    "get_workflow_status",
    "update_project_mission",
    "update_job_mission",
    "complete_job",
    "finalize_job",
    "resume_or_dismiss_job",
    "write_memory_entry",
    "write_project_closeout",
    "get_agent_result",
    "create_task",
)


class MissionOrchestrationService:

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
        self._repo = MissionRepository()
        self._chain = SequenceChainContextResolver(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=websocket_manager,
            test_session=test_session,
        )

    def _get_session(self, tenant_key: str | None = None):
        if self._test_session is not None:

            @asynccontextmanager
            async def _test_session_wrapper():
                if tenant_key:
                    self._test_session.info["tenant_key"] = tenant_key
                yield self._test_session

            return _test_session_wrapper()

        if tenant_key:

            @asynccontextmanager
            async def _tenant_session_wrapper():
                async with self.db_manager.get_session_async() as session:
                    session.info["tenant_key"] = tenant_key
                    yield session

            return _tenant_session_wrapper()
        return self.db_manager.get_session_async()

    def _build_execution_mode_fields(
        self,
        execution_mode: str,
        templates: list,
        job_id: str,
        resolved_harness: str | None = None,
    ) -> dict[str, Any]:
        return build_execution_mode_fields(execution_mode, templates, job_id, resolved_harness=resolved_harness)

    async def get_staging_instructions(
        self, job_id: str, tenant_key: str, preset_name: str | None = None, detected_harness: str | None = None
    ) -> dict[str, Any]:
        preset = get_preset(preset_name)
        try:
            async with self._get_session(tenant_key) as session:
                ctx = await self._build_orchestrator_context(
                    session, job_id, tenant_key, preset=preset, detected_harness=detected_harness
                )

                if ctx.get("early_return"):
                    return ctx["early_return"]

                directive = self._maybe_build_ctx_self_close_directive(ctx)
                if directive is not None:
                    return await self._apply_ctx_self_close(
                        session=session,
                        ctx=ctx,
                        directive=directive,
                        job_id=job_id,
                        tenant_key=tenant_key,
                    )

                return self._build_orchestrator_response(ctx, job_id, tenant_key)

        except (ValidationError, ResourceNotFoundError):
            raise
        except Exception as e:
            logger.exception("Failed to get orchestrator instructions")
            raise OrchestrationError(
                message="Failed to get orchestrator instructions",
                error_code="INTERNAL_ERROR",
                context={"job_id": job_id, "error": str(e)},
            ) from e

    async def _build_orchestrator_context(
        self,
        session: AsyncSession,
        job_id: str,
        tenant_key: str,
        preset: Platform | None = None,
        detected_harness: str | None = None,
    ) -> dict[str, Any]:
        if not job_id or not job_id.strip():
            raise ValidationError(
                message="Job ID is required",
                error_code="VALIDATION_ERROR",
                context={"method": "get_staging_instructions"},
            )

        if not tenant_key or not tenant_key.strip():
            raise ValidationError(
                message="Tenant key is required",
                error_code="VALIDATION_ERROR",
                context={"method": "get_staging_instructions"},
            )

        execution = await self._repo.get_execution_with_job(session, tenant_key, job_id)

        if not execution:
            raise ResourceNotFoundError(
                message=(
                    f"No execution found for job {job_id} in this tenant. The job_id may be "
                    "mistyped, belong to a different tenant, or never have been spawned."
                ),
                error_code="NOT_FOUND",
                context={
                    "job_id": job_id,
                    "method": "get_staging_instructions",
                    "reason": "unknown_job_id",
                    "next_action": build_next_action(
                        tool="diagnose_project_state",
                        why=(
                            "job_id not found in this tenant. If you know which project owns "
                            "it, call diagnose_project_state(project_id=...) to see its agents' "
                            "current job_ids and statuses."
                        ),
                    ),
                },
            )

        agent_job = execution.job
        if not agent_job:
            raise ResourceNotFoundError(
                message=f"Execution {execution.id} for job {job_id} has no linked agent job row (data integrity gap).",
                error_code="NOT_FOUND",
                context={
                    "job_id": job_id,
                    "method": "get_staging_instructions",
                    "reason": "orphaned_execution",
                    "next_action": build_next_action(
                        tool="diagnose_project_state",
                        why=(
                            "The execution exists but its agent job row is missing. If you know "
                            "which project owns it, call diagnose_project_state(project_id=...) "
                            "to see the recovery step."
                        ),
                    ),
                },
            )

        if agent_job.job_type != "orchestrator":
            raise ValidationError(
                message=(
                    f"Job {job_id} exists but is job_type='{agent_job.job_type}', not 'orchestrator'. "
                    "get_staging_instructions is only valid for the orchestrator's own job_id."
                ),
                error_code="VALIDATION_ERROR",
                context={
                    "job_id": job_id,
                    "job_type": agent_job.job_type,
                    "method": "get_staging_instructions",
                    "reason": "wrong_job_type",
                    "next_action": build_next_action(
                        tool="diagnose_project_state",
                        args_hint={"project_id": str(agent_job.project_id)} if agent_job.project_id else None,
                        why=(
                            "Call get_staging_instructions with the ORCHESTRATOR job_id for this "
                            "project, not a worker job_id. diagnose_project_state(project_id=...) "
                            "lists current agents and their job_ids."
                        ),
                    ),
                },
            )

        if agent_job.project_id is None:
            return {
                "early_return": await resolve_conductor_early_return(
                    session,
                    chain=self._chain,
                    repo=self._repo,
                    execution=execution,
                    job_id=job_id,
                    tenant_key=tenant_key,
                    preset=preset,
                )
            }

        project = await self._repo.get_project_by_id(session, tenant_key, agent_job.project_id)

        if not project:
            raise ResourceNotFoundError(
                message=f"Project {agent_job.project_id} not found in this tenant (referenced by job {job_id}).",
                error_code="NOT_FOUND",
                context={
                    "project_id": str(agent_job.project_id),
                    "job_id": job_id,
                    "method": "get_staging_instructions",
                    "reason": "unknown_project_id",
                    "next_action": build_next_action(
                        tool="diagnose_project_state",
                        args_hint={"project_id": str(agent_job.project_id)},
                        why="The job's project_id no longer resolves. Call diagnose_project_state to inspect it.",
                    ),
                },
            )

        if not execution_mode_selected(project):
            return {
                "early_return": {
                    "status": "BLOCKED",
                    "action": "STOP",
                    "redirect": None,
                    "identity": {
                        "job_id": job_id,
                        "project_id": str(project.id),
                        "project_name": project.name,
                    },
                    "message": execution_mode_not_selected_message(project.name),
                    "thin_client": True,
                }
            }

        is_chain_member = await active_chain_run(session, project.id, tenant_key) is not None
        early = self._check_staging_redirect(project, job_id, is_chain_member=is_chain_member)
        if early:
            return {"early_return": early}

        product = None
        if project.product_id:
            product = await self._repo.get_project_with_vision_docs(session, tenant_key, project.product_id)

        metadata = agent_job.job_metadata or {}
        user_id = metadata.get("user_id")

        if user_id:
            user_config = await _get_user_config(user_id, tenant_key, session)
            field_toggles = user_config["field_toggles"]
            depth_config = user_config["depth_config"]
            logger.info(
                "[USER_CONFIG] Fetched fresh user config for OrchestrationService",
                extra={"job_id": job_id, "user_id": user_id},
            )
        else:
            field_toggles = metadata.get("field_toggles", metadata.get("field_priorities", {}))
            depth_config = metadata.get("depth_config", {})
            logger.debug("[USER_CONFIG] No user_id, using frozen job_metadata config", extra={"job_id": job_id})

        templates = await self._repo.get_active_templates(session, tenant_key, product_id=project.product_id)

        category_metadata = await self._build_category_metadata(
            session=session,
            product=product,
            tenant_key=tenant_key,
        )

        integrations, headless_launch = {}, False
        try:
            from giljo_mcp.services.settings_service import SettingsService

            settings_svc = SettingsService(session, tenant_key)
            integrations = await settings_svc.get_settings("integrations")
            headless_launch = bool(await settings_svc.get_setting_value("security", "allow_headless_launch"))
        except Exception as _exc:  # noqa: BLE001
            logger.warning("[INTEGRATIONS] Failed to read settings from DB")

        orchestrator_override = None
        try:
            from giljo_mcp.system_prompts.service import read_orchestrator_override

            pid = str(product.id) if product is not None else None
            orchestrator_override = await read_orchestrator_override(
                db_manager=self.db_manager, tenant_key=tenant_key, product_id=pid, session=session
            )
        except Exception as _exc:  # noqa: BLE001
            logger.warning("[SEC-0005b] Failed to read orchestrator prompt override")

        project_type_abbreviation: str | None = None
        if project.project_type_id:
            tt_result = await session.execute(
                select(TaxonomyType.abbreviation).where(TaxonomyType.id == project.project_type_id)
            )
            project_type_abbreviation = tt_result.scalar_one_or_none()

        is_staging = execution.status == "waiting"
        chain_ctx = await self._chain.resolve(
            session,
            project_id=str(project.id),
            tenant_key=tenant_key,
            orchestrator_agent_id=str(execution.agent_id),
            is_staging=is_staging,
        )
        conductor_agent_id: str | None = (
            chain_ctx.conductor_agent_id if (chain_ctx is not None and chain_ctx.role == "conductor") else None
        )

        return {
            "execution": execution,
            "agent_job": agent_job,
            "project": project,
            "product": product,
            "metadata": metadata,
            "field_toggles": field_toggles,
            "depth_config": depth_config,
            "templates": templates,
            "category_metadata": category_metadata,
            "integrations": integrations,
            "headless_launch": headless_launch,
            "orchestrator_prompt_override": getattr(orchestrator_override, "content", None),
            "orchestrator_override": orchestrator_override,
            "project_type_abbreviation": project_type_abbreviation,
            "chain_ctx": chain_ctx,
            "conductor_agent_id": conductor_agent_id,
            "preset": preset,
            "detected_harness": detected_harness,
            "checkin_cadence_minutes": await resolve_checkin_cadence_safe(session, tenant_key, project),
        }

    async def _build_category_metadata(
        self,
        session: AsyncSession,
        product: Any | None,
        tenant_key: str,
    ) -> dict[str, dict]:
        return await build_category_metadata(session, product, tenant_key, self._repo)

    @staticmethod
    def _maybe_build_ctx_self_close_directive(ctx: dict[str, Any]) -> dict[str, Any] | None:
        return maybe_build_ctx_self_close_directive(ctx)

    async def _apply_ctx_self_close(
        self,
        *,
        session: AsyncSession,
        ctx: dict[str, Any],
        directive: dict[str, Any],
        job_id: str,
        tenant_key: str,
    ) -> dict[str, Any]:
        project = ctx["project"]
        summary = directive.get("closeout_note", "hash already fresh at project launch")
        ProjectLifecycleService.stamp_completed(project, summary)

        result = validate_agent_execution_result(
            {
                "summary": summary,
                "ctx_self_close": True,
                "vision_inputs_hash": directive.get("vision_inputs_hash"),
                "consolidated_vision_hash": directive.get("consolidated_vision_hash"),
            }
        )
        completion = JobCompletionService(self.db_manager, self.tenant_manager)
        await completion.apply_completion(session, ctx["agent_job"], ctx["execution"], result, tenant_key)
        await session.flush()

        from giljo_mcp.services.project_helpers import mark_chain_member_status

        await mark_chain_member_status(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            project_id=str(project.id),
            tenant_key=tenant_key,
            status="completed",
            test_session=session,
            websocket_manager=self._websocket_manager,
        )
        await session.commit()
        await broadcast_deferred_sequence_updates(session)

        logger.info(
            "[BE-5122] CTX self-close applied server-side",
            extra={
                "job_id": job_id,
                "tenant_key": tenant_key,
                "project_id": str(project.id),
                "vision_inputs_hash": directive.get("vision_inputs_hash"),
            },
        )

        return {
            "identity": {
                "job_id": job_id,
                "project_id": str(project.id),
                "project_name": project.name,
                "tenant_key": tenant_key,
            },
            "staging_directive": {
                "status": "STAGING_SESSION_COMPLETE",
                "action": "STOP",
                "reason": "CTX_SELF_CLOSE",
                "closeout_note": directive.get("closeout_note"),
                "vision_inputs_hash": directive.get("vision_inputs_hash"),
                "consolidated_vision_hash": directive.get("consolidated_vision_hash"),
            },
            "message": (
                "Context Update aggregates are already fresh "
                "(vision_inputs_hash matches consolidated_vision_hash). "
                "Project closed server-side without spawning agents. "
                "STOP your session immediately."
            ),
            "thin_client": True,
        }

    @staticmethod
    def _check_staging_redirect(project: Any, job_id: str, *, is_chain_member: bool = False) -> dict[str, Any] | None:
        return check_staging_redirect(project, job_id, is_chain_member=is_chain_member)

    _STAGING_FORBIDDEN_ROLES: frozenset[str] = frozenset({"tester", "reviewer"})

    def _attach_protocol_and_identity(
        self,
        response: dict[str, Any],
        *,
        ctx: dict[str, Any],
        protocol_tool: str,
        chain_ctx: Any,
        build_kwargs: dict[str, Any],
    ) -> None:
        attach_protocol_and_identity(
            response, ctx=ctx, protocol_tool=protocol_tool, chain_ctx=chain_ctx, build_kwargs=build_kwargs
        )

    def _build_orchestrator_response(self, ctx: dict[str, Any], job_id: str, tenant_key: str) -> dict[str, Any]:
        execution = ctx["execution"]
        agent_job = ctx["agent_job"]
        project = ctx["project"]
        product = ctx["product"]
        metadata = ctx["metadata"]
        field_toggles = ctx["field_toggles"]
        depth_config = ctx["depth_config"]
        templates = ctx["templates"]

        phase = getattr(execution, "project_phase", "implementation")
        if phase == "staging":
            visible_templates = [t for t in templates if t.role not in self._STAGING_FORBIDDEN_ROLES]
            phase_filter_note = STAGING_FILTER_NOTE if templates else NO_AGENTS_ASSIGNED_NOTE
        else:
            visible_templates = list(templates)
            phase_filter_note = None if templates else NO_AGENTS_ASSIGNED_NOTE

        template_list = [
            {"name": t.name, "role": t.role, "description": t.description or ""} for t in visible_templates
        ]

        project_path = None
        if product is not None:
            project_path = getattr(product, "project_path", None)

        integrations = ctx.get("integrations", {})
        git_integration_enabled = integrations.get("git_integration", {}).get("enabled", False)

        response: dict[str, Any] = {
            "identity": build_orchestrator_identity_block(ctx, job_id=job_id),
            "next_required_actions": staging_orchestrator_actions(project, ctx.get("chain_ctx")),
            "project_description_inline": {
                "description": project.description or "",
                "mission": agent_job.mission or "",
                "project_path": project_path,
            },
            "agent_templates": template_list,
            "phase_filter_note": phase_filter_note,
            "mcp_tools_available": list(ORCHESTRATOR_AVAILABLE_TOOLS),
            "field_toggles": field_toggles,
            "thin_client": True,
            "architecture": "toggle_based",
            "integrations": {
                "git_integration_enabled": git_integration_enabled,
            },
        }

        execution_mode = effective_execution_mode(
            getattr(project, "execution_mode", None), getattr(ctx.get("chain_ctx"), "execution_mode", None)
        ) or metadata.get("execution_mode", "multi_terminal")

        resolved_harness = effective_harness(execution_mode, {"harness": ctx.get("detected_harness")})

        response.update(
            self._build_execution_mode_fields(
                execution_mode, visible_templates, job_id, resolved_harness=resolved_harness
            )
        )

        cli_mode = execution_mode in SUBAGENT_EXECUTION_MODES
        protocol_tool = tool_for_mode(execution_mode)
        if resolved_harness in HARNESS_CLI_TOOL_TYPES:
            protocol_tool = resolved_harness
        is_staging = execution.status == "waiting"

        auto_checkin_enabled = getattr(project, "auto_checkin_enabled", False)
        auto_checkin_interval = ctx.get("checkin_cadence_minutes") or (
            getattr(project, "auto_checkin_interval", 10) if auto_checkin_enabled else 10
        )

        category_metadata = ctx.get("category_metadata")

        conductor_agent_id = ctx.get("conductor_agent_id")
        chain_ctx = ctx.get("chain_ctx")
        self._attach_protocol_and_identity(
            response,
            ctx=ctx,
            protocol_tool=protocol_tool,
            chain_ctx=chain_ctx,
            build_kwargs={
                "cli_mode": cli_mode,
                "project_id": str(project.id),
                "orchestrator_id": job_id,
                "tenant_key": tenant_key,
                "include_implementation_reference": not is_staging,
                "field_toggles": field_toggles,
                "depth_config": depth_config,
                "product_id": str(product.id) if product else None,
                "tool": protocol_tool,
                "auto_checkin_enabled": auto_checkin_enabled,
                "auto_checkin_interval": auto_checkin_interval,
                "git_integration_enabled": git_integration_enabled,
                "category_metadata": category_metadata,
                "conductor_agent_id": conductor_agent_id,
                "chain_ctx": chain_ctx,
                "preset": ctx.get("preset"),
                "detected_harness": ctx.get("detected_harness"),
                "headless_launch": bool(ctx.get("headless_launch", False)),
            },
        )


        logger.info(
            "Returning toggle-based orchestrator instructions",
            extra={
                "job_id": job_id,
                "enabled_categories": sum(1 for v in field_toggles.values() if v),
            },
        )

        return response
