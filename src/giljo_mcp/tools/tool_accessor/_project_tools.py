# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.harness_resolver import HARNESS_CLAUDE_CODE
from giljo_mcp.platform_registry import RETIRED_HARNESS_TOKENS
from giljo_mcp.schemas.service_responses import build_next_action


_STAGE_MODE_MAP: dict[str, tuple[str, str]] = {
    "multi_terminal": (HARNESS_CLAUDE_CODE, "multi_terminal"),
    "subagent": (HARNESS_CLAUDE_CODE, "subagent"),
    "claude": (HARNESS_CLAUDE_CODE, "subagent"),
    "codex": ("codex", "subagent"),
}
_STAGE_MODE_MAP.update(dict.fromkeys(RETIRED_HARNESS_TOKENS, _STAGE_MODE_MAP["subagent"]))

_EXECUTION_MODE_CHOICES: tuple[tuple[str, str], ...] = (
    ("multi_terminal", "Multi-Terminal -- a separate terminal per agent, and you watch the fleet."),
    ("subagent", "Subagent -- one session drives the worker agents itself, inside this conversation."),
)


def _execution_mode_required_rejection() -> dict[str, Any]:
    return {
        "success": False,
        "error": "EXECUTION_MODE_REQUIRED",
        "modes": [{"mode": mode, "description": description} for mode, description in _EXECUTION_MODE_CHOICES],
        "hint": (
            "Staging did not pick for you. Ask your user which way they want this run, then retry "
            "with mode='multi_terminal' or mode='subagent'. To stop being asked, set the account "
            "default once in the dashboard under Tools -> Agents (ask every time / terminals / subagents)."
        ),
    }


_STAGING_STOP_INSTRUCTION = (
    "STAGING COMPLETE — STOP HERE. Do NOT begin implementation. The user must review "
    "the staged plan in the GiljoAI dashboard and MANUALLY press Implement. Only after "
    "the user launches will get_implementation_prompt return the execution prompt. This gate is "
    "intentional and cannot be bypassed."
)

_STAGING_CHAIN_CONTINUE_INSTRUCTION = (
    "chain mode: there is NO per-project human Implement gate in a chain; the conductor "
    "already released you. Continue to implementation: call get_job_mission ONCE — it "
    "returns your implementation protocol and flips you to working. Do NOT wait for a "
    "human, do NOT return to the dashboard, do NOT sleep-poll a gate."
)

_STAGING_START_PHASES = (
    "Project ready for staging. Follow these phases in order: "
    "(1) call health_check(); stop and report if it fails. "
    '(2) call get_staging_instructions(job_id="{job_id}"). '
    "(3) follow the returned staging protocol to prepare and save the mission, execution "
    "plan and worker assignments. Do NOT begin implementation. "
    '(4) when all staging requirements are satisfied, call complete_job(job_id="{job_id}") '
    "to mark staging complete. "
    '(5) when the server confirms phase="staging_end", {phase_five} '
    "This response starts staging; it does not mean staging is complete."
)

_STAGING_PHASE_FIVE_SOLO = (
    "STOP: present the staged plan and wait for the user's explicit approval to implement "
    "(dashboard Implement, or launch_implementation where enabled)."
)


def _staging_start_instruction(job_id: str, *, is_chain_member: bool) -> str:
    return _STAGING_START_PHASES.format(
        job_id=job_id,
        phase_five=_STAGING_CHAIN_CONTINUE_INSTRUCTION if is_chain_member else _STAGING_PHASE_FIVE_SOLO,
    )


class ProjectToolsMixin:

    async def diagnose_project_state(self, project_id: str, tenant_key: str) -> dict[str, Any]:
        from giljo_mcp.services.project_closeout_service import ProjectCloseoutService

        service = ProjectCloseoutService(
            self.db_manager,
            self.tenant_manager,
            test_session=self._test_session,
            websocket_manager=self._websocket_manager,
        )
        return await service.diagnose_project_state(project_id, tenant_key=tenant_key)

    async def update_project_mission(self, project_id: str, mission: str) -> dict[str, Any]:
        tenant_key = self.tenant_manager.get_current_tenant()
        return await self._project_service.update_project_mission(project_id, mission, tenant_key=tenant_key)

    async def stage_project(
        self,
        project_id: str,
        mode: str,
        tenant_key: str,
        user_id: str | None = None,
        action: str = "stage",
        mission: str = "",
    ) -> dict[str, Any]:
        if action != "stage":
            return await self._stage_project_reverse_gear(project_id, action)

        from giljo_mcp.exceptions import ValidationError
        from giljo_mcp.platform_registry import ACCEPTED_EXECUTION_MODES, stage_mode_token
        from giljo_mcp.services.orchestrator_prompt_ws_broadcast import (
            broadcast_orchestrator_prompt_generated,
        )
        from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

        if not mode:
            mode = await self._resolve_stage_mode_default(tenant_key)
            if not mode:
                return _execution_mode_required_rejection()

        if mission:
            await self.update_project_mission(project_id, mission)

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
            await self._project_service.lifecycle.mark_staged(
                project_id, execution_mode, tenant_key=tenant_key, db_session=db
            )
            from giljo_mcp.services.sequence_run_service import active_chain_run

            is_chain_member = await active_chain_run(db, project_id, tenant_key) is not None

        await broadcast_orchestrator_prompt_generated(
            self._websocket_manager,
            tenant_key=tenant_key,
            project_id=project_id,
            orchestrator_id=result["orchestrator_id"],
            agent_id=result.get("agent_id"),
            execution_id=result.get("execution_id"),
            tool=tool,
            product_id=result.get("product_id"),
        )

        why = _staging_start_instruction(str(result.get("orchestrator_id", "")), is_chain_member=is_chain_member)
        return {
            "status": "staged",
            "mode": mode,
            "execution_mode": execution_mode,
            **result,
            "next_action": build_next_action(tool="health_check", why=why),
        }

    async def _resolve_stage_mode_default(self, tenant_key: str) -> str:
        from giljo_mcp.execution_mode_default import (
            EXECUTION_MODE_DEFAULT_KEY,
            STAGE_MODE_ASK,
            default_stage_mode,
        )
        from giljo_mcp.services.settings_service import SettingsService

        async with self.get_session_async() as db:
            stored = await SettingsService(db, tenant_key).get_setting_value(
                "general", EXECUTION_MODE_DEFAULT_KEY, default=STAGE_MODE_ASK
            )
        return default_stage_mode(stored if isinstance(stored, str) else None)

    _STAGE_REVERSE_ACTIONS: frozenset[str] = frozenset({"unstage", "restage", "cancel_staging"})

    async def _stage_project_reverse_gear(self, project_id: str, action: str) -> dict[str, Any]:
        from giljo_mcp.exceptions import ValidationError

        if action not in self._STAGE_REVERSE_ACTIONS:
            raise ValidationError(
                f"Invalid action '{action}'. Valid actions: stage, {', '.join(sorted(self._STAGE_REVERSE_ACTIONS))}.",
                context={"valid_actions": ["stage", *sorted(self._STAGE_REVERSE_ACTIONS)]},
            )

        if action == "unstage":
            result = await self._project_service.lifecycle.unstage(project_id)
        elif action == "restage":
            result = await self._project_service.lifecycle.restage(project_id)
        else:
            data = await self._project_service.lifecycle.cancel_staging(
                project_id, websocket_manager=self._websocket_manager
            )
            result = {"message": "Staging cancelled.", "project_id": data.id}

        return {
            "status": action,
            "project_id": result["project_id"],
            "message": result["message"],
        }

    async def implement_project(
        self,
        project_id: str,
        tenant_key: str,
        user_id: str | None = None,
        detected_harness: str | None = None,
    ) -> dict[str, Any]:
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
        mission: str | None = None,
    ) -> dict[str, Any]:
        if mission is not None and mission.strip():
            await self.update_project_mission(project_id, mission)

        from giljo_mcp.exceptions import ImplementationNotReadyError
        from giljo_mcp.services.project_staging_service import ProjectStagingService

        staging_service = ProjectStagingService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            test_session=self._test_session,
            websocket_manager=self._websocket_manager,
        )
        try:
            result = await staging_service.launch_implementation(
                project_id=project_id,
                tenant_key=tenant_key,
                launched_by=user_id,
                origin="mcp",
            )
        except ImplementationNotReadyError as e:
            return self._implementation_gate_error(e, project_id)
        return {
            "status": "launched",
            **result,
        }

    @staticmethod
    def _implementation_gate_error(error: Any, project_id: str) -> dict[str, Any]:
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
            "chain_predecessor_open": build_next_action(
                tool="get_workflow_status",
                why=(
                    "Linked projects run ONE AT A TIME. The project before this one has not closed "
                    "out yet, so this one cannot start. Finish that project and call "
                    "write_project_closeout on it; this project's launch (and its play button in "
                    "the dashboard) unlocks the moment that close-out is recorded."
                ),
            ),
            "not_launched": build_next_action(
                why=(
                    f"{_STAGING_STOP_INSTRUCTION} Ask the user to open this project in "
                    "the GiljoAI dashboard and click Implement, then call get_implementation_prompt again. "
                    "If you are unsure why the "
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
