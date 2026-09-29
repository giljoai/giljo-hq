# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.platform_registry import (
    GENERIC_HARNESS,
    GENERIC_SUBAGENT_SPAWN_SYNTAX,
    get_harness,
)
from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase


class SubagentPromptBuilder(ExecutionPromptBuilderBase):

    def __init__(self, resolved_harness: str | None = None):
        self._resolved_harness = resolved_harness or GENERIC_HARNESS

    @property
    def platform_name(self) -> str:
        return "Subagent Mode"

    def _spawn_syntax(self) -> str:
        harness = get_harness(self._resolved_harness)
        return harness.spawn_syntax if harness is not None else GENERIC_SUBAGENT_SPAWN_SYNTAX

    def _build_agent_name_line(self, agent) -> str:
        return f"   - Agent Name: `{agent.agent_name}` (used as-is when you spawn it)"

    def _build_execution_directive_text(self) -> list[str]:
        return [
            "After fetching your mission, you MUST invoke every agent listed above.",
            "Do NOT skip agents. Do NOT summarize the plan and stop. Spawn each agent",
            "as a SUBAGENT in THIS session using your harness's own spawn mechanism —",
            "do NOT open a new terminal window or paste a prompt into a separate session.",
            "Monitor their progress and close out the project when all agents are complete.",
            "",
        ]

    def _build_spawning_section(self, agent_jobs: list) -> list[str]:
        lines = [
            "## How to Spawn Agents (subagent mode)",
            "",
            self._spawn_syntax(),
            "",
            "For EACH agent below, spawn it and give it this first instruction:",
            "",
            "```",
            "You are {agent_name} (job_id: {job_id})",
            "",
            'First action: Call get_job_mission(job_id="{job_id}")',
            "This returns your `mission` and `full_protocol`.",
            "Follow `full_protocol` for all lifecycle behavior.",
            "```",
            "",
        ]

        if agent_jobs:
            first = agent_jobs[0]
            lines.extend(
                [
                    "### Example: First Agent",
                    "```",
                    f"You are {first.agent_name} (job_id: {first.job_id})",
                    "",
                    f'First action: Call get_job_mission(job_id="{first.job_id}")',
                    "This returns your `mission` and `full_protocol`.",
                    "Follow `full_protocol` for all lifecycle behavior.",
                    "```",
                    "",
                ]
            )

        return lines
