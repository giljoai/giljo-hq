# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Project domain tools mixin for ToolAccessor (BE-6042a split)."""

from __future__ import annotations

from typing import Any

from giljo_mcp.schemas.service_responses import build_next_action


# INF-6049b / BE-9035c: stage_project's user-facing ``mode`` -> the engine's
# (tool, execution_mode) vocabulary. The public MCP ``mode`` param KEEPS accepting
# multi_terminal | subagent | claude | codex | gemini | antigravity (agent-facing
# contract preserved — DESIGN §3). Post-collapse the stored execution_mode is one of
# the 2 canonical modes; the per-CLI short tokens map to ``subagent`` + a HARNESS
# HINT (the ``tool`` slot — the staging prose flavor) so a caller may still name its
# CLI without breaking, while the persisted mode is the collapsed ``subagent``.
_STAGE_MODE_MAP: dict[str, tuple[str, str]] = {
    "multi_terminal": ("claude-code", "multi_terminal"),
    "subagent": ("claude-code", "subagent"),
    "claude": ("claude-code", "subagent"),
    "codex": ("codex", "subagent"),
    "gemini": ("gemini", "subagent"),
    "antigravity": ("antigravity", "subagent"),
}

# The explicit stop instruction the staging payload + tool description must end on
# (feedback_staging_stop_do_not_execute — the human gate is sacred).
_STAGING_STOP_INSTRUCTION = (
    "STAGING COMPLETE — STOP HERE. Do NOT begin implementation. The user must review "
    "the staged plan in the GiljoAI dashboard and MANUALLY press Implement. Only after "
    "the user launches will implement_project return the execution prompt. This gate is "
    "intentional and cannot be bypassed."
)

# BE-9015: the chain-mode counterpart. A chain sub-orchestrator has NO per-project
# human Implement gate — the conductor already released it — so returning the SOLO
# STOP instruction to a chain member wedges it waiting for a dashboard click that
# never comes. When stage_project detects an active chain run for the project it
# emits THIS instead (mirrors mission_orchestration_service._check_staging_redirect's
# chain-member branch: staging complete -> get_job_mission carries you straight into
# implementation).
_STAGING_CHAIN_CONTINUE_INSTRUCTION = (
    "STAGING COMPLETE — chain mode. There is NO per-project human Implement gate in a "
    "chain; the conductor already released you. Continue to implementation now: call "
    "get_job_mission ONCE — it returns your implementation protocol and flips you to "
    "working. Do NOT wait for a human, do NOT return to the dashboard, do NOT sleep-poll "
    "a gate."
)


class ProjectToolsMixin:
    """Project lifecycle ADAPTER tools. Composed into ToolAccessor.

    BE-6118: the pure create_project / list_projects / update_project_metadata
    pass-throughs were deleted (``_call_tool`` dispatches them straight to
    ProjectService via ``TOOL_DISPATCH``). What remains are ADAPTERs resolved
    through the ``getattr`` fallback: diagnose_project_state (constructs
    ProjectCloseoutService), update_project_mission (injects the current tenant),
    and the stage/implement/launch gate tools (mode mapping + structured gate
    errors + the human-gate stop instruction).
    """

    async def diagnose_project_state(self, project_id: str, tenant_key: str) -> dict[str, Any]:
        """Read-only project lifecycle diagnostic (BE-6111c / BE-5055).

        Delegates to ProjectCloseoutService, constructed with the accessor's bound
        deps so the diagnostic owns its tenant-scoped session (no ad-hoc session
        here). Reports status/gates + agent counts + readiness + stuck conditions.
        """
        from giljo_mcp.services.project_closeout_service import ProjectCloseoutService

        service = ProjectCloseoutService(
            self.db_manager,
            self.tenant_manager,
            test_session=self._test_session,
            websocket_manager=self._websocket_manager,
        )
        return await service.diagnose_project_state(project_id, tenant_key=tenant_key)

    async def update_project_mission(self, project_id: str, mission: str) -> dict[str, Any]:
        """Update the mission field (delegates to ProjectService)"""
        # SECURITY FIX (Handover 0424): Always pass tenant_key for isolation
        tenant_key = self.tenant_manager.get_current_tenant()
        return await self._project_service.update_project_mission(project_id, mission, tenant_key=tenant_key)

    async def stage_project(
        self,
        project_id: str,
        mode: str,
        tenant_key: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Drive the staging endpoint for a project (INF-6049b).

        Produces exactly what the dashboard "copy staging prompt" button does, but
        the driving agent acts on it directly. Reuses the existing prompt engine
        (ThinClientPromptGenerator.stage -> generate / generate_staging_prompt /
        StagingPromptBuilder) — ZERO duplicated prompt-building.

        The returned payload ENDS with the explicit stop instruction: staging
        completes -> STOP -> the user reviews the dashboard -> the user manually
        triggers implementation. This tool NEVER launches implementation.
        """
        from giljo_mcp.exceptions import ValidationError
        from giljo_mcp.platform_registry import ACCEPTED_EXECUTION_MODES, stage_mode_token
        from giljo_mcp.services.orchestrator_prompt_ws_broadcast import (
            broadcast_orchestrator_prompt_generated,
        )
        from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

        # BE-6177/BE-9035c backstop: accept the short token (claude / subagent) OR a full
        # project/run execution_mode — the 2 canonical modes AND the 5 legacy ``*_cli``
        # tokens (tolerance) — and normalize to the short token. The conductor's staging
        # chapter emits the execution_mode vocabulary; this keeps the boundary forgiving
        # so a chain stage never hard-fails on a spelling axis. ONLY a recognized
        # execution_mode is translated — an unknown value is left untouched so it still
        # errors below (no silent coercion).
        if mode in _STAGE_MODE_MAP:
            normalized_mode = mode
        elif mode in ACCEPTED_EXECUTION_MODES:
            normalized_mode = stage_mode_token(mode)
        else:
            normalized_mode = mode
        mapping = _STAGE_MODE_MAP.get(normalized_mode)
        if mapping is None:
            raise ValidationError(
                f"Invalid mode '{mode}'. Valid modes: {sorted(_STAGE_MODE_MAP)}.",
                context={"valid_modes": sorted(_STAGE_MODE_MAP)},
            )
        mode = normalized_mode
        tool, execution_mode = mapping

        async with self.get_session_async() as db:
            generator = ThinClientPromptGenerator(db, tenant_key)
            result = await generator.stage(
                project_id=project_id, user_id=user_id, tool=tool, execution_mode=execution_mode
            )
            # The mark_staged single-writer transaction fix: stage() no longer
            # persists the staged state itself -- route it through the OWNING service
            # on this SAME session, so the whole staging call is one transaction
            # instead of two. Ordering preserved: write, then chain-membership check
            # (must see committed state), then the WS broadcast after the session
            # closes (below).
            await self._project_service.lifecycle.mark_staged(
                project_id, execution_mode, tenant_key=tenant_key, db_session=db
            )
            # BE-9015: the next_action must be chain-aware. A SOLO project keeps the
            # sacred human Implement gate (STOP); a CHAIN member has no such gate (the
            # conductor released it) and must continue via get_job_mission — else it
            # wedges waiting for a dashboard click chain mode never has.
            is_chain_member = await self._stage_is_chain_member(db, project_id, tenant_key)

        # BE-9332: staging over MCP is the headless/CLI path, and it used to emit
        # NOTHING — the orchestrator card never appeared in the dashboard for a
        # CLI-driven staging. Emission is a TRANSPORT concern and stays with the
        # caller by design (stage()'s docstring: "Transport concerns (HTTP guards,
        # WebSocket broadcast, structured errors) stay with the caller"), so the
        # REST endpoints and this tool are peers, all three going through the one
        # shared emitter. POST-COMMIT: the session block above has closed, so this
        # can never announce a state a rollback could still undo.
        await broadcast_orchestrator_prompt_generated(
            self._websocket_manager,
            tenant_key=tenant_key,
            project_id=project_id,
            orchestrator_id=result["orchestrator_id"],
            agent_id=result.get("agent_id"),
            execution_id=result.get("execution_id"),
            tool=tool,
        )

        why = _STAGING_CHAIN_CONTINUE_INSTRUCTION if is_chain_member else _STAGING_STOP_INSTRUCTION
        return {
            "status": "staged",
            "mode": mode,
            "execution_mode": execution_mode,
            **result,
            "next_action": build_next_action(why=why),
        }

    async def _stage_is_chain_member(self, session: Any, project_id: str, tenant_key: str) -> bool:
        """Best-effort: True if the project belongs to an ACTIVE chain run (BE-9015).

        Mirrors job_lifecycle_service._is_active_chain_member /
        mission_orchestration_service._is_chain_member: constructs SequenceRunService
        on the SAME already-open session and calls find_active_run_for_project
        (tenant_key-scoped, active statuses only).

        On ANY failure this returns False (treat as SOLO) — a DELIBERATE fail-safe, NOT
        a bug: the human Implement gate is SACRED. A DB error must fail toward "STOP,
        ask the human" (solo), never toward "continue without approval" (chain). A rare
        chain wedge on a lookup error is visible and recoverable; a solo project that
        silently skips the gate is not. Do NOT "fix" this to raise. (BE-9015, per CI1-EM2.)
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
        except Exception:  # noqa: BLE001 - best-effort chain detection; never break staging (fail-safe to solo)
            return False

    async def implement_project(
        self,
        project_id: str,
        tenant_key: str,
        user_id: str | None = None,
        detected_harness: str | None = None,
    ) -> dict[str, Any]:
        """Return the implementation prompt for an already-staged + launched project (INF-6049b).

        Server-side preconditions are enforced via the SHARED gate
        (ProjectStagingService.check_implementation_allowed, also used by the REST
        endpoint): the project must exist for the tenant, staging must be complete,
        AND the user must have pressed Implement in the dashboard
        (implementation_launched_at set).

        If the human gate has NOT been pressed this returns a STRUCTURED ERROR (not
        an exception) telling the agent the exact next action — distinguishing
        "staging not complete" from "press Implement in the dashboard". This tool
        NEVER sets implementation_launched_at and offers NO bypass parameter.
        """
        from giljo_mcp.exceptions import ImplementationNotReadyError
        from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

        async with self.get_session_async() as db:
            generator = ThinClientPromptGenerator(db, tenant_key)
            try:
                payload = await generator.implement(
                    project_id=project_id, user_id=user_id, detected_harness=detected_harness
                )
            except ImplementationNotReadyError as e:
                return self._implementation_gate_error(e, project_id)

        # BE-9165 (wall 3): every specialist already completed — steer the caller
        # to closeout instead of telling it to launch agents that no longer exist.
        if payload.get("ready_to_close"):
            return {
                "status": "ready_to_close",
                **payload,
                "next_action": build_next_action(
                    tool="write_project_closeout",
                    why=(
                        "All specialist agents have already completed their work — nothing left to "
                        "implement. Close the project (write_project_closeout; pass force=true if a "
                        "leftover 'waiting' orchestrator blocks it)."
                    ),
                ),
            }

        return {
            "status": "ready",
            **payload,
            "next_action": build_next_action(
                why=(
                    "Implementation prompt ready. Launch/seed the orchestrator with this prompt. In "
                    "multi_terminal mode, open one new session per agent using the PER-SESSION AGENT SEED "
                    "block embedded in the prompt."
                )
            ),
        }

    async def launch_implementation(
        self,
        project_id: str,
        tenant_key: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """CLI door of the two-door implement gate (BE-6115a).

        Stamps ``implementation_launched_at`` through the SAME single-writer the
        dashboard Implement button uses
        (``ProjectStagingService.launch_implementation``) — there is NO parallel
        write path. This is a USER / driving-agent lifecycle tool, deliberately
        kept OUT of the orchestrator auto-tool bundle (``_canonical_tool_list``):
        a spawned/staging agent has no schema for it and therefore CANNOT
        self-unlock implementation. The MCP permission prompt on this tool IS the
        human authorization — the human gate stays sacred.

        Downstream gates: ``implement_project`` / ``get_job_mission`` / ``spawn_job``
        still refuse a SOLO project until this flag is set, and this tool offers NO
        bypass of those checks — it only sets the flag a human authorized via the
        permission prompt. (A conductor-released CHAIN member has no human Implement
        button and is exempted from those gates via ``_is_chain_member``; BE-9069 keeps
        a member parked at the solo Implement gate out of that exemption.)
        """
        from giljo_mcp.services.project_staging_service import ProjectStagingService

        staging_service = ProjectStagingService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            test_session=self._test_session,
            websocket_manager=self._websocket_manager,
        )
        result = await staging_service.launch_implementation(
            project_id=project_id,
            tenant_key=tenant_key,
            launched_by=user_id,
            # TSK-6219: the launch_implementation MCP tool is the headless (mcp) door.
            origin="mcp",
        )
        return {
            "status": "launched",
            **result,
        }

    @staticmethod
    def _implementation_gate_error(error: Any, project_id: str) -> dict[str, Any]:
        """Build the distinguishable, actionable structured error for the human gate."""
        # BE-6225c: each recovery hint points at diagnose_project_state -- the
        # read-only self-heal diagnostic an orchestrator should call when a gate
        # won't clear and it isn't sure why, instead of guessing.
        actions = {
            "staging_incomplete": build_next_action(
                tool="stage_project",
                args_hint={"project_id": project_id},
                why=(
                    "Staging is not complete for this project. Run stage_project(project_id, mode) and "
                    "let the orchestrator finish staging first. If you are unsure why the gate has not "
                    "cleared, call diagnose_project_state(project_id) (read-only) to see the stuck "
                    "condition and the suggested recovery step."
                ),
            ),
            "not_launched": build_next_action(
                why=(
                    "The human Implement gate has not been pressed. Ask the user to open this project in "
                    "the GiljoAI dashboard and click Implement, then call implement_project again. This "
                    "gate is intentional and CANNOT be bypassed by the agent. If you are unsure why the "
                    "gate has not cleared, call diagnose_project_state(project_id) (read-only) to see the "
                    "stuck condition and the suggested recovery step."
                )
            ),
        }
        return {
            "status": "gate_not_passed",
            "reason": error.reason,
            "error": error.message,
            "next_action": actions.get(error.reason, build_next_action(why=error.message)),
            "project_id": project_id,
        }
