# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.branding import MCP_ALIAS
from giljo_mcp.platform_registry import Platform
from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line
from giljo_mcp.services.protocol_sections.orchestrator_body import render_capability_ladder


_PREFIX = f"mcp__{MCP_ALIAS}__"

_AGENT_SEED_TOOLS = (
    f"{_PREFIX}health_check",
    f"{_PREFIX}get_job_mission",
    f"{_PREFIX}report_progress",
    f"{_PREFIX}complete_job",
)

_TOOLSEARCH_HARNESS_TOOLS = frozenset({"claude", "claude-code"})


def build_agent_seed_lines(cli_tool: str, job_id: str) -> list[str]:
    lines: list[str] = []
    is_claude = (cli_tool or "claude") in _TOOLSEARCH_HARNESS_TOOLS
    if is_claude:
        lines.append('ToolSearch(query="select:' + ",".join(_AGENT_SEED_TOOLS) + '", max_results=10)')
        lines.extend(
            [
                f"{_PREFIX}health_check()",
                f'{_PREFIX}get_job_mission(job_id="{job_id}")',
            ]
        )
    else:
        lines.extend(
            [
                "health_check()",
                f'get_job_mission(job_id="{job_id}")',
            ]
        )
    lines.append("# Execute the returned mission. Report via report_progress; complete_job when done.")
    return lines


def _project_title(project) -> str:
    has_taxonomy = bool(getattr(project, "project_type_id", None) or getattr(project, "series_number", None))
    if has_taxonomy:
        return f"{project.taxonomy_alias} {project.name}"
    return project.name


class MultiTerminalPromptBuilder:

    def build_execution_prompt(
        self,
        orchestrator_id: str,
        project,
        agent_jobs: list,
        git_enabled: bool = False,
        tool: str = "multi_terminal",
        preset: Platform | None = None,
    ) -> str:
        lines = [
            "# GiljoAI Implementation Phase - Orchestrator",
            "",
        ]
        if tool == "claude-code":
            lines.extend(
                [
                    "## STEP 0: TOOLSEARCH BOOTSTRAP (Claude Code only — first action)",
                    "",
                    "Claude Code defers MCP tool schemas behind `ToolSearch`. Before health_check,",
                    "fire this single call to load the canonical orchestrator tool set:",
                    "```",
                    render_toolsearch_call_one_line(),
                    "```",
                    "",
                ]
            )
        health_check_call = f"{_PREFIX}health_check()" if tool == "claude-code" else "health_check()"
        get_job_mission_call = (
            f'{_PREFIX}get_job_mission(job_id="{orchestrator_id}")'
            if tool == "claude-code"
            else f'get_job_mission(job_id="{orchestrator_id}")'
        )
        lines.extend(
            [
                "## FIRST ACTION (MANDATORY)",
                "Verify MCP connection:",
                "```",
                health_check_call,
                "```",
                "",
                f"You are the ORCHESTRATOR for project '{_project_title(project)}'.",
                f"Job ID: `{orchestrator_id}` | Project ID: `{project.id}`",
                "",
                "Call `get_job_mission` to receive your current team state and operating protocol:",
                "```",
                get_job_mission_call,
                "```",
            ]
        )
        seed_block = self._build_agent_seed_block(agent_jobs, tool, preset=preset)
        if seed_block:
            lines.extend(["", seed_block])
        return "\n".join(lines)

    def _build_agent_seed_block(self, agent_jobs: list, tool: str, preset: Platform | None = None) -> str:
        if not agent_jobs:
            return ""
        if preset is not None:
            return self._build_agent_seed_block_preset(agent_jobs, preset)
        out = [
            "## PER-SESSION AGENT SEED (one NEW SESSION per agent)",
            "",
            "Open a NEW SESSION with your AI — a new conversation, tab, or terminal window — and",
            "paste its block. Each agent self-fetches its mission on boot — no mission text is",
            "baked in. The initiation protocol is: connect MCP -> health_check ->",
            "get_job_mission(job_id) -> execute the returned mission.",
        ]
        for job in agent_jobs:
            display = getattr(job, "agent_display_name", None) or "agent"
            job_id = getattr(job, "job_id", "")
            cli_tool = getattr(job, "cli_tool", None) or "claude"
            out.extend(["", f"### Session: {display} (tool: {cli_tool})", "```"])
            out.extend(build_agent_seed_lines(cli_tool, job_id))
            out.append("```")
        return "\n".join(out)

    def _build_agent_seed_block_preset(self, agent_jobs: list, preset: Platform) -> str:
        out = [
            "## PER-SESSION AGENT SEED (one NEW SESSION per agent)",
            "",
            "Open a NEW SESSION with your AI (a new conversation / tab / window) for each agent",
            "below and paste its block. Each agent self-fetches its mission on boot — no mission",
            "text is baked in. The initiation protocol is: connect MCP -> health_check ->",
            "get_job_mission(job_id) -> execute the returned mission.",
        ]
        if not preset.has_shell:
            out.extend(
                [
                    "",
                    "NOTE (chat harness): a code-WRITING job needs a session that HAS an execution",
                    "environment (tools) — open one for it. Planning / analysis / PM jobs proceed in",
                    "any session.",
                ]
            )
        for job in agent_jobs:
            display = getattr(job, "agent_display_name", None) or "agent"
            job_id = getattr(job, "job_id", "")
            cli_tool = getattr(job, "cli_tool", None) or "claude"
            out.extend(["", f"### Session: {display} (tool: {cli_tool})", "```"])
            out.extend(build_agent_seed_lines(cli_tool, job_id))
            out.append("```")
        return render_capability_ladder(
            preferred="\n".join(out),
            fallback=(
                "If you cannot open a separate session per agent, work the agent jobs yourself one at\n"
                "a time in THIS session: for each, get_job_mission(job_id) -> do the work ->\n"
                "complete_job, in the order listed above."
            ),
            floor_user_line=(
                "Open a new AI session (tab / window / conversation) for each agent block above and "
                "paste it, or ask me to run them one at a time."
            ),
            preset_display=preset.display_label,
        )
