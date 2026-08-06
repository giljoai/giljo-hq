# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Multi-terminal (platform-agnostic) orchestrator prompt builder.

Extracted from CodexPromptBuilder (Handover 0950 orchestrator fix).
Builds the thinnest possible implementation prompt — identity + single
instruction to call get_job_mission(). All behavioral protocol lives
server-side.
"""

from giljo_mcp.branding import MCP_ALIAS
from giljo_mcp.platform_registry import Platform
from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line
from giljo_mcp.services.protocol_sections.orchestrator_body import render_capability_ladder


# BE-9275b: derived from the branding constant instead of a fresh literal.
_PREFIX = f"mcp__{MCP_ALIAS}__"

# INF-6049b: the minimal MCP tool schemas an agent terminal needs to boot,
# self-fetch its mission, and report. Kept deliberately small (NOT the full
# orchestrator canonical set) so a seeded agent terminal loads only what it uses.
_AGENT_SEED_TOOLS = (
    f"{_PREFIX}health_check",
    f"{_PREFIX}get_job_mission",
    f"{_PREFIX}report_progress",
    f"{_PREFIX}complete_job",
)

# INF-6049c: coding-tool identifiers whose harness DEFERS MCP tool schemas behind
# ToolSearch (Claude Code). Such an agent needs a single agent-scoped select line
# before its first MCP call; codex/gemini/antigravity load schemas natively and
# skip it. "claude-code" is accepted alongside "claude" for the orchestrator-tool
# vocabulary used by build_execution_prompt.
_TOOLSEARCH_HARNESS_TOOLS = frozenset({"claude", "claude-code"})


def build_agent_seed_lines(cli_tool: str, job_id: str) -> list[str]:
    """Minimal per-agent initiation seed lines for ``cli_tool`` (INF-6049c).

    The single source of truth for an agent terminal's boot protocol — connect
    MCP -> health_check -> get_job_mission(job_id) -> execute. A Claude-Code
    agent additionally gets a leading ToolSearch select (its harness defers MCP
    schemas) that loads the tools under the prefixed names, so its two boot calls
    stay prefixed to match; other tools (Codex/Gemini/unknown) never see that
    prefix in their own tool list, so they get bare names. Shared by the
    human-readable per-terminal seed block AND the structured ``launch_commands``
    synthesis so the two never drift.
    """
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
    """Builds platform-agnostic multi-terminal orchestrator prompts."""

    def build_execution_prompt(
        self,
        orchestrator_id: str,
        project,
        agent_jobs: list,
        git_enabled: bool = False,
        tool: str = "multi_terminal",
        preset: Platform | None = None,
    ) -> str:
        """Build multi-terminal orchestrator implementation prompt (Handover 0830).

        Genuinely thin: identity + single instruction to call get_job_mission().
        All behavioral protocol, team state, and tool catalog live server-side
        in get_job_mission() response — never baked into the prompt.

        CE-0033 Task 5: ``tool`` lets callers opt into a Step 0 ToolSearch
        bootstrap when the operator is running a Claude-Code-style harness
        that defers MCP tool schemas. Default ``"multi_terminal"`` keeps the
        prompt unchanged for platform-neutral / Codex / Gemini operators —
        the bootstrap is noise there.
        """
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
        """Per-terminal agent seed (INF-6049b).

        Multi-terminal launch opens one terminal per spawned agent. Each terminal's
        seed is a MINIMAL initiation protocol — connect MCP -> health_check ->
        get_job_mission(job_id) -> execute — so the agent self-fetches its mission
        on boot instead of having the mission baked into the prompt. No-op when there
        are no spawned agents (e.g. a staging-phase prompt with no team yet), which
        keeps the orchestrator prompt unchanged in that case.

        Shared by the ``implement_project`` MCP tool and the copy-paste REST path —
        both render through this one builder.

        BE-8003f (D3-S2) / BE-8003h (slice 1): both the default and the preset paths now use
        session-neutral container prose ("open a NEW SESSION"; a terminal window kept only as
        an example, never a requirement). ``preset`` no longer gates the wording — it gates the
        ladder wrapping: a preset-active (shell-less) render is additionally wrapped in the
        PREFERRED/FALLBACK/FLOOR ladder, and a chat preset (no execution environment) also gets
        the code-vs-planning note. The seed LINES themselves are unchanged — the boot protocol
        is harness-agnostic.
        """
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
            # INF-6049c: each agent's seed is routed to its OWN assigned coding tool
            # (template cli_tool, attached transiently by the lifecycle; default
            # claude when unset). A Claude agent's seed carries the ToolSearch
            # bootstrap; codex/gemini/antigravity get the plain variant.
            cli_tool = getattr(job, "cli_tool", None) or "claude"
            out.extend(["", f"### Session: {display} (tool: {cli_tool})", "```"])
            out.extend(build_agent_seed_lines(cli_tool, job_id))
            out.append("```")
        return "\n".join(out)

    def _build_agent_seed_block_preset(self, agent_jobs: list, preset: Platform) -> str:
        """Preset-active (shell-less) variant of the agent seed block (BE-8003f, D3-S2).

        Same boot protocol, but the container prose says "NEW SESSION" not "terminal", and
        the whole thing is wrapped in the capability ladder so the orchestrator has a
        floor. A chat preset (no execution environment) also gets the code-vs-planning note.
        """
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
