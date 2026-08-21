# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MissionOrchestrationService - Orchestrator instruction building.

Extracted from MissionService (Handover 0950n) to keep modules under 1000 lines.

Responsibilities:
- get_staging_instructions (public entry point)
- Building orchestrator context from database
- Staging redirect checks
- Assembling the orchestrator response dict
- Execution-mode-specific field building (CLI rules / phase assignment)
- BE-5122: CTX project self-close server-side short-circuit
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
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
from giljo_mcp.schemas.service_responses import build_next_action
from giljo_mcp.services.conductor_staging_builder import resolve_conductor_early_return
from giljo_mcp.services.execution_mode_gate import (
    effective_execution_mode,
    execution_mode_not_selected_message,
    execution_mode_selected,
)
from giljo_mcp.services.mission_orchestration_builders import (
    attach_protocol_and_identity,
    build_category_metadata,
    build_execution_mode_fields,
    build_orchestrator_identity_block,
    check_staging_redirect,
    is_chain_member,
    maybe_build_ctx_self_close_directive,
)
from giljo_mcp.services.protocol_builder import _get_user_config
from giljo_mcp.services.protocol_survival import staging_orchestrator_actions
from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
from giljo_mcp.services.settings_service import resolve_checkin_cadence_safe
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


class MissionOrchestrationService:
    """
    Service for building orchestrator instructions.

    Extracted from MissionService to reduce module size.
    Handles the get_staging_instructions flow end-to-end.
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
        self._repo = MissionRepository()
        # BE-6165c: the sequence driver (chain role resolution) lives in its own
        # module; shares the test session so injected-session tests stay isolated.
        self._chain = SequenceChainContextResolver(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=websocket_manager,
            test_session=test_session,
        )

    def _get_session(self, tenant_key: str | None = None):
        """
        Get a session, preferring an injected test session when provided.
        This keeps service methods compatible with test transaction fixtures.
        """
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
        """BE-9073: back-compat shim — logic lives in mission_orchestration_builders.build_execution_mode_fields."""
        return build_execution_mode_fields(execution_mode, templates, job_id, resolved_harness=resolved_harness)

    async def get_staging_instructions(
        self, job_id: str, tenant_key: str, preset_name: str | None = None, detected_harness: str | None = None
    ) -> dict[str, Any]:
        """
        Fetch orchestrator mission with framing-based context instructions (Handover 0350b).

        Returns a lean response (~500 tokens) with:
        - identity: Orchestrator/project identifiers
        - project_description_inline: Description + mission (always inline)
        - orchestrator_protocol: CH2 contains inline get_context() calls (Handover 0823)

        CH2 protocol now contains explicit, mandatory get_context() calls.
        Agents cannot skip categories. User depth settings control what comes back.

        BE-8003f (D2 activation): ``preset_name`` (a harness token resolved at the MCP
        boundary — web_sandbox/desktop_app/chat, else None) selects the shell-less
        CH_CAPABILITY / CH_CHAIN_DRIVE ladder for a chain conductor's staging script.
        None (every CLI caller) → byte-identical to today (D1).

        BE-9035b: ``detected_harness`` (the harness token resolved from the session
        clientInfo at the MCP boundary, or None/``"generic"``) is stashed into ctx and
        applied by ``_build_orchestrator_response`` as the DETECTED-beats-declared render
        key precedence. None/generic → the declared render key stands → byte-identical.
        """
        preset = get_preset(preset_name)
        try:
            async with self._get_session(tenant_key) as session:
                ctx = await self._build_orchestrator_context(
                    session, job_id, tenant_key, preset=preset, detected_harness=detected_harness
                )

                if ctx.get("early_return"):
                    return ctx["early_return"]

                # BE-5122 review F2: server-side CTX self-close short-circuit.
                # When the derived vision_inputs_hash matches the persisted
                # consolidated_vision_hash, transition the project + execution
                # to terminal state HERE and return a STOP-shaped directive the
                # existing complete_job/_handle_staging_end handler chain
                # already recognizes. This makes the close real, not advisory.
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
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
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
        """Gather all data needed for orchestrator instructions response.

        Returns a context dict with execution, job, project, product, config, and templates.
        If a staging redirect is needed, returns {"early_return": <response_dict>}.

        BE-8003f (D2 activation): ``preset`` (resolved harness Platform, or None on the
        CLI path) is threaded into the conductor staging builder and stashed in the
        returned ctx so ``_build_orchestrator_response`` reaches the project-bound
        protocol builder with it.
        """
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

        # Query AgentExecution and join to AgentJob
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

        # BE-6184/BE-6186: the DEDICATED chain conductor is project-less and stages the
        # whole chain in one session. Resolving its staging payload is its own concern —
        # conductor_staging_builder.resolve_conductor_early_return owns that branch
        # entirely, and the composition is pinned by substitution in the BE-9291 suite.
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

        # NULL-state gate: an orchestrator cannot operate without a chosen
        # execution mode. Backstop — staging prompt-gen 409s on a NULL mode, so
        # this rarely fires (legacy / out-of-band rows). Returns a STOP via the
        # early_return channel before any protocol is rendered, so the NULL never
        # reaches the HO1020 render fail-safes downstream.
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

        # Handover 0830: Response gating branches on implementation_launched_at
        # BE-6206 (§14, CHAIN_ARCHITECTURE.md): a chain SUB-ORCHESTRATOR (project-bound
        # member of an active run) has NO per-project gate — its staging-complete redirect
        # must point it straight at get_job_mission (one ungated call returns the impl
        # protocol), not "click Implement" and not a sleep-poll on a gate that no longer
        # exists. The project-less conductor never reaches get_staging_instructions for a
        # project, and a solo project (no active run) keeps the original wording byte-identical.
        is_chain_member = await self._is_chain_member(session, str(project.id), tenant_key)
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

        # CE-OPT-001: Build category_metadata with Modified timestamps
        category_metadata = await self._build_category_metadata(
            session=session,
            product=product,
            tenant_key=tenant_key,
        )

        # BE-5008: Read integration toggles from DB Settings
        integrations = {}
        try:
            from giljo_mcp.services.settings_service import SettingsService

            settings_svc = SettingsService(session, tenant_key)
            integrations = await settings_svc.get_settings("integrations")
        except Exception as _exc:  # noqa: BLE001
            logger.warning("[INTEGRATIONS] Failed to read settings from DB")

        # SEC-0005b: orchestrator override; imported locally to avoid api.app_state's
        # import-time side effects. BE-9385d: the STAGING identity, on the product ->
        # tenant -> seed ladder; get_job_mission walks it for the implementation one.
        orchestrator_override = None
        try:
            from giljo_mcp.system_prompts.service import read_orchestrator_override

            pid = str(product.id) if product is not None else None
            orchestrator_override = await read_orchestrator_override(
                db_manager=self.db_manager, tenant_key=tenant_key, product_id=pid, session=session
            )
        except Exception as _exc:  # noqa: BLE001
            logger.warning("[SEC-0005b] Failed to read orchestrator prompt override")

        # BE-5122: CTX self-close hook. Resolve project_type abbreviation up
        # front so the response builder can decide whether the orchestrator
        # should self-close (vision inputs already match the persisted
        # consolidated hash) without re-querying the session.
        project_type_abbreviation: str | None = None
        if project.project_type_id:
            tt_result = await session.execute(
                select(TaxonomyType.abbreviation).where(TaxonomyType.id == project.project_type_id)
            )
            project_type_abbreviation = tt_result.scalar_one_or_none()

        # BE-6165c: resolve chain role INSIDE the async context builder (session is
        # available here) rather than inside the SYNC _build_orchestrator_response.
        # _build_orchestrator_response reads ctx["conductor_agent_id"] and forwards
        # it to _build_orchestrator_protocol; ctx["chain_ctx"] is available for the
        # step-d chapter authors (CH_CHAIN_STAGING / CH_CHAIN_DRIVE).
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
            "orchestrator_prompt_override": getattr(orchestrator_override, "content", None),
            # FE-9408: the resolved rung + saved date now travel WITH that content, so
            # staging can name where this orchestrator's persona came from. None (a
            # failed read) means what the seed fallback already means: built-in default.
            "orchestrator_override": orchestrator_override,
            "project_type_abbreviation": project_type_abbreviation,
            "chain_ctx": chain_ctx,
            "conductor_agent_id": conductor_agent_id,
            "preset": preset,
            "detected_harness": detected_harness,
            # FE-9296b: CH6 seed for the sync builder. Never raises; None -> column fallback.
            "checkin_cadence_minutes": await resolve_checkin_cadence_safe(session, tenant_key, project),
        }

    async def _build_category_metadata(
        self,
        session: AsyncSession,
        product: Any | None,
        tenant_key: str,
    ) -> dict[str, dict]:
        """BE-9073: back-compat shim — logic lives in mission_orchestration_builders.build_category_metadata."""
        return await build_category_metadata(session, product, tenant_key, self._repo)

    @staticmethod
    def _maybe_build_ctx_self_close_directive(ctx: dict[str, Any]) -> dict[str, Any] | None:
        """BE-9073: back-compat shim — logic lives in mission_orchestration_builders.maybe_build_ctx_self_close_directive."""
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
        """Server-side CTX self-close: transition project + execution to terminal.

        BE-5122 review F2. Marks the project COMPLETED and the orchestrator's
        AgentExecution complete in the same session before returning a
        STOP-shaped staging_directive. The shape matches CE-0026 / complete_job
        so the existing orchestrator agent's STOP handler (chapters_startup.py
        + staging_prompt_builder.py) exits without spawning agents.
        """
        project = ctx["project"]
        execution = ctx["execution"]
        now = datetime.now(UTC)

        project.status = ProjectStatus.COMPLETED
        project.completed_at = now
        project.updated_at = now
        project.closeout_executed_at = now
        project.orchestrator_summary = directive.get("closeout_note", "hash already fresh at project launch")

        if execution is not None:
            execution.status = "complete"
            execution.completed_at = now
            execution.progress = 100
            execution.result = {
                "summary": directive.get("closeout_note", "hash already fresh at project launch"),
                "ctx_self_close": True,
                "vision_inputs_hash": directive.get("vision_inputs_hash"),
                "consolidated_vision_hash": directive.get("consolidated_vision_hash"),
            }

        await session.flush()

        # BE-6181: a CTX self-close also marks the project completed (closeout_
        # executed_at stamped above). If this project is a chain member, propagate
        # the terminal "completed" status to its active run so the conductor guard
        # accounts for it. Solo -> no-op. Best-effort: never fails the self-close.
        from giljo_mcp.services.project_helpers import mark_chain_member_status

        await mark_chain_member_status(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            project_id=str(project.id),
            tenant_key=tenant_key,
            status="completed",
            test_session=self._test_session,
            websocket_manager=self._websocket_manager,
        )

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

    async def _is_chain_member(self, session: AsyncSession, project_id: str, tenant_key: str) -> bool:
        """BE-9073: back-compat shim — logic lives in mission_orchestration_builders.is_chain_member."""
        return await is_chain_member(
            session, project_id, tenant_key, db_manager=self.db_manager, tenant_manager=self.tenant_manager
        )

    @staticmethod
    def _check_staging_redirect(project: Any, job_id: str, *, is_chain_member: bool = False) -> dict[str, Any] | None:
        """BE-9073: back-compat shim — logic lives in mission_orchestration_builders.check_staging_redirect."""
        return check_staging_redirect(project, job_id, is_chain_member=is_chain_member)

    # CE-0031 Task 1: verification roles forbidden during staging.
    # Keyed on AgentTemplate.role (not name) so it survives template renames.
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
        """BE-9073: back-compat shim — logic lives in mission_orchestration_builders.attach_protocol_and_identity."""
        attach_protocol_and_identity(
            response, ctx=ctx, protocol_tool=protocol_tool, chain_ctx=chain_ctx, build_kwargs=build_kwargs
        )

    def _build_orchestrator_response(self, ctx: dict[str, Any], job_id: str, tenant_key: str) -> dict[str, Any]:
        """Assemble the orchestrator instructions response from gathered context."""
        execution = ctx["execution"]
        agent_job = ctx["agent_job"]
        project = ctx["project"]
        product = ctx["product"]
        metadata = ctx["metadata"]
        field_toggles = ctx["field_toggles"]
        depth_config = ctx["depth_config"]
        templates = ctx["templates"]

        # CE-0031 Task 1: phase-aware agent_templates filter.
        # Staging-phase orchestrators must not spawn verification agents
        # (tester, reviewer) — the protocol forbids it and the templates list
        # was a footgun. We filter on execution.project_phase rather than
        # project.staging_status because those values can diverge (the project
        # may have been re-opened while this exec was staged).
        phase = getattr(execution, "project_phase", "implementation")
        if phase == "staging":
            visible_templates = [t for t in templates if t.role not in self._STAGING_FORBIDDEN_ROLES]
            phase_filter_note = (
                "Filtered to deliverable agents only because you are in the staging phase. "
                "Verification agents (tester, reviewer) become available in the implementation phase, "
                "after deliverable agents complete and produce real artifacts to verify."
            )
        else:
            visible_templates = list(templates)
            phase_filter_note = None

        template_list = [
            {"name": t.name, "role": t.role, "description": t.description or ""} for t in visible_templates
        ]

        project_path = None
        if product is not None:
            project_path = getattr(product, "project_path", None)

        # Handover 0408 / BE-5008: Read integration toggles from ctx (loaded in _build_orchestrator_context)
        integrations = ctx.get("integrations", {})
        include_serena = integrations.get("serena_mcp", {}).get("use_in_prompts", False)
        git_integration_enabled = integrations.get("git_integration", {}).get("enabled", False)

        response: dict[str, Any] = {
            "identity": build_orchestrator_identity_block(ctx, job_id=job_id, tenant_key=tenant_key),
            # BE-9083a: live phase-x-role checklist, early so it survives truncation.
            "next_required_actions": staging_orchestrator_actions(project, ctx.get("chain_ctx")),
            "project_description_inline": {
                "description": project.description or "",
                "mission": agent_job.mission or "",
                "project_path": project_path,
            },
            "agent_templates": template_list,
            "phase_filter_note": phase_filter_note,
            # Handover 0966: Comprehensive tool list for orchestrator awareness
            "mcp_tools_available": [
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
                "close_job",
                "resolve_reactivation",
                "write_memory_entry",
                "write_project_closeout",
                "get_agent_result",
                "create_task",
            ],
            "field_toggles": field_toggles,
            "thin_client": True,
            "architecture": "toggle_based",
            "integrations": {
                "serena_mcp_enabled": include_serena,
                "git_integration_enabled": git_integration_enabled,
            },
        }

        # INF-6007: surface role-specific Serena guidance + advertise the Serena
        # tool names when the toggle is on. Additive — integrations.serena_mcp_enabled
        # (boolean) above is preserved. This replaces the previously broken
        # template_manager string-anchor inject that never reached the orchestrator.
        if include_serena:
            from giljo_mcp.prompt_generation.serena_instructions import for_role

            response["serena_guidance"] = for_role("orchestrator", enabled=True)
            response["mcp_tools_available"].extend(
                [
                    "find_symbol",
                    "get_symbols_overview",
                    "find_referencing_symbols",
                    "search_for_pattern",
                    "replace_symbol_body",
                    "insert_after_symbol",
                    "insert_before_symbol",
                ]
            )

        # BE-9335: a chain member RUNS in the chain's mode (already-resolved chain_ctx).
        execution_mode = effective_execution_mode(
            getattr(project, "execution_mode", None), getattr(ctx.get("chain_ctx"), "execution_mode", None)
        ) or metadata.get("execution_mode", "multi_terminal")

        # BE-9035b/9035c (the precedence rule, in ONE place): for per-harness RENDERING a
        # DETECTED harness beats the declared execution_mode. effective_harness() owns
        # that rule; it consumes the session-detected harness token stashed in ctx. A
        # collapsed ``subagent`` mode has no CLI hint (-> generic unless detected); a
        # stored legacy ``*_cli`` token supplies its historical harness as the hint. This
        # single resolution now drives BOTH the cli_mode_rules spawn syntax (harness
        # facets) AND the protocol render tool — no per-site re-resolution.
        resolved_harness = effective_harness(execution_mode, {"harness": ctx.get("detected_harness")})

        # Handover 0351 / 0411a: Execution-mode-specific fields.
        # CE-0031 Task 1: pass `visible_templates` so cli_mode_rules.allowed_agent_names
        # honors the staging phase filter — the example agents must match the
        # filtered list, otherwise CLI mode would surface tester/reviewer as
        # spawn examples in staging.
        response.update(
            self._build_execution_mode_fields(
                execution_mode, visible_templates, job_id, resolved_harness=resolved_harness
            )
        )

        # Handover 0415: Add chapter-based orchestrator protocol
        cli_mode = execution_mode in SUBAGENT_EXECUTION_MODES
        # HO1020 (Wave 2 Item 2): tool_for_mode() maps the mode to its protocol
        # tool with a fail-safe default of "multi_terminal" so an unknown/unmapped
        # execution_mode falls back to the platform-neutral generic branch rather
        # than the Claude Code Task() block. Single source: PlatformRegistry.
        protocol_tool = tool_for_mode(execution_mode)
        # Only a CONCRETE detected CLI harness overrides the declared render key —
        # generic / absent detection leaves protocol_tool exactly as tool_for_mode()
        # produced it, so the no-detection render (and the golden) stays byte-identical.
        if resolved_harness in HARNESS_CLI_TOOL_TYPES:
            protocol_tool = resolved_harness
        is_staging = execution.status == "waiting"

        # Handover 0904 / FE-9296b: the CH6 seed is the resolved cadence (stashed
        # in ctx by the async builder); slider-era project columns are the fallback.
        auto_checkin_enabled = getattr(project, "auto_checkin_enabled", False)
        auto_checkin_interval = ctx.get("checkin_cadence_minutes") or (
            getattr(project, "auto_checkin_interval", 10) if auto_checkin_enabled else 10
        )

        # CE-OPT-001: Thread category timestamps into protocol
        category_metadata = ctx.get("category_metadata")

        # BE-6165c/d: conductor_agent_id + chain_ctx resolved in _build_orchestrator_context
        # (async, has the session) and passed through so _build_orchestrator_protocol can
        # render the chain chapters. chain_ctx=None ⇒ byte-identical solo render (Deletion Test).
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
                # BE-8003f (D2 activation): resolved harness preset (None on CLI path →
                # byte-identical). _build_orchestrator_protocol threads it to the chain builders.
                "preset": ctx.get("preset"),
                "detected_harness": ctx.get("detected_harness"),  # BE-9092: narrows CH_CHAIN_DRIVE spawn matrix
            },
        )

        # BE-5122 review F2: the CTX self-close path is handled
        # server-side in get_staging_instructions before this assembler
        # ever runs (see _apply_ctx_self_close). _build_orchestrator_response
        # only executes for projects that have real work to dispatch.

        logger.info(
            "Returning toggle-based orchestrator instructions",
            extra={
                "job_id": job_id,
                "enabled_categories": sum(1 for v in field_toggles.values() if v),
            },
        )

        return response
