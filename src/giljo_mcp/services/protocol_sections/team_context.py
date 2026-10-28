# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from giljo_mcp.models import AgentExecution, AgentJob


_SUMMARY_EMPHASIS = re.compile(r"[*`]+")
_SUMMARY_NOISE = re.compile(r"[#>|]+")
ORCHESTRATOR_TEAM_ROLE = "Coordinates the team; message it with blockers and questions"


def summarize_mission(text: str | None, limit: int) -> str:
    summary = ""
    for token in _SUMMARY_NOISE.sub(" ", _SUMMARY_EMPHASIS.sub("", text or "")).split():
        word = "[...]" if len(token) > limit else token
        candidate = f"{summary} {word}".strip()
        if len(candidate) > limit:
            return f"{summary}..."
        summary = candidate
        if word.endswith((".", "!", "?")) and len(summary) >= limit // 2:
            break
    return summary


JobLinks = dict[str, tuple[str | None, int | None]]


def job_dependency_link(job: AgentJob) -> tuple[str | None, int | None]:
    metadata = getattr(job, "job_metadata", None)
    predecessor = metadata.get("predecessor_job_id") if isinstance(metadata, dict) else None
    return (predecessor if isinstance(predecessor, str) else None, getattr(job, "phase", None))


def _upstream_job_ids(job_id: str, job_links: JobLinks) -> set[str]:
    predecessor, phase = job_links.get(job_id, (None, None))
    upstream = {predecessor} if predecessor else set()
    if phase is not None and phase > 1:
        upstream.update(
            other_id
            for other_id, (_, other_phase) in job_links.items()
            if other_phase is not None and other_phase < phase
        )
    upstream.discard(job_id)
    return upstream


def _generate_team_context_header(
    current_job: AgentExecution,
    all_project_jobs: list[AgentExecution],
    mission_lookup: dict[str, str] | None = None,
    include_team_table: bool = True,
    job_links: JobLinks | None = None,
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
        is_orchestrator = [getattr(job, "agent_display_name", None) == "orchestrator" for job in all_project_jobs]
        team_rows = []
        for job, orchestrator_row in zip(all_project_jobs, is_orchestrator, strict=True):
            role_name = getattr(job, "agent_name", None) or getattr(job, "agent_display_name", "unknown")

            mission_text = ""
            if mission_lookup and hasattr(job, "job_id") and job.job_id in mission_lookup:
                mission_text = mission_lookup[job.job_id]
            elif hasattr(job, "mission") and job.mission:
                mission_text = job.mission

            deliverable = ORCHESTRATOR_TEAM_ROLE if orchestrator_row else summarize_mission(mission_text, 80)
            job_agent_id = getattr(job, "agent_id", "unknown")
            team_rows.append(
                f"| {role_name} | `{job_agent_id}` | {getattr(job, 'agent_display_name', 'unknown')} | {deliverable} |"
            )

        workers = len(all_project_jobs) - sum(is_orchestrator)
        headcount = f"{workers} agent(s) and its orchestrator" if any(is_orchestrator) else f"{workers} agent(s)"
        team_table = "\n".join(team_rows)
        team_section = f"""## YOUR TEAM
This project has {headcount}:

| Agent | agent_id | Role | Deliverables |
|-------|----------|------|--------------|
{team_table}
"""
    else:
        team_section = ""

    links = job_links or {}
    current_job_id = getattr(current_job, "job_id", None)
    upstream_ids = _upstream_job_ids(current_job_id, links)
    others = [j for j in all_project_jobs if getattr(j, "job_id", None) != current_job_id]
    dependencies_upstream = [f"{j.agent_display_name} ({j.agent_id})" for j in others if j.job_id in upstream_ids]
    dependencies_downstream = [
        f"{j.agent_display_name} ({j.agent_id})" for j in others if current_job_id in _upstream_job_ids(j.job_id, links)
    ]

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
- **UUID-ONLY MESSAGING**: address agents by the team table's agent_id UUIDs, NEVER a display
  name; omit `to_participant` to broadcast. Your `from_agent` is `{agent_id}`.
- Post a status message to the agents that depend on you when a deliverable is ready; the exact
  `get_thread_history` / `post_to_thread` calls are in `full_protocol`.

---

"""

    return identity_section + "\n" + team_section + "\n" + dependencies_section + "\n" + coordination_section
