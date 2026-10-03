# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
from giljo_mcp.services.next_action import STAGING_COMPLETE
from giljo_mcp.services.sequence_run_service import MAX_CHAIN_MISSION_CHARS, SequenceRunService


logger = logging.getLogger(__name__)

_CONDUCTOR_BOOTSTRAP_TOOL = "get_staging_instructions"

_EXECUTION_MODE_QUESTION = (
    "Ask the user ONE question before you retry, and do not guess: how should this chain "
    "run -- 'subagent' (each project's sub-orchestrator runs its workers inside this "
    "session, using this harness's own task/subagent tool) or 'multi_terminal' (one "
    "terminal per agent, coordinated over the Message Hub)? Then call link_projects again "
    "with execution_mode set to their answer."
)


def _execution_mode_question() -> dict[str, Any]:
    return {
        "success": False,
        "error": "EXECUTION_MODE_REQUIRED",
        "options": ["subagent", "multi_terminal"],
        "message": "execution_mode was not answered. It is the user's choice, so ask them.",
        "next_action": build_next_action(tool="link_projects", why=_EXECUTION_MODE_QUESTION),
    }


class ChainToolsMixin:

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

        if project_ids is None:
            raise ValidationError(
                message="project_ids is required for action='start'",
                context={"operation": "accessor.start_chain_run"},
            )
        if execution_mode is None:
            return _execution_mode_question()

        self._validate_chain_inputs(project_ids, execution_mode, chain_mission)

        order = list(resolved_order) if resolved_order is not None else list(project_ids)

        rejection = await self._reject_unchainable(project_ids, order, effective_tenant_key)
        if rejection is not None:
            return rejection

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
            run = await service.update(
                run_id=run["id"],
                tenant_key=effective_tenant_key,
                chain_mission=chain_mission,
            )

        conductor_job_id = await self._resolve_conductor_job_id(run["conductor_agent_id"], effective_tenant_key)
        return self._chain_run_response(run, conductor_job_id)


    _CHAIN_REVERSE_ACTIONS = frozenset({"terminate_remaining", "mark_reviewed"})

    async def _chain_run_reverse_gear(
        self,
        *,
        action: str,
        run_id: str | None,
        member_project_id: str | None,
        tenant_key: str,
    ) -> dict[str, Any]:
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
            run = await service.stop_chain(run_id=run_id, tenant_key=tenant_key)
            return {"success": True, "action": action, "run": run}

        if not isinstance(member_project_id, str) or not member_project_id.strip():
            raise ValidationError(
                message="member_project_id is required for action='mark_reviewed'",
                context={"field": "member_project_id"},
            )
        run = await service.mark_member_reviewed(run_id=run_id, project_id=member_project_id, tenant_key=tenant_key)
        return {"success": True, "action": action, "run": run}


    @staticmethod
    def _validate_chain_inputs(project_ids: Any, execution_mode: Any, chain_mission: Any) -> None:
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
        ordered_distinct = list(dict.fromkeys(project_ids))

        if len(ordered_distinct) < 2:
            return self._reject(
                "CHAIN_TOO_SMALL",
                "A chain needs at least 2 distinct projects.",
                project_ids=project_ids,
            )

        if len(order) != len(project_ids) or set(order) != set(project_ids):
            return self._reject(
                "RESOLVED_ORDER_MISMATCH",
                "resolved_order must be a permutation of project_ids (same members, same length).",
                project_ids=project_ids,
                resolved_order=order,
            )

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

        awaiting_implement = [
            pid for pid in ordered_distinct if found[pid][2] == STAGING_COMPLETE and found[pid][3] is None
        ]
        if awaiting_implement:
            return self._reject(
                "PROJECT_NOT_CHAINABLE",
                "One or more projects are staged and awaiting the solo Implement gate; click Implement "
                "(or unstage) before linking them into a chain.",
                project_ids=awaiting_implement,
                reason="awaiting_implement",
            )

        launched = [pid for pid in ordered_distinct if found[pid][3] is not None]
        if launched:
            return self._reject(
                "PROJECT_NOT_CHAINABLE",
                "One or more projects have already launched implementation and cannot join a chain.",
                project_ids=launched,
                reason="already_launched",
            )

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
        async with self.get_session_async() as session:
            row = await session.execute(
                select(AgentExecution.job_id).where(
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.agent_id == conductor_agent_id,
                )
            )
            return str(row.scalar_one())


    @staticmethod
    def _reject(error_code: str, message: str, **extra: Any) -> dict[str, Any]:
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
