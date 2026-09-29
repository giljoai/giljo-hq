# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.platform_registry import (
    ACCEPTED_EXECUTION_MODES,
    EXECUTION_MODE_TO_TOOL,
    GENERIC_HARNESS,
    HARNESS_OPENCODE,
    MODE_MULTI_TERMINAL,
    effective_harness,
)
from giljo_mcp.prompts.spawn_prompt import launch_gate_passed
from giljo_mcp.services.comm_thread_enrolment import project_thread_ref
from giljo_mcp.services.execution_mode_gate import effective_execution_mode
from giljo_mcp.services.sequence_chain_context import chain_execution_mode_for_project


SUBAGENT_EXECUTION_PROMPT_TYPE = "subagent_execution"

_READY_TO_CLOSE_PROMPT = (
    "All specialist agents for this project have already completed their work — "
    "there is nothing left to implement. The project is ready to close.\n\n"
    "As the orchestrator: 1) review the recorded results (get_workflow_status), "
    "2) if your own orchestrator job is still open, finish it with complete_job, "
    "then 3) close the project with write_project_closeout(project_id=..., "
    "summary=..., key_outcomes=..., decisions_made=..., git_commits=[...]). "
    "If closeout reports CLOSEOUT_BLOCKED on a leftover 'waiting' orchestrator, "
    "pass force=true to auto-decommission it."
)

_TOOL_TYPE_TO_PROMPT_TYPE: dict[str, str] = {
    "multi_terminal": "multi_terminal_orchestrator",
    "claude-code": "claude_code_execution",
    "codex": "codex_execution",
    GENERIC_HARNESS: SUBAGENT_EXECUTION_PROMPT_TYPE,
    HARNESS_OPENCODE: SUBAGENT_EXECUTION_PROMPT_TYPE,
}

_IMPLEMENTATION_PROMPT_TYPE_MAP: dict[str, str] = {
    mode: _TOOL_TYPE_TO_PROMPT_TYPE.get(tool, "multi_terminal_orchestrator")
    for mode, tool in EXECUTION_MODE_TO_TOOL.items()
}


def select_implementation_prompt_type(execution_mode: str, detected_harness: str | None) -> tuple[str, str | None]:
    baseline = _IMPLEMENTATION_PROMPT_TYPE_MAP.get(execution_mode, "multi_terminal_orchestrator")
    if execution_mode == MODE_MULTI_TERMINAL:
        return baseline, None
    resolved_harness = effective_harness(execution_mode, {"harness": detected_harness})
    return _TOOL_TYPE_TO_PROMPT_TYPE.get(resolved_harness, baseline), resolved_harness


class ThinClientLifecycleMixin:

    _LAUNCHABLE_AGENT_STATUSES: ClassVar[tuple[str, ...]] = ("waiting", "working", "staged", "idle")

    async def _resolve_agent_cli_tools(
        self, executions: list[AgentExecution], *, execution_mode: str | None = None
    ) -> None:
        template_ids = {e.job.template_id for e in executions if e.job and e.job.template_id}
        mapping: dict[str, str | None] = {}
        if template_ids:
            rows = (
                await self.db.execute(
                    select(AgentTemplate.id, AgentTemplate.cli_tool).where(
                        AgentTemplate.id.in_(template_ids),
                        AgentTemplate.tenant_key == self.tenant_key,
                    )
                )
            ).all()
            mapping = dict(rows)

        role_default_map: dict[str, str] = {}
        if (execution_mode or "") == "multi_terminal":
            unresolved_roles = {
                e.agent_display_name
                for e in executions
                if e.agent_display_name and not mapping.get(e.job.template_id if e.job else None)
            }
            if unresolved_roles:
                role_rows = (
                    await self.db.execute(
                        select(AgentTemplate.role, AgentTemplate.cli_tool).where(
                            AgentTemplate.role.in_(unresolved_roles),
                            AgentTemplate.is_default,
                            AgentTemplate.cli_tool.is_not(None),
                            AgentTemplate.deleted_at.is_(None),
                            AgentTemplate.tenant_key == self.tenant_key,
                        )
                    )
                ).all()
                for role, ct in role_rows:
                    if ct and role not in role_default_map:
                        role_default_map[role] = ct

        for e in executions:
            tid = e.job.template_id if e.job else None
            cli = mapping.get(tid)
            if cli is None and role_default_map:
                cli = role_default_map.get(e.agent_display_name)
            e.cli_tool = cli or "claude"

    def _launch_commands_for(self, executions: list[AgentExecution], *, launched: bool) -> list[dict]:
        from giljo_mcp.prompts.launch_command_synth import DEFAULT_CLI_TOOL, render_harness_launch_block
        from giljo_mcp.template_validation import resolve_harness_name

        return [
            {
                "agent": e.agent_display_name or "agent",
                "cli_tool": getattr(e, "cli_tool", DEFAULT_CLI_TOOL) or DEFAULT_CLI_TOOL,
                "job_id": e.job_id,
                "launch": render_harness_launch_block(
                    resolve_harness_name(getattr(e, "cli_tool", None)), model=None, effort=None, launched=launched
                ),
            }
            for e in executions
        ]

    async def _fetch_launchable_agents(self, project_id: str) -> list[AgentExecution]:
        stmt = (
            select(AgentExecution)
            .options(joinedload(AgentExecution.job))
            .where(
                AgentExecution.tenant_key == self.tenant_key,
                AgentExecution.agent_display_name != "orchestrator",
                AgentExecution.status.in_(self._LAUNCHABLE_AGENT_STATUSES),
            )
            .join(
                AgentJob,
                (AgentJob.job_id == AgentExecution.job_id) & (AgentJob.tenant_key == AgentExecution.tenant_key),
            )
            .where(AgentJob.project_id == project_id)
            .order_by(AgentExecution.started_at.asc().nullsfirst())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    _IMPLEMENTATION_PROMPT_TYPE_MAP: ClassVar[dict[str, str]] = _IMPLEMENTATION_PROMPT_TYPE_MAP

    async def stage(self, project_id: str, user_id: str | None, tool: str, execution_mode: str) -> dict[str, Any]:
        result = await self.generate(project_id=project_id, user_id=user_id, tool=tool)

        staging_prompt = await self.generate_staging_prompt(
            orchestrator_id=result["orchestrator_id"],
            project_id=project_id,
            agent_id=result.get("agent_id"),
            tool=tool,
        )
        staging_tokens = len(staging_prompt) // 4

        launch_commands: list[dict] = []
        if execution_mode == "multi_terminal":
            agents = await self._fetch_launchable_agents(project_id)
            await self._resolve_agent_cli_tools(agents, execution_mode=execution_mode)
            launch_commands = self._launch_commands_for(agents, launched=False)

        thread_ref = await project_thread_ref(self.db, self.tenant_key, project_id)
        return {
            "orchestrator_id": result["orchestrator_id"],
            "agent_id": result.get("agent_id"),
            "execution_id": result.get("execution_id"),
            "prompt": staging_prompt,
            "estimated_prompt_tokens": staging_tokens,
            "launch_commands": launch_commands,
            "product_id": result.get("product_id"),
            **thread_ref,
        }

    async def implement(
        self, project_id: str, user_id: str | None = None, detected_harness: str | None = None
    ) -> dict[str, Any]:
        from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
        from giljo_mcp.services.project_staging_service import ProjectStagingService
        from giljo_mcp.services.settings_service import SettingsService

        project_stmt = (
            select(Project)
            .options(joinedload(Project.product))
            .where(Project.id == project_id, Project.tenant_key == self.tenant_key)
        )
        project = (await self.db.execute(project_stmt)).scalar_one_or_none()
        if not project:
            raise ResourceNotFoundError(f"Project {project_id} not found or not accessible")

        execution_mode = effective_execution_mode(
            project.execution_mode,
            await chain_execution_mode_for_project(self.db, project_id=project_id, tenant_key=self.tenant_key),
        )

        if execution_mode not in ACCEPTED_EXECUTION_MODES:
            raise ValidationError(f"Unsupported execution mode: {execution_mode}")

        ProjectStagingService.check_implementation_allowed(project)
        thread_ref = await project_thread_ref(self.db, self.tenant_key, project_id)

        orchestrator_stmt = (
            select(AgentExecution)
            .options(joinedload(AgentExecution.job))
            .where(
                AgentExecution.tenant_key == self.tenant_key,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
            )
            .join(
                AgentJob,
                (AgentJob.job_id == AgentExecution.job_id) & (AgentJob.tenant_key == AgentExecution.tenant_key),
            )
            .where(AgentJob.project_id == project_id)
            .order_by(AgentExecution.started_at.desc().nullslast())
        )
        orchestrator_execution = (await self.db.execute(orchestrator_stmt)).scalar_one_or_none()
        if not orchestrator_execution:
            raise ResourceNotFoundError(
                "No orchestrator found for this project. Please ensure staging has been completed."
            )

        agent_executions_stmt = (
            select(AgentExecution)
            .options(joinedload(AgentExecution.job))
            .where(
                AgentExecution.spawned_by == orchestrator_execution.agent_id,
                AgentExecution.tenant_key == self.tenant_key,
                AgentExecution.status.in_(["waiting", "working"]),
            )
            .order_by(AgentExecution.started_at.asc().nullsfirst())
        )
        agent_executions = (await self.db.execute(agent_executions_stmt)).scalars().all()
        if not agent_executions:
            fallback_stmt = (
                select(AgentExecution)
                .options(joinedload(AgentExecution.job))
                .where(
                    AgentExecution.tenant_key == self.tenant_key,
                    AgentExecution.agent_display_name != "orchestrator",
                    AgentExecution.status.in_(["waiting", "working"]),
                )
                .join(
                    AgentJob,
                    (AgentJob.job_id == AgentExecution.job_id) & (AgentJob.tenant_key == AgentExecution.tenant_key),
                )
                .where(AgentJob.project_id == project_id)
                .order_by(AgentExecution.started_at.asc().nullsfirst())
            )
            agent_executions = (await self.db.execute(fallback_stmt)).scalars().all()
        if not agent_executions:
            any_status_stmt = (
                select(AgentExecution)
                .where(
                    AgentExecution.tenant_key == self.tenant_key,
                    AgentExecution.agent_display_name != "orchestrator",
                )
                .join(
                    AgentJob,
                    (AgentJob.job_id == AgentExecution.job_id) & (AgentJob.tenant_key == AgentExecution.tenant_key),
                )
                .where(AgentJob.project_id == project_id)
            )
            all_specialists = (await self.db.execute(any_status_stmt)).scalars().all()
            if all_specialists and all(e.status in TERMINAL_EXECUTION_STATUSES for e in all_specialists):
                return {
                    "ready_to_close": True,
                    "prompt": _READY_TO_CLOSE_PROMPT,
                    "orchestrator_job_id": orchestrator_execution.job_id,
                    "agent_count": len(all_specialists),
                    "launch_commands": [],
                    **thread_ref,
                }
            raise ValidationError("No agent jobs spawned yet. Please run staging first to create agent jobs.")

        git_enabled = await SettingsService(self.db, self.tenant_key).git_integration_enabled()

        await self._resolve_agent_cli_tools(agent_executions, execution_mode=execution_mode)

        prompt_type, resolved_harness = select_implementation_prompt_type(execution_mode, detected_harness)
        prompt = self.generate_implementation_prompt(
            prompt_type=prompt_type,
            resolved_harness=resolved_harness,
            orchestrator_id=orchestrator_execution.job_id,
            project=project,
            agent_jobs=agent_executions,
            git_enabled=git_enabled,
        )

        launch_commands: list[dict] = []
        if execution_mode == "multi_terminal":
            launch_commands = self._launch_commands_for(agent_executions, launched=launch_gate_passed(project))

        return {
            "prompt": prompt,
            "orchestrator_job_id": orchestrator_execution.job_id,
            "agent_count": len(agent_executions),
            "launch_commands": launch_commands,
            **thread_ref,
        }
