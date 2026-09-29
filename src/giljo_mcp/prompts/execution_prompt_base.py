# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


class ExecutionPromptBuilderBase:

    @property
    def platform_name(self) -> str:
        raise NotImplementedError("Subclasses must define platform_name")

    def build_execution_prompt(self, orchestrator_id: str, project, agent_jobs: list, git_enabled: bool = False) -> str:
        sections = [
            self._build_context_recap(orchestrator_id, project, agent_jobs),
            self._build_agent_list(orchestrator_id, project, agent_jobs),
            self._build_spawning_section(agent_jobs),
            self._build_monitoring_section(project),
            self._build_context_refresh_section(orchestrator_id),
            *self._build_extra_sections(orchestrator_id, project, agent_jobs),
            self._build_completion_section(orchestrator_id, project, agent_jobs, git_enabled),
        ]
        lines = []
        for section in sections:
            lines.extend(section)
        return "\n".join(lines)

    def _build_context_recap(self, orchestrator_id: str, project, agent_jobs: list) -> list[str]:
        return [
            f"# GiljoAI Implementation Phase - {self.platform_name}",
            "",
            "## Who You Are",
            f"You are Orchestrator (job_id: {orchestrator_id}) for project '{project.name}'",
            f"Project ID: {project.id}",
            f"Product ID: {project.product_id}",
            "",
            "## MANDATORY STARTUP — both calls, in order, no skipping",
            "",
            "Tool names below are bare; your MCP client may expose them under a prefix",
            "(e.g. `mcp__<server>__<tool>`) — call them by the names your harness lists.",
            "",
            "**1. Verify MCP connection:**",
            "```python",
            "health_check()",
            "```",
            'Expected: `{"status": "healthy"}`. If failed, STOP and report error.',
            "",
            "**2. Fetch your execution plan AND operating protocol:**",
            "```python",
            f'get_job_mission(job_id="{orchestrator_id}")',
            "```",
            "NOT optional — even if you remember staging from a prior session. This call:",
            "  - transitions you `waiting → working` on the server (skipping leaves you invisible on the dashboard)",
            "  - returns `full_protocol` — the coordination loop, blocker handling, closeout ordering. Without it you WILL get closeout wrong.",
            "  - returns `current_team_state` — LIVE agent statuses. Any memory you have from staging is stale.",
            "",
            "**GATE: before invoking any agent below, `full_protocol` text must be in THIS session's context. If not, you skipped step 2. Go back.**",
            "",
            "If `full_protocol` conflicts with anything else in this prompt, `full_protocol` wins.",
            "EXCEPTION (execution model): the EXECUTION-MODEL instructions in THIS prompt take "
            "precedence over any multi-terminal phrasing in `full_protocol`. If `full_protocol` says to "
            "copy a prompt from the dashboard, paste it into a NEW terminal, or go to another agent's "
            "terminal, IGNORE that — in this session all agents run as subagents in THIS session.",
            "",
            *self._build_execution_plan_details(),
            "## What You've Already Done",
            "In a PREVIOUS session, you completed staging:",
            "- Analyzed project requirements",
            "- Created mission plan",
            f"- Spawned {len(agent_jobs) if agent_jobs else 0} specialist agents",
            "",
            "## Current State",
            "All agent jobs are in waiting status, ready for execution.",
            "Your job now: Spawn and coordinate these agents to complete the project.",
            "---",
            "",
        ]

    def _build_execution_plan_details(self) -> list[str]:
        return [
            "Follow this plan to coordinate agents.",
            "",
        ]

    def _build_agent_list(self, orchestrator_id: str, project, agent_jobs: list) -> list[str]:
        agent_spawn_lines = []
        if agent_jobs:
            for idx, agent in enumerate(agent_jobs, 1):
                mission = getattr(agent.job, "mission", None) or "(No mission assigned)"
                mission_summary = mission[:100] + "..." if len(mission) > 100 else mission

                agent_spawn_lines.extend(
                    [
                        f"**{idx}. {agent.agent_name}**",
                        self._build_agent_name_line(agent),
                        f"   - Agent Type: `{agent.agent_display_name}` (display category)",
                        f"   - Job ID: `{agent.job_id}`",
                        f"   - Status: {agent.status}",
                        f"   - Mission Summary: {mission_summary}",
                        "",
                    ]
                )
        else:
            agent_spawn_lines.append("(No agents spawned yet - use spawn_job() first)")

        return [
            "## Agent Jobs to Execute",
            "",
            *self._build_agent_list_preamble(),
            *agent_spawn_lines,
            "## EXECUTION DIRECTIVE",
            "",
            *self._build_execution_directive_text(),
            "⚠ **NEW agent not listed above (e.g. a deferred tester/reviewer)? `spawn_job` FIRST, then launch.**",
            "The agents above already have MCP jobs. Any agent you add later does NOT — call",
            "`spawn_job(...)` to mint its `job_id` (its dashboard record + audit trail),",
            "then launch it with that `job_id` as its `get_job_mission` first action. Launching a new",
            "agent directly without a `spawn_job` leaves it untracked and unauditable — never do it.",
            "",
        ]

    def _build_agent_list_preamble(self) -> list[str]:
        return [
            "Below are the specialist agents spawned during staging.",
            "",
        ]

    def _build_agent_name_line(self, agent) -> str:
        return f"   - Agent Name: `{agent.agent_name}`"

    def _build_execution_directive_text(self) -> list[str]:
        return [
            "After fetching your mission, you MUST invoke every agent listed above.",
            "Do NOT skip agents. Do NOT summarize the plan and stop. Your job is to",
            "launch each agent, monitor their progress,",
            "and close out the project when all agents are complete.",
            "",
        ]

    def _build_spawning_section(self, agent_jobs: list) -> list[str]:
        raise NotImplementedError("Subclasses must implement _build_spawning_section")

    def _build_monitoring_section(self, project) -> list[str]:
        return [
            "## Monitoring Agent Progress",
            "",
            "### get_workflow_status()",
            "Check all agent statuses:",
            "```python",
            f'get_workflow_status(project_id="{project.id}")',
            "```",
            "",
        ]

    def _build_context_refresh_section(self, orchestrator_id: str) -> list[str]:
        return [
            "## Refreshing Your Context",
            "",
            "If you need to re-read your orchestrator mission:",
            "```python",
            f'get_staging_instructions(job_id="{orchestrator_id}")',
            "```",
            "",
        ]

    def _build_extra_sections(self, orchestrator_id: str, project, agent_jobs: list) -> list[list[str]]:
        return []

    def _build_git_closeout_lines(self, project, git_enabled: bool) -> list[str]:
        if not git_enabled:
            return []
        tag = getattr(project, "taxonomy_alias", None) or project.name
        return [
            "### Git Closeout Commit",
            "**Committer of last resort:** BEFORE closeout, check the working tree "
            "(`git status --short`). If it is DIRTY with this project's work — a worker that "
            "did not commit, or your own residue — commit those files "
            "(`git add <the specific changed files>`; NEVER `git add -A`):",
            "```bash",
            f'git commit -m "{tag}: <what these changes do>"',
            "```",
            "Pass this project's commits (yours and your workers') as `git_commits` to "
            "`write_project_closeout`. Never create an empty commit to have something to pass: "
            'if the project changed no code, pass `no_code_changes="<why>"` instead.',
            "",
        ]

    def _build_completion_section(
        self, orchestrator_id: str, project, agent_jobs: list, git_enabled: bool
    ) -> list[str]:
        git_closeout_lines = self._build_git_closeout_lines(project, git_enabled)
        return [
            "## When You're Done",
            "",
            "1. Check all agents via get_workflow_status()",
            "2. Ensure all have status='complete'",
            "3. Review final deliverables",
            *git_closeout_lines,
            "### Complete Your Orchestrator Job",
            "```python",
            f'complete_job(job_id="{orchestrator_id}")',
            "```",
            "",
        ]
