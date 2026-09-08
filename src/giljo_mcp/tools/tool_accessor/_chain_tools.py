# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Chain (linked multi-project / sequence-run) tools mixin for ToolAccessor (BE-6221a).

``start_chain_run`` is the HEADLESS entry point the dashboard "Run Sequential"
button already has but MCP lacked: it creates the durable sequence_run + mints the
dedicated, PROJECT-LESS chain conductor by reusing ``SequenceRunService.create``
(the exact path the REST POST /api/v1/sequence-runs endpoint drives) — NO new
write path, store, schema, or migration.

Because there is no election UI for a headless caller to lean on, this mixin owns
the server-side guards the UI would otherwise enforce: every project must exist for
the tenant, be chainable (not terminal, not already in another active run),
``resolved_order`` must be a permutation of ``project_ids``, and a chain needs >= 2
distinct members. A failed guard is returned as a structured
``{"success": False, "error": <CODE>, ...}`` rejection (BE-6081 MCP-boundary
carve-out — an agent-actionable declined request, NOT a raised error). Enum/cap
violations (execution_mode, chain_mission length) raise ValidationError as usual.

Edition Scope: CE.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from giljo_mcp.domain.project_status import LIFECYCLE_FINISHED_STATUSES
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import ACCEPTED_EXECUTION_MODES, VALID_EXECUTION_MODES
from giljo_mcp.schemas.service_responses import build_next_action
from giljo_mcp.services.sequence_run_service import MAX_CHAIN_MISSION_CHARS, SequenceRunService


logger = logging.getLogger(__name__)

# MUST-FIX #4: the conductor's FIRST drive call after run-create is
# get_staging_instructions — verified against the CURRENT build:
#   * the dashboard "Run Sequential" -> Stage flow fetches the chain-staging prompt
#     (useChainLifecycle.stageChain -> api.prompts.chainStaging), whose bootstrap
#     calls get_staging_instructions(job_id=conductor_job_id) (test_be6191);
#   * a project-less conductor calling get_staging_instructions resolves the
#     conductor branch and returns CH_CAPABILITY + CH_CHAIN_STAGING (BE-6186);
#   * get_job_mission is the LATER implementation-phase drive (chain-implementation
#     prompt / Implement button), reached only after staging-end.
_CONDUCTOR_BOOTSTRAP_TOOL = "get_staging_instructions"


class ChainToolsMixin:
    """start_chain_run adapter tool. Composed into ToolAccessor (BE-6221a)."""

    async def start_chain_run(
        self,
        project_ids: list[str] | None = None,
        execution_mode: str | None = None,
        resolved_order: list[str] | None = None,
        review_policy: str = "per_card",
        chain_mission: str | None = None,
        tenant_key: str | None = None,
        action: str = "start",
        run_id: str | None = None,
        member_project_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a chain (sequence run) + its conductor, reusing the existing engine.

        Returns the serialized run plus the conductor identity and a next_action
        that bootstraps the conductor's drive, or a structured rejection dict.

        BE-9500b: ``action`` is the chain reverse gear / member-review verb, the
        same one-tool-many-actions pattern ``stage_project`` uses for its staging
        reverse gear (BE-9499b) -- no new tool registered, roster-lock untouched.
        ``action="start"`` (default) is the behavior above, unchanged.
        ``action="terminate_remaining"`` (requires ``run_id``) cancels the run via
        ``SequenceRunService.release(mode="cancel")`` -- byte-identical to the REST
        ``POST /sequence-runs/{run}/release?mode=cancel`` door, no precondition.
        ``action="mark_reviewed"`` (requires ``run_id`` + ``member_project_id``)
        durably records a member reviewed via
        ``SequenceRunService.mark_member_reviewed`` -- byte-identical to the REST
        ``POST /sequence-runs/{run}/members/{pid}/review`` door. Verified by call
        path (BE-9500b): this is NON-GATING, it never touches
        ``current_index``/``project_statuses`` -- a completed member is already
        advanced past automatically (BE-9500a). It exists so a headless conductor
        can take the one action a human takes closing the review pane, keeping the
        durable review record consistent regardless of which door drove it.
        """
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not effective_tenant_key:
            raise ValidationError(message="tenant_key is required", context={"operation": "accessor.start_chain_run"})

        if action != "start":
            return await self._chain_run_reverse_gear(
                action=action,
                run_id=run_id,
                member_project_id=member_project_id,
                tenant_key=effective_tenant_key,
            )

        if project_ids is None or execution_mode is None:
            raise ValidationError(
                message="project_ids and execution_mode are required for action='start'",
                context={"operation": "accessor.start_chain_run"},
            )

        # Tool-layer input validation: agent input is untrusted (CLAUDE.md). Type +
        # enum + length are checked BEFORE the service so a bad value is a clean 422,
        # never a 500 from a downstream DB constraint.
        self._validate_chain_inputs(project_ids, execution_mode, chain_mission)

        order = list(resolved_order) if resolved_order is not None else list(project_ids)

        rejection = await self._reject_unchainable(project_ids, order, effective_tenant_key)
        if rejection is not None:
            return rejection

        # MUST-FIX #1: inject the bound websocket_manager so create()'s
        # broadcast-on-create (BE-6221a) actually fires; without it the broadcast
        # silently no-ops and the dashboard tickboxes never light up.
        service = SequenceRunService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            websocket_manager=self._websocket_manager,
            session=self._test_session,
        )
        run = await service.create(
            project_ids=project_ids,
            resolved_order=order,
            execution_mode=execution_mode,
            review_policy=review_policy,
            tenant_key=effective_tenant_key,
        )
        if chain_mission:
            # Routed through the owning service's writer (no parallel write path);
            # the freshly created run is not ultralocked so the edit is accepted.
            run = await service.update(
                run_id=run["id"],
                tenant_key=effective_tenant_key,
                chain_mission=chain_mission,
            )

        conductor_job_id = await self._resolve_conductor_job_id(run["conductor_agent_id"], effective_tenant_key)
        return self._chain_run_response(run, conductor_job_id)

    # ------------------------------------------------------------------
    # BE-9500b: chain reverse gear (terminate-remaining, mark-reviewed)
    # ------------------------------------------------------------------

    _CHAIN_REVERSE_ACTIONS = frozenset({"terminate_remaining", "mark_reviewed"})

    async def _chain_run_reverse_gear(
        self,
        *,
        action: str,
        run_id: str | None,
        member_project_id: str | None,
        tenant_key: str,
    ) -> dict[str, Any]:
        """The two surviving chain verbs (BE-9500b), dispatched off ``action``.

        Each branch calls the exact ``SequenceRunService`` method the matching
        REST door calls -- one owning writer, two doors. Both routes
        end in ``service.update()`` internally, so ``sequence:updated`` fires the
        same as the REST path and the dashboard cockpit tracks a headless-driven
        end/review exactly as it tracks a UI-driven one.
        """
        if action not in self._CHAIN_REVERSE_ACTIONS:
            raise ValidationError(
                message=f"Invalid action {action!r}. Valid actions: start, "
                f"{', '.join(sorted(self._CHAIN_REVERSE_ACTIONS))}.",
                context={"valid_actions": ["start", *sorted(self._CHAIN_REVERSE_ACTIONS)]},
            )
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValidationError(message="run_id is required for this action", context={"field": "run_id"})

        service = SequenceRunService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            websocket_manager=self._websocket_manager,
            session=self._test_session,
        )

        if action == "terminate_remaining":
            run = await service.release(run_id=run_id, mode="cancel", tenant_key=tenant_key)
            return {"success": True, "action": action, "run": run}

        # Remaining branch: action == "mark_reviewed" (enforced by the membership check above).
        if not isinstance(member_project_id, str) or not member_project_id.strip():
            raise ValidationError(
                message="member_project_id is required for action='mark_reviewed'",
                context={"field": "member_project_id"},
            )
        run = await service.mark_member_reviewed(run_id=run_id, project_id=member_project_id, tenant_key=tenant_key)
        return {"success": True, "action": action, "run": run}

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_chain_inputs(project_ids: Any, execution_mode: Any, chain_mission: Any) -> None:
        """Type/enum/length validation of the raw agent inputs (clean 422 on failure)."""
        if not isinstance(project_ids, list) or not project_ids:
            raise ValidationError(
                message="project_ids must be a non-empty list of project_id strings",
                context={"field": "project_ids"},
            )
        if not all(isinstance(pid, str) and pid.strip() for pid in project_ids):
            raise ValidationError(
                message="every project_id must be a non-empty string",
                context={"field": "project_ids"},
            )
        if execution_mode not in ACCEPTED_EXECUTION_MODES:
            raise ValidationError(
                message=f"Invalid execution_mode {execution_mode!r}. Valid: {sorted(VALID_EXECUTION_MODES)}",
                context={"field": "execution_mode", "valid": sorted(VALID_EXECUTION_MODES)},
            )
        if chain_mission is not None:
            if not isinstance(chain_mission, str):
                raise ValidationError(message="chain_mission must be a string", context={"field": "chain_mission"})
            if len(chain_mission) > MAX_CHAIN_MISSION_CHARS:
                raise ValidationError(
                    message=f"chain_mission exceeds maximum of {MAX_CHAIN_MISSION_CHARS} characters",
                    context={"field": "chain_mission", "max": MAX_CHAIN_MISSION_CHARS},
                )

    async def _reject_unchainable(
        self,
        project_ids: list[str],
        order: list[str],
        tenant_key: str,
    ) -> dict[str, Any] | None:
        """Return a structured rejection dict if the membership is invalid, else None."""
        ordered_distinct = list(dict.fromkeys(project_ids))  # preserve order, drop dups

        # (d) a chain needs >= 2 distinct members.
        if len(ordered_distinct) < 2:
            return self._reject(
                "CHAIN_TOO_SMALL",
                "A chain needs at least 2 distinct projects.",
                project_ids=project_ids,
            )

        # (c) resolved_order must be a permutation of project_ids.
        if len(order) != len(project_ids) or set(order) != set(project_ids):
            return self._reject(
                "RESOLVED_ORDER_MISMATCH",
                "resolved_order must be a permutation of project_ids (same members, same length).",
                project_ids=project_ids,
                resolved_order=order,
            )

        # (a) existence + (b) not-terminal + (BE-9069) solo-HITL / launched screen —
        # one tenant-scoped query carrying the two extra gate columns.
        async with self.get_session_async() as session:
            rows = await session.execute(
                select(
                    Project.id,
                    Project.status,
                    Project.deleted_at,
                    Project.staging_status,
                    Project.implementation_launched_at,
                ).where(
                    Project.tenant_key == tenant_key,
                    Project.id.in_(ordered_distinct),
                )
            )
            found = {
                str(pid): (status, deleted_at, staging_status, launched_at)
                for pid, status, deleted_at, staging_status, launched_at in rows.all()
            }

        missing = [pid for pid in ordered_distinct if pid not in found]
        if missing:
            return self._reject(
                "PROJECT_NOT_FOUND",
                "One or more projects do not exist for this tenant.",
                project_ids=missing,
            )

        terminal = [
            pid for pid in ordered_distinct if found[pid][1] is not None or found[pid][0] in LIFECYCLE_FINISHED_STATUSES
        ]
        if terminal:
            return self._reject(
                "PROJECT_NOT_CHAINABLE",
                "One or more projects are terminal (completed/cancelled/terminated/deleted) and cannot join a chain.",
                project_ids=terminal,
                reason="terminal",
            )

        # BE-9069 (Defect A): refuse a member parked at the SOLO human Implement gate
        # (staging_status='staging_complete' with implementation_launched_at still NULL).
        # Enrolling it would let start_chain_run cross that project's sacred Implement gate
        # as a side effect, with ZERO human GO (BE-6115a). A genuine chain member is never
        # in this state — its staging-end stamps launch + staging_complete together.
        awaiting_implement = [
            pid for pid in ordered_distinct if found[pid][2] == "staging_complete" and found[pid][3] is None
        ]
        if awaiting_implement:
            return self._reject(
                "PROJECT_NOT_CHAINABLE",
                "One or more projects are staged and awaiting the solo Implement gate; click Implement "
                "(or unstage) before linking them into a chain.",
                project_ids=awaiting_implement,
                reason="awaiting_implement",
            )

        # BE-9069 (Defect B): refuse a member already in implementation (implementation_
        # launched_at set). Enrolling it mid-flight forces a forbidden mixed-mode chain (the
        # conductor re-stamp silently keeps its old execution_mode) and downgrades its live
        # staging_status. Re-election must start from a clean pre-launch project.
        launched = [pid for pid in ordered_distinct if found[pid][3] is not None]
        if launched:
            return self._reject(
                "PROJECT_NOT_CHAINABLE",
                "One or more projects have already launched implementation and cannot join a chain.",
                project_ids=launched,
                reason="already_launched",
            )

        # (b) not already a member of another active run (reuse the owning service's read).
        run_service = SequenceRunService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            session=self._test_session,
        )
        enrolled = [
            pid
            for pid in ordered_distinct
            if await run_service.find_active_run_for_project(project_id=pid, tenant_key=tenant_key) is not None
        ]
        if enrolled:
            return self._reject(
                "PROJECT_NOT_CHAINABLE",
                "One or more projects are already members of an active chain run.",
                project_ids=enrolled,
                reason="already_enrolled",
            )
        return None

    async def _resolve_conductor_job_id(self, conductor_agent_id: str, tenant_key: str) -> str:
        """Resolve the project-less conductor's job_id from its agent_id (tenant-scoped).

        The serialized run carries conductor_agent_id, but the bootstrap call
        (get_staging_instructions) takes a job_id — so resolve it the same way the
        chain-prompt endpoint does (api/endpoints/prompts.py._resolve_conductor_job_id).
        """
        async with self.get_session_async() as session:
            row = await session.execute(
                select(AgentExecution.job_id).where(
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.agent_id == conductor_agent_id,
                )
            )
            return str(row.scalar_one())

    # ------------------------------------------------------------------
    # Response shaping
    # ------------------------------------------------------------------

    @staticmethod
    def _reject(error_code: str, message: str, **extra: Any) -> dict[str, Any]:
        """BE-6081 structured rejection (returned, not raised; reaches the agent as content)."""
        return {"success": False, "error": error_code, "message": message, **extra}

    @staticmethod
    def _chain_run_response(run: dict[str, Any], conductor_job_id: str) -> dict[str, Any]:
        next_action = build_next_action(
            tool=_CONDUCTOR_BOOTSTRAP_TOOL,
            args_hint={"job_id": conductor_job_id},
            why=(
                "You are the dedicated chain conductor for this run. Receive your chain staging "
                "protocol (CH_CAPABILITY + CH_CHAIN_STAGING): stand up the Hub thread, author the "
                "chain mission, then complete_job to end staging. The implementation drive "
                "(get_job_mission) comes after staging is complete. This run row is the "
                "crash-resume ground truth, not a workflow you must hold in your own context: "
                "run['resolved_order'] + run['project_ids'] are the grouping/order and "
                "run['current_index'] + run['project_statuses'] are the live progress, all "
                "durable on the sequence_run record -- a fresh session that lost this response "
                "recovers by reading the record (get_context / the run itself), never by "
                "re-electing or re-staging. The dashboard's Run Sequential button writes this "
                "SAME record through the same SequenceRunService; you are not its only writer."
            ),
        )
        return {
            "success": True,
            "run": run,
            "run_id": run["id"],
            "conductor_agent_id": run["conductor_agent_id"],
            "conductor_job_id": conductor_job_id,
            "bootstrap_tool": _CONDUCTOR_BOOTSTRAP_TOOL,
            "next_action": next_action,
        }
