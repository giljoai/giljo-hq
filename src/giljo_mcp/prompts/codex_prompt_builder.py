# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.prompts.default_agent_ladder import MISSING_AGENT_TEMPLATES_NOTICE
from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase


class CodexPromptBuilder(ExecutionPromptBuilderBase):

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
        lines = [
            "## How to Spawn Agents via Codex spawn_agent",
            "",
            "### CRITICAL: the role comes from the server, not from your disk",
            "get_job_mission returns this agent's role instructions in agent_identity and its",
            "agent_profile: role, description, model and effort hints, rules and success criteria.",
            "There is no agent file to install, look up, or keep in sync.",
            "",
            "### Prefer the tenant's own agent; fall back to the default agent",
            "- NEVER use agent='worker', agent='implementer', agent='tester', or any unprefixed name",
            "  while a gil-* agent resolves — built-in Codex roles shadow unprefixed names",
            "- If no gil-* agent resolves, do NOT stop: spawn Codex's DEFAULT subagent for that",
            f'  job and say so once — "{MISSING_AGENT_TEMPLATES_NOTICE}"',
            "- DO NOT re-explain the agent's role in instructions= (the agent_profile handles this)",
            "- DO NOT override the profile with lengthy instruction text",
            "",
            "### Always use 'gil-' prefix",
            "The server returns agent_name WITHOUT the prefix. You MUST prepend 'gil-'.",
            "Built-in Codex roles shadow unprefixed names.",
            "",
            "### Spawning Template",
            "```",
            "spawn_agent(",
            '    agent="gil-{agent_name}",  # role arrives from get_job_mission, not a local file',
            '    instructions="""<that agent\'s launch prompt from Launch Prompts below, verbatim>""",',
            ")",
            "```",
            "Keep instructions= to that launch prompt alone \u2014 it names the job_id and the mission fetch call.",
            "",
        ]

        return lines
