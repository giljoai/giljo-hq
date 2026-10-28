# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


CANONICAL_ORCHESTRATOR_TOOLS: tuple[str, ...] = (
    "get_giljo_guide",
    "get_context",
    "spawn_job",
    "get_job_mission",
    "get_staging_instructions",
    "post_to_thread",
    "get_thread_history",
    "report_progress",
    "set_agent_status",
    "get_workflow_status",
    "update_project_mission",
    "update_job_mission",
    "complete_job",
    "finalize_job",
    "resume_job",
    "dismiss_job",
    "write_memory_entry",
    "write_project_closeout",
    "get_agent_result",
    "create_task",
    "create_project",
    "list_projects",
    "request_approval",
)


def render_toolsearch_query() -> str:
    return "select:" + ",".join(CANONICAL_ORCHESTRATOR_TOOLS)


def render_toolsearch_call_one_line() -> str:
    return f'ToolSearch(query="{render_toolsearch_query()}", max_results={len(CANONICAL_ORCHESTRATOR_TOOLS)})'


CANONICAL_WORKER_TOOLS: tuple[str, ...] = (
    "get_job_mission",
    "get_thread_history",
    "post_to_thread",
    "report_progress",
    "set_agent_status",
    "get_context",
    "complete_job",
)


def render_worker_toolsearch_call() -> str:
    tools = ",".join(CANONICAL_WORKER_TOOLS)
    return f'ToolSearch(query="select:{tools}", max_results={len(CANONICAL_WORKER_TOOLS)})'
