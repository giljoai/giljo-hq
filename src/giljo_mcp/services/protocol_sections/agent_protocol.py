# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Agent 5-phase lifecycle protocol generation."""

from __future__ import annotations

from giljo_mcp.platform_registry import Platform, task_list_phrase
from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.worker_body import (
    _build_conditional_blocks,
    _build_worker_protocol_body,
)


def _generate_agent_protocol(
    job_id: str,
    tenant_key: str,
    agent_name: str,
    agent_id: str | None = None,
    execution_mode: str = "multi_terminal",
    git_integration_enabled: bool = False,
    job_type: str = "agent",
    tool: str = "multi_terminal",
    is_chain_conductor: bool = False,
    preset: Platform | None = None,
    comm_thread_id: str | None = None,
) -> str:
    """
    Generate the 5-phase agent lifecycle protocol (Handover 0334, 0355, 0358b, 0359, 0378, 0392).

    This protocol is embedded in get_job_mission() response to provide
    CLI subagents with self-documenting lifecycle instructions.

    Handover 0392: Simplified progress reporting - agents now send only todo_items array,
    backend calculates percent/steps automatically. Removed redundant field instructions.

    Handover 0378: Fixed three protocol bugs:
    - Bug 2: Protocol now shows distinct job_id and agent_id values (not both job_id)
    - Bug 4: Added "Sync TodoWrite with MCP Progress" section with explicit instructions

    Handover 0359: Fixed progress format to match backend implementation.
    Protocol now instructs mode="todo", completed_steps, total_steps, current_step
    instead of old steps_completed/steps_total format. This fixes Steps column
    tracking in Jobs table.

    Handover 0355: Enhanced message checking - Phase 2 checks after each task,
    Phase 3 reordered to check before reporting, Phase 4 gates on empty queue,
    plus "When to Check Messages" guidance section.

    Handover 0358b: Added agent_id parameter. In the dual-model architecture:
    - job_id = work order UUID (persists across succession)
    - agent_id = executor UUID (changes on succession)

    Args:
        job_id: Agent job UUID for MCP tool calls (work order)
        tenant_key: Tenant key for MCP tool calls
        agent_name: Agent name (matches template filename)
        agent_id: Optional executor UUID (defaults to job_id for backwards compat)
        comm_thread_id: BE-9012d. The project's bound Hub thread id, resolved by the
            caller (mission_service.get_agent_mission) on the SAME session as the
            render. None renders the worker's "no coordination thread bound"
            degradation. TSK-9459: the ORCHESTRATOR branch now consumes it too --
            it used to be worker-only, which left the orchestrator reading its own
            protocol's ``<your coordination thread>`` as a literal placeholder.

    Returns:
        Multi-line protocol string with 5 phases and MCP tool references
    """
    # Use agent_id if provided, otherwise fall back to job_id (backwards compat)
    executor_id = agent_id or job_id

    # Handover 0830/0851: Orchestrator protocol fork — 3-phase coordination lifecycle
    # BE-5103: thread `tool` through so the multi_terminal FORBIDDEN banner can pick
    # the right CLI-specific forbidden-call line (Task/spawn_agent/@-syntax/generic).
    if job_type == "orchestrator":
        return _generate_orchestrator_protocol(
            job_id,
            tenant_key,
            executor_id,
            execution_mode,
            tool=tool,
            is_chain_conductor=is_chain_conductor,
            preset=preset,
            comm_thread_id=comm_thread_id,
        )

    git_commit_block, giljo_block = _build_conditional_blocks(git_integration_enabled, execution_mode, tool)

    # BE-9260: harness-neutral task-list phrasing ("TodoWrite list" only for the
    # detected claude-code harness; "task list" for everyone else).
    todo_phrase = task_list_phrase(tool)

    # Conditional Phase 1 Step 5: scope the task-list step to job_type. BE-9012d:
    # renumbered from "4." to "5." — the worker body's Phase 1 gained a step 2
    # (join_thread), shifting every subsequent Phase 1 step down by one.
    if job_type == "orchestrator":
        phase1_step4 = (
            f"5. **MANDATORY: Create your {todo_phrase}** (BEFORE coordination):\n"
            "   - Orchestration ONLY: spawning, monitoring, coordinating, unblocking, closing out\n"
            "   - NEVER include implementation, testing, or documentation tasks — those belong to your agents\n"
            '   - Count and announce: "X steps to complete: [list items]"\n'
            "   - NEVER skip this step - planning prevents poor execution"
        )
    else:
        phase1_step4 = (
            f"5. **MANDATORY: Create your {todo_phrase}** (BEFORE implementation):\n"
            "   - Break mission into 3-7 specific, actionable tasks\n"
            '   - Count and announce: "X steps to complete: [list items]"\n'
            "   - NEVER skip this step - planning prevents poor execution"
        )

    # Handover 0825: Framing directive for lifecycle protocol
    protocol_framing = "These are your lifecycle operating procedures. Follow them from startup through completion.\n\n"

    return _build_worker_protocol_body(
        job_id=job_id,
        tenant_key=tenant_key,
        executor_id=executor_id,
        job_type=job_type,
        phase1_step4=phase1_step4,
        git_commit_block=git_commit_block,
        giljo_block=giljo_block,
        protocol_framing=protocol_framing,
        preset=preset,
        comm_thread_id=comm_thread_id,
        tool=tool,
    )
