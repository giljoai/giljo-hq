# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    executor_id = agent_id or job_id

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

    todo_phrase = task_list_phrase(tool)

    phase1_step4 = (
        f"5. **MANDATORY: Create your {todo_phrase}** (BEFORE implementation):\n"
        "   - Break mission into 3-7 specific, actionable tasks\n"
        '   - Count and announce: "X steps to complete: [list items]"\n'
        "   - NEVER skip this step - planning prevents poor execution"
    )

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
