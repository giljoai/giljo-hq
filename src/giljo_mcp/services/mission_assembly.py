# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import hashlib
from typing import Any

from giljo_mcp.models import AgentExecution, AgentJob
from giljo_mcp.platform_registry import (
    EXECUTION_MODE_TO_TOOL,
    HARNESS_CLI_TOOL_TYPES,
    Platform,
    effective_harness,
)
from giljo_mcp.prompts.launch_command_synth import normalize_hint
from giljo_mcp.schemas.responses.orchestration import (
    IDENTITY_RESOLVED,
    IDENTITY_TEMPLATE_UNBOUND,
    IDENTITY_TEMPLATE_UNRESOLVED,
)
from giljo_mcp.schemas.service_responses import MissionResponse
from giljo_mcp.services.execution_mode_gate import effective_execution_mode
from giljo_mcp.services.protocol_builder import (
    _generate_agent_protocol,
    _generate_team_context_header,
)
from giljo_mcp.services.protocol_survival import compute_next_required_actions


_EXECUTION_MODE_TO_TOOL = EXECUTION_MODE_TO_TOOL


def compute_is_chain_conductor(chain_execution_mode: str | None, project_id: Any) -> bool:
    return bool(chain_execution_mode) and not project_id


_UNRESOLVED_IDENTITY_BLOCK = """You are running WITHOUT a role identity. {cause}, so no role
instructions, behavioral rules or success criteria could be loaded for you.

Work your mission literally and conservatively — you have no role framing to lean on. Where the
protocol tells you to take your role "from your activated agent template", you have none: use your
display name '{display_name}' as your `from_agent` value instead.

This is a degradation, not a stop. Keep working your mission, and report it once via
report_progress (or post_to_thread) so whoever spawned you can {remedy}."""


def compose_template_identity(identity_template: Any, execution: AgentExecution) -> str:
    role_label = (identity_template.role or execution.agent_name or "agent").upper()
    identity_parts = [
        f"You are {role_label}. The following defines your expertise, "
        f"behavioral constraints, and success criteria. "
        f"Internalize these as your operating identity.\n"
    ]

    if identity_template.user_instructions:
        identity_parts.append(identity_template.user_instructions)

    rules = identity_template.behavioral_rules
    if isinstance(rules, list) and len(rules) > 0:
        identity_parts.append("\n## Behavioral Rules\n" + "\n".join(f"- {r}" for r in rules))

    criteria = identity_template.success_criteria
    if isinstance(criteria, list) and len(criteria) > 0:
        identity_parts.append("\n## Success Criteria\n" + "\n".join(f"- {c}" for c in criteria))

    return "\n\n".join(identity_parts)


def compose_agent_profile(template: Any) -> dict[str, Any] | None:
    if template is None:
        return None
    return {
        "template_id": getattr(template, "id", None),
        "name": getattr(template, "name", None),
        "role": getattr(template, "role", None),
        "description": getattr(template, "description", None) or "",
        "harness": getattr(template, "cli_tool", None) or "claude",
        "model": normalize_hint(getattr(template, "model", None)),
        "effort": normalize_hint(getattr(template, "effort", None)),
        "instructions": getattr(template, "user_instructions", None) or "",
        "behavioral_rules": list(getattr(template, "behavioral_rules", None) or []),
        "success_criteria": list(getattr(template, "success_criteria", None) or []),
    }


def compose_unresolved_identity(job: AgentJob, execution: AgentExecution) -> tuple[str, str]:
    display_name = execution.agent_display_name or execution.agent_name or "agent"
    requested = execution.agent_name or display_name
    if getattr(job, "template_id", None):
        cause = f"The agent template this job was created against ('{requested}') has been DELETED"
        remedy = "restore that agent from the trash, or re-spawn this work against a live agent"
        status = IDENTITY_TEMPLATE_UNRESOLVED
    else:
        cause = f"This job was never bound to an agent template ('{requested}' resolved to none)"
        remedy = "re-spawn this work against an agent that exists"
        status = IDENTITY_TEMPLATE_UNBOUND
    return _UNRESOLVED_IDENTITY_BLOCK.format(cause=cause, display_name=display_name, remedy=remedy), status


def should_serve_identity(identity_status: str, execution_mode: Any) -> bool:
    del identity_status, execution_mode
    return True


def _apply_identity_serve_gate(
    logger,
    job_id: str,
    agent_identity: str | None,
    identity_status: str,
    protocol_exec_mode: Any,
) -> str | None:
    del logger, job_id
    if should_serve_identity(identity_status, protocol_exec_mode):
        return agent_identity
    return None  # pragma: no cover - unreachable while should_serve_identity is constant


def gate_identity_source(served_identity: str | None, identity_source: str | None) -> str | None:
    return identity_source if served_identity else None


def compute_protocol_etag(agent_identity: str | None, full_protocol: str | None) -> str:
    static_block = (agent_identity or "") + "\x00" + (full_protocol or "")
    return hashlib.sha256(static_block.encode("utf-8")).hexdigest()


def _maybe_inject_ch6(
    full_protocol: str,
    execution: AgentExecution,
    protocol_exec_mode: str,
    project: Any,
    checkin_cadence_minutes: int | None,
) -> str:
    if execution.agent_display_name != "orchestrator" or protocol_exec_mode != "multi_terminal":
        return full_protocol
    from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch6_auto_checkin

    interval = checkin_cadence_minutes
    if interval is None:
        has_override = project is not None and getattr(project, "auto_checkin_enabled", False)
        interval = getattr(project, "auto_checkin_interval", 10) if has_override else 10
    return full_protocol + "\n" + _build_ch6_auto_checkin(interval, for_conductor=project is None)


def assemble_mission_context(
    logger,
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
    comm_chat_id: str | None = None,
    detected_harness: str | None = None,
    checkin_cadence_minutes: int | None = None,
    identity_status: str = IDENTITY_RESOLVED,
    identity_source: str | None = None,
    agent_profile: dict[str, Any] | None = None,
) -> MissionResponse:
    job_id = job.job_id

    project_exec_mode = getattr(project, "execution_mode", "multi_terminal") if project else "multi_terminal"
    is_multi_terminal_specialist = (
        execution.agent_display_name != "orchestrator" and project_exec_mode == "multi_terminal"
    )

    team_context_header = _generate_team_context_header(
        execution,
        all_project_executions,
        mission_lookup=mission_lookup,
        include_team_table=not is_multi_terminal_specialist,
    )
    raw_mission = job.mission or ""
    mission_framing = (
        "This is your assigned work order. Execute the following tasks "
        "within the scope and team structure defined below.\n\n"
    )
    full_mission = mission_framing + team_context_header + raw_mission

    integrations = integrations or {}
    include_serena = integrations.get("serena_mcp", {}).get("use_in_prompts", False)

    if include_serena:
        try:
            from giljo_mcp.prompt_generation.serena_instructions import for_role

            role = job.job_type
            serena_instructions = for_role(role, enabled=True)
            full_mission = serena_instructions + "\n\n---\n\n" + full_mission
            logger.info(
                "[SERENA] Injected role-specific Serena guidance into agent mission",
                extra={"job_id": job_id, "agent_id": execution.agent_id, "role": role},
            )
        except (ImportError, AttributeError) as e:
            logger.warning(f"[SERENA] Failed to inject Serena guidance: {e}")

    git_enabled = integrations.get("git_integration", {}).get("enabled", False)
    protocol_exec_mode = effective_execution_mode(project_exec_mode, chain_execution_mode)
    agent_tool = _EXECUTION_MODE_TO_TOOL.get(protocol_exec_mode, "multi_terminal")
    is_chain_conductor = compute_is_chain_conductor(chain_execution_mode, job.project_id)
    render_tool = agent_tool
    resolved_harness = effective_harness(protocol_exec_mode, {"harness": detected_harness})
    if resolved_harness in HARNESS_CLI_TOOL_TYPES:
        render_tool = resolved_harness
    full_protocol = _generate_agent_protocol(
        job_id=job_id,
        tenant_key=tenant_key,
        agent_name=execution.agent_display_name,
        agent_id=str(execution.agent_id),
        execution_mode=agent_tool,
        git_integration_enabled=git_enabled,
        job_type=job.job_type,
        tool=render_tool,
        is_chain_conductor=is_chain_conductor,
        preset=preset,
        comm_thread_id=comm_thread_id,
    )

    full_protocol = _maybe_inject_ch6(full_protocol, execution, protocol_exec_mode, project, checkin_cadence_minutes)

    if is_multi_terminal_specialist:
        from giljo_mcp.services.protocol_sections.chapters_coordination import (
            _build_ch_messaging,
            _build_ch_team,
        )

        full_protocol += "\n" + _build_ch_team(current_team_state)
        full_protocol += "\n" + _build_ch_messaging()

    if job.job_type != "orchestrator":
        phase_for_response = None
    elif project is not None:
        phase_for_response = "implementation" if project.implementation_launched_at is not None else "staging"
    else:
        phase_for_response = getattr(execution, "project_phase", None)
    next_required_actions = compute_next_required_actions(
        job_type=job.job_type,
        phase=phase_for_response,
        is_chain_member=bool(chain_execution_mode) and bool(job.project_id),
        is_chain_conductor=is_chain_conductor,
    )
    served_identity = _apply_identity_serve_gate(logger, job_id, agent_identity, identity_status, protocol_exec_mode)
    return MissionResponse(
        job_id=job.job_id,
        agent_id=execution.agent_id,
        agent_name=execution.agent_display_name,
        agent_display_name=execution.agent_display_name,
        agent_identity=served_identity,
        identity_status=identity_status,
        identity_source=gate_identity_source(served_identity, identity_source),
        agent_profile=agent_profile,
        mission=full_mission,
        project_id=str(job.project_id) if job.project_id else None,
        thread_id=comm_thread_id,
        chat_id=comm_chat_id,
        parent_job_id=str(execution.spawned_by) if execution.spawned_by else None,
        status=execution.status,
        created_at=job.created_at.isoformat() if job.created_at else None,
        started_at=execution.started_at.isoformat() if execution.started_at else None,
        thin_client=True,
        full_protocol=full_protocol,
        current_team_state=current_team_state,
        project_phase=phase_for_response,
        next_required_actions=next_required_actions,
    )
