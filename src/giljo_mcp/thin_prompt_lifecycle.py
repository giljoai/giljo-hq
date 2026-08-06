# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Staging + implementation lifecycle cores for ThinClientPromptGenerator (INF-6049b).

Mechanical mixin split (mirrors the BE-6042 / tool_accessor mixin pattern) to keep
``thin_prompt_generator.py`` under the file-size guardrail. ``stage()`` and
``implement()`` are the SINGLE generation paths shared by the REST prompt endpoints
AND the ``stage_project`` / ``implement_project`` MCP tools — zero duplicated
prompt-building. They run on the composed ``ThinClientPromptGenerator`` and use its
``db`` / ``tenant_key`` / ``generate`` / ``generate_staging_prompt`` /
``generate_implementation_prompt`` members.
"""

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
from giljo_mcp.services.execution_mode_gate import effective_execution_mode
from giljo_mcp.services.sequence_chain_context import chain_execution_mode_for_project


# The harness-neutral subagent implementation prompt type (BE-9099) — served by
# SubagentPromptBuilder. Defined here (with the map it appears in) and imported by
# thin_prompt_generator's builders dict so the token never drifts between the two.
SUBAGENT_EXECUTION_PROMPT_TYPE = "subagent_execution"

# BE-9165 (wall 3): the closeout-only guidance returned when every specialist has
# already completed — there is nothing left to implement, so the misleading
# "No agent jobs spawned yet" 400 must never surface for this state.
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

# tool_type (harness token) -> generate_implementation_prompt type. Antigravity reuses
# gemini's builder (BE-6041b D1-B). BE-9099: the ``generic`` floor and ``opencode`` (a
# detectable harness with no dedicated CLI builder) route to the harness-neutral
# subagent builder — NOT the multi_terminal builder. This makes
# ``multi_terminal_orchestrator`` UNREACHABLE from any subagent-family harness (the
# BE-9035c regression: ``generic`` had no key, so ``.get()`` fell through to the
# multi_terminal seed for every subagent-elected project). ``multi_terminal`` is the
# ONLY key that maps to the multi_terminal builder.
_TOOL_TYPE_TO_PROMPT_TYPE: dict[str, str] = {
    "multi_terminal": "multi_terminal_orchestrator",
    "claude-code": "claude_code_execution",
    "codex": "codex_execution",
    "gemini": "gemini_execution",
    "antigravity": "gemini_execution",
    GENERIC_HARNESS: SUBAGENT_EXECUTION_PROMPT_TYPE,
    HARNESS_OPENCODE: SUBAGENT_EXECUTION_PROMPT_TYPE,
}

# execution_mode -> generate_implementation_prompt type. Single source shared by
# implement() and the REST /implementation endpoint (0497c, 0838 added codex/gemini).
# BE-9035a: built by iterating EVERY registry execution_mode (instead of a
# hand-copied literal), so a platform the registry knows about can never be silently
# absent here — the omission that 400'd generic_mcp at implement(). BE-9035c: since
# EXECUTION_MODE_TO_TOOL now carries the 2 canonical modes AND the 5 legacy aliases,
# this map covers both. BE-9099: this is the DECLARED-mode baseline (no session) —
# ``subagent`` (tool ``generic``) and every legacy alias whose tool is ``generic``
# (incl. ``generic_mcp``) resolve to the harness-neutral subagent builder; implement()
# then applies the DETECTED-beats-declared upgrade via effective_harness. The
# ``multi_terminal_orchestrator`` default only guards a corrupted DB value (every real
# key resolves through _TOOL_TYPE_TO_PROMPT_TYPE, which now covers ``generic``).
_IMPLEMENTATION_PROMPT_TYPE_MAP: dict[str, str] = {
    mode: _TOOL_TYPE_TO_PROMPT_TYPE.get(tool, "multi_terminal_orchestrator")
    for mode, tool in EXECUTION_MODE_TO_TOOL.items()
}


def select_implementation_prompt_type(execution_mode: str, detected_harness: str | None) -> tuple[str, str | None]:
    """Resolve ``(prompt_type, resolved_harness)`` for implement() (BE-9099).

    The ONE place the implement-phase builder-selection precedence lives (pure + total,
    no DB) so it is testable at the failing layer:

    * ``multi_terminal`` is MODE-FIXED -> ``('multi_terminal_orchestrator', None)``. Its
      render NEVER depends on the detected harness -> byte-parity with the golden.
    * every SUBAGENT-family mode (canonical ``subagent`` + the 5 legacy ``*_cli`` /
      ``generic_mcp`` aliases) applies the DETECTED-beats-declared upgrade via
      :func:`effective_harness` — a detected CLI (claude-code / codex / gemini /
      antigravity) resolves to its native builder; ``generic`` / ``opencode`` /
      undetected resolve to the harness-neutral subagent builder.

    Consequence (the BE-9035c regression this fixes): ``multi_terminal_orchestrator`` is
    UNREACHABLE from a subagent-family election. ``resolved_harness`` is returned so the
    caller can seed the harness-neutral subagent builder's registry-sourced spawn prose;
    it is ``None`` for a multi_terminal election.
    """
    baseline = _IMPLEMENTATION_PROMPT_TYPE_MAP.get(execution_mode, "multi_terminal_orchestrator")
    if execution_mode == MODE_MULTI_TERMINAL:
        return baseline, None
    resolved_harness = effective_harness(execution_mode, {"harness": detected_harness})
    return _TOOL_TYPE_TO_PROMPT_TYPE.get(resolved_harness, baseline), resolved_harness


class ThinClientLifecycleMixin:
    """stage() + implement() cores. Composed into ThinClientPromptGenerator."""

    # INF-6049c: agent statuses that represent a spawned, launchable team member
    # (pre-run or running) when synthesizing per-terminal launch commands.
    _LAUNCHABLE_AGENT_STATUSES: ClassVar[tuple[str, ...]] = ("waiting", "working", "staged", "idle")

    async def _resolve_agent_cli_tools(
        self, executions: list[AgentExecution], *, execution_mode: str | None = None
    ) -> None:
        """Attach each execution's assigned coding tool (INF-6049c).

        The role->tool mapping is an ``agent_templates.cli_tool`` property; resolve
        it via each job's ``template_id`` (tenant-filtered) and stamp a transient,
        non-persisted ``cli_tool`` attribute on the execution. Unmapped agents
        (no template, or unset cli_tool) default to ``claude``. Read by the
        per-terminal seed block AND launch_commands synthesis.

        BE-6204 — multi_terminal ROLE fallback. When a worker's job carries NO
        ``template_id`` (or that template's ``cli_tool`` is unset) — the "local
        template storage may be absent" case multi_terminal must tolerate — fall
        back to the worker's ROLE default template (``is_default`` for that role,
        keyed by the execution's ``agent_display_name``) instead of silently
        defaulting to ``claude``. Resolution chain:
        ``job template_id.cli_tool -> role-default-template.cli_tool -> "claude"``.
        GATED on ``multi_terminal``: every other mode resolves exactly as before
        (``template_id -> claude``), so their rendered prompt stays byte-identical.
        """
        template_ids = {e.job.template_id for e in executions if e.job and e.job.template_id}
        # Keep raw cli_tool (may be None) so a missing harness can trigger the
        # BE-6204 role fallback below; the final ``or "claude"`` still coalesces.
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

        # BE-6204: build the role -> default-template cli_tool map ONLY in
        # multi_terminal, and ONLY for the roles whose template_id path yielded no
        # harness. Subagent modes skip this entirely -> byte-identical resolution.
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
                # One default per role is the invariant; first non-empty wins.
                for role, ct in role_rows:
                    if ct and role not in role_default_map:
                        role_default_map[role] = ct

        for e in executions:
            tid = e.job.template_id if e.job else None
            cli = mapping.get(tid)
            if cli is None and role_default_map:
                cli = role_default_map.get(e.agent_display_name)
            e.cli_tool = cli or "claude"

    def _launch_commands_for(self, executions: list[AgentExecution]) -> list[dict]:
        """Synthesize the structured, advisory ``launch_commands`` array (INF-6049c).

        One entry per spawned agent; each carries its assigned tool + the per-OS
        command that opens a terminal running that CLI pre-seeded with the agent's
        initiation prompt (the SAME seed lines the per-terminal block renders).
        These are strings the DRIVING agent / user runs locally — never executed
        server-side.
        """
        from giljo_mcp.prompts.launch_command_synth import build_loaded_prompt, synthesize_launch_commands

        # BE-6182: the launch command's terminal argument is now a NATURAL-LANGUAGE
        # loaded prompt (verify MCP -> get_job_mission(job_id) -> execute), not raw
        # tool-call seed lines a CLI would not interpret. The synthesizer adds the
        # per-harness autonomy flag + terminal wrapper so the terminal runs unattended.
        specs = [
            {
                "agent": e.agent_display_name,
                "cli_tool": getattr(e, "cli_tool", "claude"),
                "job_id": e.job_id,
                "seed_prompt": build_loaded_prompt(e.job_id),
            }
            for e in executions
        ]
        return synthesize_launch_commands(specs)

    async def _fetch_launchable_agents(self, project_id: str) -> list[AgentExecution]:
        """Fetch a project's spawned (non-orchestrator) agents for launch synthesis."""
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

    # Module-level maps (above) are the single source shared by implement() and the
    # REST /implementation endpoint; referenced as ClassVars so existing
    # ``self._IMPLEMENTATION_PROMPT_TYPE_MAP`` call sites are unchanged. The map is
    # registry-derived (iterates EXECUTION_MODE_TO_TOOL), so BE-9035c's canonical
    # ``subagent`` mode and every stored legacy ``*_cli`` row are all covered. BE-9099:
    # implement() applies the SAME DETECTED-beats-declared harness upgrade the MISSION
    # path uses (effective_harness) via _TOOL_TYPE_TO_PROMPT_TYPE, so a detected CLI
    # subagent orchestrator gets its native builder here too.
    _IMPLEMENTATION_PROMPT_TYPE_MAP: ClassVar[dict[str, str]] = _IMPLEMENTATION_PROMPT_TYPE_MAP

    async def stage(self, project_id: str, user_id: str | None, tool: str, execution_mode: str) -> dict[str, Any]:
        """Shared staging core (INF-6049b) — create the orchestrator job and build the
        mode-specific staging prompt. Pure generation; does NOT persist staged state.

        This is the generation path the ``stage_project`` MCP tool drives; it reuses
        the EXISTING engine (``generate`` + ``generate_staging_prompt`` ->
        ``StagingPromptBuilder``) with ZERO duplicated prompt-building. Transport
        concerns (HTTP guards, WebSocket broadcast, structured errors) stay with the
        caller. Content is therefore equivalent to ``GET /api/prompts/staging`` for
        the same project + resolved tool.

        The mark_staged single-writer transaction fix: this method used to also
        raw-write ``project.staging_status='staged'`` + ``execution_mode`` and
        ``self.db.commit()`` inline here, on a re-fetched project row -- a SECOND
        write path for the identical transition ``ProjectStagingService.mark_staged``
        already owns, and on a session the caller had no way to control. That write
        (and the redundant re-fetch it required) is gone; EVERY caller of ``stage()``
        MUST now call ``ProjectStagingService.mark_staged`` (via the
        ``ProjectLifecycleService`` facade) itself, on its own session, right after
        this returns -- see ``ToolAccessor.stage_project``
        (``tools/tool_accessor/_project_tools.py``) for the reference caller.

        Args:
            project_id: Project UUID.
            user_id: Authenticated user id (optional; drives field-priority toggles).
            tool: Harness tool (claude-code / codex / gemini / antigravity).
            execution_mode: Resolved execution_mode the CALLER must persist onto the
                project pre-launch via ``mark_staged`` (claude_code_cli / codex_cli /
                gemini_cli / multi_terminal / antigravity_cli) -- this method itself no
                longer writes it.

        Returns:
            dict with ``orchestrator_id``, ``agent_id``, ``execution_id``,
            ``prompt``, ``estimated_prompt_tokens``, ``launch_commands``.

        Raises:
            ValueError: If the project or its product is not found.
        """
        result = await self.generate(project_id=project_id, user_id=user_id, tool=tool)

        staging_prompt = await self.generate_staging_prompt(
            orchestrator_id=result["orchestrator_id"],
            project_id=project_id,
            agent_id=result.get("agent_id"),  # WHO - executor id for MCP tool calls
            tool=tool,
        )
        staging_tokens = len(staging_prompt) // 4

        # INF-6049c: multi_terminal staging carries the per-agent launch_commands for
        # any agents the orchestrator has already spawned (empty at first staging,
        # before a team exists). Other modes run one terminal -> no array.
        launch_commands: list[dict] = []
        if execution_mode == "multi_terminal":
            agents = await self._fetch_launchable_agents(project_id)
            await self._resolve_agent_cli_tools(agents, execution_mode=execution_mode)
            launch_commands = self._launch_commands_for(agents)

        return {
            "orchestrator_id": result["orchestrator_id"],
            "agent_id": result.get("agent_id"),
            # BE-9332: the AgentExecution row id. Both REST prompt endpoints already put
            # it on the orchestrator:prompt_generated wire payload, and the frontend
            # route reads it onto the job row (it is also upsertJob's first
            # existing-row lookup). The MCP caller could not emit it because stage()
            # dropped it here — generate() has always returned it.
            "execution_id": result.get("execution_id"),
            "prompt": staging_prompt,
            "estimated_prompt_tokens": staging_tokens,
            "launch_commands": launch_commands,
        }

    async def implement(
        self, project_id: str, user_id: str | None = None, detected_harness: str | None = None
    ) -> dict[str, Any]:
        """Shared implementation-prompt core (INF-6049b).

        The single generation path behind BOTH ``GET /api/prompts/implementation``
        and the ``implement_project`` MCP tool. Enforces the SACRED human gate via
        the shared ``ProjectStagingService.check_implementation_allowed`` (never
        sets ``implementation_launched_at``; no bypass), then assembles the prompt
        inputs (orchestrator + spawned agents + git toggle) and delegates to the
        existing ``generate_implementation_prompt`` engine.

        ``detected_harness`` (BE-9099) is the session-detected harness token
        (claude-code / codex / gemini / antigravity / opencode / generic, else None),
        resolved by the caller from the MCP session's clientInfo (``_detected_harness``).
        For a SUBAGENT-family election it drives the DETECTED-beats-declared builder
        upgrade via ``effective_harness`` — a detected CLI gets its native builder; the
        generic floor / opencode / undetected get the harness-neutral subagent builder.
        None (the REST copy-paste path, which has no MCP session) resolves to the
        harness-neutral subagent builder for subagent mode. It NEVER affects a
        multi_terminal election (mode-fixed render).

        Returns:
            dict with ``prompt``, ``orchestrator_job_id`` (the orchestrator's
            agent_id), and ``agent_count``.

        Raises:
            ResourceNotFoundError (404): project not found, or no active orchestrator.
            ValidationError (400): unsupported execution mode, or no agents spawned.
            ImplementationNotReadyError (404): human gate not cleared (staging
                incomplete or Implement not pressed).
        """
        from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
        from giljo_mcp.services.project_staging_service import ProjectStagingService
        from giljo_mcp.services.settings_service import SettingsService

        # 1. Fetch project with tenant filter (eager-load product for git closeout).
        project_stmt = (
            select(Project)
            .options(joinedload(Project.product))
            .where(Project.id == project_id, Project.tenant_key == self.tenant_key)
        )
        project = (await self.db.execute(project_stmt)).scalar_one_or_none()
        if not project:
            raise ResourceNotFoundError(f"Project {project_id} not found or not accessible")

        # BE-9335: a chain member IMPLEMENTS in the chain's mode. This path is the solo
        # Play button, which stays live on a chain member's Jobs tab, so it is reachable
        # by clicking alone — and it read the project column at every site below, which
        # rendered a member in whatever mode it was staged with individually. Resolved
        # ONCE here so the gate, the per-agent tool assignment, the prompt-builder
        # election and the launch-command branch cannot disagree with each other.
        # None (solo path) -> the project column, so solo rendering is unchanged.
        execution_mode = effective_execution_mode(
            project.execution_mode,
            await chain_execution_mode_for_project(self.db, project_id=project_id, tenant_key=self.tenant_key),
        )

        # 2. Validate execution mode. BE-9035a derived this gate from the registry (was
        # a hand-copied tuple that omitted generic_mcp, 400ing every solo generic_mcp
        # project at implement). BE-9035c: use the registry's BOUNDARY set (2 canonical
        # modes + 5 legacy aliases) so the collapsed ``subagent`` mode is supported and a
        # stored legacy row (incl. ``generic_mcp``) never hard-fails at implement.
        if execution_mode not in ACCEPTED_EXECUTION_MODES:
            raise ValidationError(f"Unsupported execution mode: {execution_mode}")

        # 3. SACRED human gate — shared with the REST endpoint, never bypassed.
        ProjectStagingService.check_implementation_allowed(project)

        # 4. Fetch the active orchestrator execution (gate is on the project flags,
        # not transient agent status).
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

        # 5. Fetch spawned agent executions (by spawned_by, with legacy project_id fallback).
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
            # BE-9165 (wall 3): both queries above filter status IN
            # ('waiting','working'), so specialists whose work is already DONE
            # match neither. Distinguish "nothing ever spawned" (the 400 below
            # stays) from "all specialists terminal" — the latter is a valid
            # lifecycle state (work executed outside a staged session) and gets
            # a ready-to-close response instead of the misleading dead end.
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
                }
            raise ValidationError("No agent jobs spawned yet. Please run staging first to create agent jobs.")

        # 6. BE-9103: the orchestrator closeout-commit gate reads the canonical master
        # toggle ALONE (settings integrations.git_integration.enabled). It is decoupled
        # from the git_history CONTEXT toggle — reading commit history != writing commits,
        # so the read-side depth toggle must never gate closeout-commit instructions.
        git_enabled = await SettingsService(self.db, self.tenant_key).git_integration_enabled()

        # 7. INF-6049c: resolve each spawned agent's assigned coding tool BEFORE prompt
        # generation so the per-terminal seed block routes each agent to its tool's
        # variant (Claude -> ToolSearch bootstrap; codex/gemini/antigravity -> plain).
        await self._resolve_agent_cli_tools(agent_executions, execution_mode=execution_mode)

        # 8. Select the implementation prompt builder (BE-9099). The pure resolver applies
        # the DETECTED-beats-declared harness upgrade for subagent-family modes and keeps
        # multi_terminal mode-fixed (byte-parity), so 'multi_terminal_orchestrator' is
        # UNREACHABLE from a subagent election. Step 2 already validated execution_mode
        # against ACCEPTED_EXECUTION_MODES. resolved_harness seeds the neutral builder's
        # registry-sourced spawn prose (None for multi_terminal).
        prompt_type, resolved_harness = select_implementation_prompt_type(execution_mode, detected_harness)
        prompt = self.generate_implementation_prompt(
            prompt_type=prompt_type,
            resolved_harness=resolved_harness,
            orchestrator_id=orchestrator_execution.job_id,
            project=project,
            agent_jobs=agent_executions,
            git_enabled=git_enabled,
        )

        # 9. INF-6049c: multi_terminal carries the structured per-agent launch_commands
        # (advisory; the driving agent / user runs them locally). Other modes run a
        # single terminal, so the array is empty.
        launch_commands: list[dict] = []
        if execution_mode == "multi_terminal":
            launch_commands = self._launch_commands_for(agent_executions)

        return {
            "prompt": prompt,
            # BE-6182: return the orchestrator's JOB id (the field is *_job_id and
            # every consumer — closeout readiness, report_progress, the conductor's
            # advance loop — keys off the job_id). Previously returned .agent_id,
            # which broke get_job_mission/report_progress with "job not found" on the
            # SOLO implement path (the chain endpoint independently re-resolves the
            # correct job_id, so it was already correct). job_id and agent_id are both
            # always-populated on an orchestrator execution; this is a strict fix.
            "orchestrator_job_id": orchestrator_execution.job_id,
            "agent_count": len(agent_executions),
            "launch_commands": launch_commands,
        }
