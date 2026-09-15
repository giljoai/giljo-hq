# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from giljo_mcp.models import AgentExecution


def _generate_team_context_header(
    current_job: AgentExecution,
    all_project_jobs: list[AgentExecution],
    mission_lookup: dict[str, str] | None = None,
    include_team_table: bool = True,
) -> str:
    agent_name = getattr(current_job, "agent_name", None) or getattr(current_job, "agent_display_name", "unknown")
    agent_display_name = getattr(current_job, "agent_display_name", "unknown")

    agent_id = getattr(current_job, "agent_id", "unknown")
    job_id = getattr(current_job, "job_id", agent_id)

    identity_section = f"""## YOUR IDENTITY
You are **{agent_name.upper()}** (agent_id: `{agent_id}`, job_id: `{job_id}`)
Role: {agent_display_name}
"""

    if include_team_table:
        num_agents = len(all_project_jobs)
        team_rows = []
        for job in all_project_jobs:
            role_name = getattr(job, "agent_name", None) or getattr(job, "agent_display_name", "unknown")

            mission_text = ""
            if mission_lookup and hasattr(job, "job_id") and job.job_id in mission_lookup:
                mission_text = mission_lookup[job.job_id]
            elif hasattr(job, "mission") and job.mission:
                mission_text = job.mission

            deliverable_preview = (mission_text or "")[:80].replace("\n", " ")
            if len(mission_text or "") > 80:
                deliverable_preview += "..."
            job_agent_id = getattr(job, "agent_id", "unknown")
            team_rows.append(
                f"| {role_name} | `{job_agent_id}` | {getattr(job, 'agent_display_name', 'unknown')} | {deliverable_preview} |"
            )

        team_table = "\n".join(team_rows)
        team_section = f"""## YOUR TEAM
This project has {num_agents} agent(s) working together:

| Agent | agent_id | Role | Deliverables |
|-------|----------|------|--------------|
{team_table}
"""
    else:
        team_section = ""

    dependencies_upstream = []
    dependencies_downstream = []

    dependency_rules = {
        "analyzer": {"upstream": [], "downstream": ["implementer", "documenter", "tester"]},
        "implementer": {"upstream": ["analyzer"], "downstream": ["tester", "reviewer", "documenter"]},
        "tester": {"upstream": ["implementer"], "downstream": ["reviewer"]},
        "reviewer": {"upstream": ["implementer", "tester"], "downstream": ["documenter"]},
        "documenter": {"upstream": ["analyzer", "implementer", "reviewer"], "downstream": []},
    }

    current_id = getattr(current_job, "agent_id", None) or getattr(current_job, "job_id", None)
    other_agents = [
        j for j in all_project_jobs if (getattr(j, "agent_id", None) or getattr(j, "job_id", None)) != current_id
    ]
    other_types = {getattr(j, "agent_display_name", "unknown") for j in other_agents}

    if agent_display_name in dependency_rules:
        rules = dependency_rules[agent_display_name]
        dependencies_upstream.extend([upstream for upstream in rules["upstream"] if upstream in other_types])
        dependencies_downstream.extend([downstream for downstream in rules["downstream"] if downstream in other_types])

    if dependencies_upstream:
        upstream_text = f"- You depend on: {', '.join(dependencies_upstream)} (wait for their outputs if needed)"
    else:
        upstream_text = "- You depend on: None (you can start immediately)"

    if dependencies_downstream:
        downstream_text = (
            f"- Others depend on you: {', '.join(dependencies_downstream)} (notify them when your work is ready)"
        )
    else:
        downstream_text = "- Others depend on you: None"

    dependencies_section = f"""## YOUR DEPENDENCIES
{upstream_text}
{downstream_text}
"""

    coordination_section = f"""## COORDINATION
- **UUID-ONLY MESSAGING**: Always use agent_id UUIDs from the team table above when addressing agents
- Use `post_to_thread(thread_id=<your coordination thread>, content="...", from_agent="{agent_id}", to_participant="<agent_id>", ...)` with UUID values
- Use `get_thread_history(thread_id=<your coordination thread>, as_participant="{agent_id}", unread_only=true, mark_read=true)` to check for instructions or updates
- When you complete a deliverable, post a brief status message to downstream agents using their agent_id UUIDs as `to_participant`
- Omit `to_participant` for a broadcast to the entire team
- NEVER use display names (e.g., "orchestrator", "implementer") in to_participant - use the UUID from the team table
- Check `full_protocol` for detailed messaging and progress reporting guidance

---

"""

    return identity_section + "\n" + team_section + "\n" + dependencies_section + "\n" + coordination_section
