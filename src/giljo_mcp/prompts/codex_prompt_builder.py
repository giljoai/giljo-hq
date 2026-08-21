# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Codex CLI execution prompt builder.

Extracted from ThinClientPromptGenerator (Handover 0950g).
Refactored to inherit from ExecutionPromptBuilderBase (quality-sprint-002e).
"""

from giljo_mcp.prompts.default_agent_ladder import MISSING_AGENT_TEMPLATES_NOTICE
from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase


class CodexPromptBuilder(ExecutionPromptBuilderBase):
    """Builds Codex CLI execution prompts for the implementation phase."""

    @property
    def platform_name(self) -> str:
        return "Codex CLI Mode"

    def _build_agent_list_preamble(self) -> list[str]:
        return [
            "Below are the specialist agents spawned during staging.",
            "Each has a unique job_id. In Codex CLI, ALL agent names require the 'gil-' prefix.",
            "",
        ]

    def _build_agent_name_line(self, agent) -> str:
        return f"   - Agent Name: `{agent.agent_name}` \u2192 Codex: `gil-{agent.agent_name}`"

    def _build_execution_directive_text(self) -> list[str]:
        return [
            "After fetching your mission, you MUST invoke every agent listed above.",
            "Do NOT skip agents. Do NOT summarize the plan and stop. Your job is to",
            "launch each agent using spawn_agent() as shown below, monitor their progress,",
            "and close out the project when all agents are complete.",
            "",
            "**Preferred mode: background execution.** If spawn_agent supports a background",
            "or async flag, use it for independent agents so the user can continue interacting.",
            "Poll progress via `get_workflow_status()`. Only block on an agent when the next",
            "agent depends on its output.",
            "",
        ]

    def _build_spawning_section(self, agent_jobs: list) -> list[str]:
        """Build Codex spawn_agent spawning template section."""
        lines = [
            "## How to Spawn Agents via Codex spawn_agent",
            "",
            "### CRITICAL: Template-First Spawning",
            "The `agent=` parameter loads an INSTALLED agent template from",
            "`~/.codex/agents/gil-{agent_name}.toml`. This template contains the agent's",
            "developer_instructions, model config, and sandbox settings.",
            "The agent ALREADY KNOWS its role \u2014 you do NOT re-explain it.",
            "",
            "### Prefer the installed template; fall back to the default agent",
            "- NEVER use agent='worker', agent='implementer', agent='tester', or any unprefixed name",
            "  while the gil-* template exists — built-in Codex roles shadow unprefixed names",
            "- If a gil-* template is MISSING, do NOT stop: spawn Codex's DEFAULT subagent for that",
            f'  job and say so once — "{MISSING_AGENT_TEMPLATES_NOTICE}"',
            "- DO NOT re-explain the agent's role in instructions= (the template handles this)",
            "- DO NOT override template behavior with lengthy instruction text",
            "",
            "### Always use 'gil-' prefix",
            "The server returns agent_name WITHOUT the prefix. You MUST prepend 'gil-'.",
            "Built-in Codex roles shadow unprefixed names.",
            "",
            "### Spawning Template",
            "```",
            "spawn_agent(",
            '    agent="gil-{agent_name}",  # loads ~/.codex/agents/gil-{agent_name}.toml',
            '    instructions="""',
            "    You are {agent_name} (job_id: {job_id})",
            "    ",
            '    First action: Call get_job_mission(job_id="{job_id}")',
            "    Note: tenant_key is auto-injected by server from your API key session",
            "    This returns your `mission` and `full_protocol`.",
            "    Follow `full_protocol` for all lifecycle behavior.",
            '    """',
            ")",
            "```",
            "Keep instructions= MINIMAL \u2014 only the job_id and mission fetch call above.",
            "",
        ]

        if agent_jobs:
            first = agent_jobs[0]
            lines.extend(
                [
                    "### Example: First Agent",
                    "```",
                    "spawn_agent(",
                    f'    agent="gil-{first.agent_name}",  # gil- prefix!',
                    '    instructions="""',
                    f"    You are {first.agent_name} (job_id: {first.job_id})",
                    "    ",
                    f'    First action: Call get_job_mission(job_id="{first.job_id}")',
                    "    Note: tenant_key is auto-injected by server from your API key session",
                    "    This returns your `mission` and `full_protocol`.",
                    "    Follow `full_protocol` for all lifecycle behavior.",
                    '    """',
                    ")",
                    "```",
                    "",
                ]
            )

        return lines
