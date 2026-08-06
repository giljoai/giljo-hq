# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Claude Code CLI execution prompt builder.

Extracted from ThinClientPromptGenerator (Handover 0950g).
Refactored to inherit from ExecutionPromptBuilderBase (quality-sprint-002e).
"""

from giljo_mcp.branding import MCP_ALIAS
from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line
from giljo_mcp.prompts.execution_prompt_base import ExecutionPromptBuilderBase


# BE-9275b: single module-level constant derived from MCP_ALIAS, reused across
# the many f-strings below instead of a fresh hardcoded tool-prefix literal.
_PREFIX = f"mcp__{MCP_ALIAS}__"


class ClaudePromptBuilder(ExecutionPromptBuilderBase):
    """Builds Claude Code CLI execution prompts for the implementation phase."""

    @property
    def platform_name(self) -> str:
        return "Claude Code CLI Mode"

    def _build_context_recap(self, orchestrator_id: str, project, agent_jobs: list) -> list[str]:
        """Claude Code variant prepends a ToolSearch bootstrap step.

        CE-0033 Task 5: Claude Code defers MCP tool schemas behind ToolSearch.
        Without this step, the orchestrator pays multi-round-trip bootstrap
        cost loading each tool schema piecemeal mid-protocol. One ToolSearch
        call with the canonical orchestrator tool list collapses that to a
        single round-trip — and it has to fire BEFORE health_check, so the
        hint must live in the spawn prompt, not in get_staging_instructions
        (which is unreachable until ToolSearch loads its schema).
        """
        base = super()._build_context_recap(orchestrator_id, project, agent_jobs)
        bootstrap = [
            "## STEP 0: TOOLSEARCH BOOTSTRAP (Claude Code only — first action)",
            "",
            "Claude Code defers MCP tool schemas behind `ToolSearch`. You CANNOT call",
            f"any `{_PREFIX}*` tool until its schema is loaded. Before health_check,",
            "before anything else, fire this single call:",
            "",
            "```",
            render_toolsearch_call_one_line(),
            "```",
            "",
            "After that single call, every tool in the canonical orchestrator set is",
            "callable. Skip this and you'll spend extra round-trips loading schemas",
            "piecemeal mid-protocol.",
            "",
            "---",
            "",
        ]
        # Insert bootstrap immediately after the header (first 3 lines: title, blank, "## Who You Are" etc.)
        # The header is line 0; we splice bootstrap between header and "## Who You Are" so it reads as Step 0.
        header_end = 0
        for idx, line in enumerate(base):
            if line.startswith("## Who You Are"):
                header_end = idx
                break
        return base[:header_end] + bootstrap + base[header_end:]

    def _build_execution_plan_details(self) -> list[str]:
        """Claude includes extra detail about what the plan contains."""
        return [
            "This returns your plan with:",
            "- Agent execution order (sequential/parallel/hybrid)",
            "- Dependency graph between agents",
            "- Coordination checkpoints",
            "- Success criteria for each phase",
            "",
            "Follow this plan to coordinate agents.",
            "",
        ]

    def _build_agent_list_preamble(self) -> list[str]:
        return [
            "Below are the specialist agents spawned during staging.",
            "Each has a unique job_id and agent_display_name.",
            "",
        ]

    def _build_agent_name_line(self, agent) -> str:
        return f"   - Agent Name: `{agent.agent_name}` (matches .claude/agents/{agent.agent_name}.md)"

    def _build_execution_directive_text(self) -> list[str]:
        return [
            "After fetching your mission, you MUST invoke every agent listed above.",
            "Do NOT skip agents. Do NOT summarize the plan and stop. Your job is to",
            "launch each agent using the Task tool as shown below, monitor their progress,",
            "and close out the project when all agents are complete.",
            "",
            "**Preferred mode: background execution.** Launch independent agents with",
            "`run_in_background=true` so the user can continue interacting while agents work.",
            "Poll progress via `get_workflow_status()`. Use foreground (default) only when",
            "one agent's output is needed before the next can start.",
            "",
        ]

    def _build_spawning_section(self, agent_jobs: list) -> list[str]:
        """Build Task tool spawning template section."""
        lines = [
            "## How to Spawn Agents via Task Tool",
            "",
            "### Spawning Template",
            "Use this exact syntax to spawn each agent in parallel:",
            "",
            "```python",
            "Task(",
            '    subagent_type="{agent_name}",  # CRITICAL: Use agent_name (template filename)',
            '    instructions="""',
            "    You are {agent_name} (job_id: {job_id})",
            "    ",
            f'    First action: Call {_PREFIX}get_job_mission(job_id="{{job_id}}")',
            "    This returns your `mission` and `full_protocol`.",
            "    Follow `full_protocol` for all lifecycle behavior",
            "    (startup, planning, progress, messaging, completion, error handling).",
            '    """',
            ")",
            "```",
            "",
        ]

        if agent_jobs:
            first = agent_jobs[0]
            lines.extend(
                [
                    "### Example: First Agent",
                    "```python",
                    "Task(",
                    f'    subagent_type="{first.agent_name}",',
                    '    instructions="""',
                    f"    You are {first.agent_name} (job_id: {first.job_id})",
                    "    ",
                    f'    First action: Call {_PREFIX}get_job_mission(job_id="{first.job_id}")',
                    "    This returns your `mission` and `full_protocol`.",
                    "    Follow `full_protocol` for all lifecycle behavior",
                    "    (startup, planning, progress, messaging, completion, error handling).",
                    '    """',
                    ")",
                    "```",
                    "",
                    "**Task Tool Parameter Naming**:",
                    "- Task(subagent_type=X) uses agent_name value",
                    "- agent_name: Template filename (e.g., 'implementer-backend')",
                    "- Do NOT use agent_display_name (e.g., 'implementer') - it will fail",
                    "",
                    "### Spawning Strategy",
                    "**Spawning Mode**: Use foreground (default) when you need to observe agent output in real-time. Use `run_in_background=true` for independent parallel agents — poll status via `get_workflow_status()`. Background execution is fully supported and reliable.",
                    "",
                    "Choose spawning approach based on job requirements:",
                    "- **Sequential**: Spawn one agent, wait for completion, then next (best for dependent tasks)",
                    "- **Parallel**: Multiple Task() calls in single message (best for independent tasks)",
                    "",
                    "Each agent runs independently and coordinates via MCP server.",
                    "",
                ]
            )

        return lines

    def _build_extra_sections(self, orchestrator_id: str, project, agent_jobs: list) -> list[list[str]]:
        """Claude has CLI constraints section."""
        return [self._build_cli_constraints_section()]

    def _build_cli_constraints_section(self) -> list[str]:
        """Build the CLI mode constraints section (Claude-only)."""
        return [
            "## CLI Mode Constraints",
            "",
            "**WARNING: Agent Template Files Required**",
            "- Each agent_name needs a file: `.claude/agents/{agent_name}.md`",
            '- If file is missing: "Subagent type not found" error',
            '- Example: agent_name="<agent_name>" requires `.claude/agents/<agent_name>.md`',
            "",
            "**WARNING: Exact Naming Required**",
            "- Task tool parameter `subagent_type` expects `agent_name`, NOT `agent_display_name`",
            "- agent_name: Template filename (see allowed_agent_names in instructions)",
            '- agent_display_name: Display category (e.g., "implementer")',
            '- Using agent_display_name will fail with "Subagent type not found"',
            "",
            "**WARNING: MCP Communication Only**",
            "- All agents run in THIS terminal (Claude Code CLI mode)",
            "- Coordination happens via MCP server (not direct communication)",
            "",
        ]

    def _build_completion_section(
        self, orchestrator_id: str, project, agent_jobs: list, git_enabled: bool
    ) -> list[str]:
        """Build extended completion section with CLOSEOUT_BLOCKED recovery (Claude-specific)."""
        git_closeout_lines = self._build_git_closeout_lines(project, git_enabled)

        return [
            "## When You're Done",
            "",
            "### Verify Sub-Agents Completed",
            f"1. Check all agents via {_PREFIX}get_workflow_status()",
            "2. Ensure all have status='complete' (no failures or blockers)",
            "3. Review final deliverables",
            "",
            "### If Agents Are NOT Complete (CLOSEOUT_BLOCKED Recovery)",
            "",
            "If `get_workflow_status()` shows agents not in 'complete', 'closed', or 'decommissioned' status,",
            "you MUST resolve them before closeout. For each non-complete agent:",
            "",
            "1. **Drain their messages:**",
            f'   `{_PREFIX}get_thread_history(thread_id=<your coordination thread>, as_participant="<their_agent_id>", unread_only=true, mark_read=true)`',
            "   Record any important content for the 360 Memory summary.",
            "",
            "2. **Process incomplete todos** — mark remaining items as completed or skipped:",
            "   ```python",
            f"   {_PREFIX}report_progress(",
            '       job_id="<their_job_id>",',
            "       todo_items=[",
            '           ...keep completed items as "completed",',
            '           ...mark remaining pending/in_progress items as "skipped"',
            "       ]",
            "   )",
            "   ```",
            '   NOTE: This will fail on agents already in "complete" status. If it fails, skip this step.',
            "",
            "3. **Force-complete the agent** (ONLY if NOT already 'complete'):",
            "   ```python",
            f"   {_PREFIX}complete_job(",
            '       job_id="<their_job_id>",',
            '       result={"summary": "Force-completed by orchestrator during closeout.", "status": "force_completed"}',
            "   )",
            "   ```",
            '   Do NOT call complete_job() on agents already in "complete" status.',
            "",
            "Skip agents in status 'closed' or 'decommissioned'.",
            "After all agents are resolved, proceed with closeout below.",
            "",
            *git_closeout_lines,
            "### Complete Your Orchestrator Job",
            "When all sub-agents are done and project is complete:",
            "```python",
            f'{_PREFIX}complete_job(job_id="{orchestrator_id}")',
            "```",
            "",
            "### Handover (if needed)",
            "If you reach context limits before completion:",
            "- Use the Hand Over button in the UI to reset your context",
            "- Your session context will be saved to 360 Memory",
            "- You'll receive a continuation prompt to continue work",
            "",
        ]
