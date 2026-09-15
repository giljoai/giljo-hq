# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.branding import MCP_ALIAS


_PREFIX = f"mcp__{MCP_ALIAS}__"


CANONICAL_ORCHESTRATOR_TOOLS: tuple[str, ...] = (
    f"{_PREFIX}health_check",
    f"{_PREFIX}get_giljo_guide",
    f"{_PREFIX}get_context",
    f"{_PREFIX}spawn_job",
    f"{_PREFIX}get_job_mission",
    f"{_PREFIX}get_staging_instructions",
    f"{_PREFIX}post_to_thread",
    f"{_PREFIX}get_thread_history",
    f"{_PREFIX}report_progress",
    f"{_PREFIX}set_agent_status",
    f"{_PREFIX}get_workflow_status",
    f"{_PREFIX}update_project_mission",
    f"{_PREFIX}update_job_mission",
    f"{_PREFIX}complete_job",
    f"{_PREFIX}finalize_job",
    f"{_PREFIX}resume_or_dismiss_job",
    f"{_PREFIX}write_memory_entry",
    f"{_PREFIX}write_project_closeout",
    f"{_PREFIX}get_agent_result",
    f"{_PREFIX}create_task",
    f"{_PREFIX}create_project",
    f"{_PREFIX}list_projects",
    f"{_PREFIX}request_approval",
)


def render_toolsearch_query() -> str:
    return "select:" + ",".join(CANONICAL_ORCHESTRATOR_TOOLS)


def render_toolsearch_call_one_line() -> str:
    return f'ToolSearch(query="{render_toolsearch_query()}", max_results=25)'
