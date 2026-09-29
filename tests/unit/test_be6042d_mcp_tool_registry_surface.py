# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from api.endpoints.mcp_sdk_server import TOOL_SCOPES, mcp


EXPECTED_TOOL_SURFACE: dict[str, dict[str, object]] = {
    "create_project": {
        "fn": "create_project",
        "params": [
            "bootstrap_template_vars",
            "description",
            "name",
            "product_id",
            "project_type",
            "series_number",
            "suffix",
        ],
        "scope": "mcp:write",
    },
    "diagnose_project_state": {
        "fn": "diagnose_project_state",
        "params": ["project_id"],
        "scope": "mcp:read",
    },
    "list_projects": {
        "fn": "list_projects",
        "params": [
            "completed_after",
            "completed_before",
            "created_after",
            "created_before",
            "cursor",
            "depth",
            "hidden",
            "include_completed",
            "include_superseded",
            "limit",
            "memory_limit",
            "mode",
            "product_id",
            "project_type",
            "query",
            "status",
            "status_filter",
            "summary_only",
            "taxonomy_alias_prefix",
        ],
        "scope": "mcp:read",
    },
    "update_project": {
        "fn": "update_project",
        "params": [
            "description",
            "force",
            "name",
            "project_id",
            "project_type",
            "series_number",
            "status",
            "successor_project_id",
            "suffix",
        ],
        "scope": "mcp:write",
    },
    "update_project_mission": {
        "fn": "update_project_mission",
        "params": ["mission", "project_id"],
        "scope": "mcp:agent",
    },
    "stage_project": {
        "fn": "stage_project",
        "params": ["action", "mission", "mode", "project_id"],
        "scope": "mcp:agent",
    },
    "get_implementation_prompt": {
        "fn": "get_implementation_prompt",
        "params": ["project_id"],
        "scope": "mcp:agent",
    },
    "launch_implementation": {
        "fn": "launch_implementation",
        "params": ["mission", "project_id"],
        "scope": "mcp:agent",
    },
    "link_projects": {
        "fn": "link_projects",
        "params": ["execution_mode", "mission", "ordered", "project_ids"],
        "scope": "mcp:agent",
    },
    "unlink_projects": {
        "fn": "unlink_projects",
        "params": ["run_id"],
        "scope": "mcp:agent",
    },
    "create_task": {
        "fn": "create_task",
        "params": ["assigned_to", "description", "priority", "product_id", "task_type", "title"],
        "scope": "mcp:write",
    },
    "update_task": {
        "fn": "update_task",
        "params": [
            "completion_notes",
            "convert_to_project",
            "description",
            "hidden",
            "priority",
            "status",
            "task_id",
            "task_type",
            "title",
        ],
        "scope": "mcp:write",
    },
    "list_tasks": {
        "fn": "list_tasks",
        "params": [
            "cursor",
            "hidden",
            "limit",
            "memory_limit",
            "mode",
            "priority",
            "product_id",
            "query",
            "status",
            "summary_only",
            "task_type",
        ],
        "scope": "mcp:read",
    },
    "save_roadmap": {
        "fn": "save_roadmap",
        "params": ["items", "patch_fields", "product_id", "remove", "summary"],
        "scope": "mcp:write",
    },
    "get_roadmap": {
        "fn": "get_roadmap",
        "params": ["product_id"],
        "scope": "mcp:read",
    },
    "create_thread": {
        "fn": "create_thread",
        "params": [
            "creator_display_name",
            "creator_id",
            "product_id",
            "project_id",
            "sequence_run_id",
            "severity",
            "subject",
        ],
        "scope": "mcp:agent",
    },
    "update_thread": {
        "fn": "update_thread",
        "params": ["clear_product", "product_id", "project_ids", "status", "subject", "thread_id"],
        "scope": "mcp:agent",
    },
    "join_thread": {
        "fn": "join_thread",
        "params": ["agent_id", "display_name", "role", "thread_id"],
        "scope": "mcp:agent",
    },
    "post_to_thread": {
        "fn": "post_to_thread",
        "params": [
            "as_user",
            "content",
            "from_agent",
            "loop_directive",
            "loop_interval_minutes",
            "my_status",
            "pass_baton_to",
            "rename_to",
            "requires_action",
            "set_status",
            "thread_id",
            "to_participant",
        ],
        "scope": "mcp:agent",
    },
    "get_my_turn": {
        "fn": "get_my_turn",
        "params": ["agent_id", "wait_seconds"],
        "scope": "mcp:read",
    },
    "get_participant_liveness": {
        "fn": "get_participant_liveness",
        "params": ["thread_id"],
        "scope": "mcp:read",
    },
    "set_next_actor": {
        "fn": "set_next_actor",
        "params": ["from_agent", "thread_id", "to"],
        "scope": "mcp:agent",
    },
    "list_threads": {
        "fn": "list_threads",
        "params": ["owner", "product_id", "project_id", "query", "status"],
        "scope": "mcp:read",
    },
    "get_thread_history": {
        "fn": "get_thread_history",
        "params": [
            "action_required_only",
            "after_message_id",
            "as_participant",
            "directed_only",
            "mark_read",
            "since",
            "tail",
            "thread_id",
            "unread_only",
        ],
        "scope": "mcp:read",
    },
    "request_approval": {
        "fn": "request_approval",
        "params": ["context", "job_id", "options", "project_id", "reason"],
        "scope": "mcp:agent",
    },
    "decide_approval": {
        "fn": "decide_approval",
        "params": ["approval_id", "option_id"],
        "scope": "mcp:agent",
    },
    "get_staging_instructions": {
        "fn": "get_staging_instructions",
        "params": ["harness", "job_id"],
        "scope": "mcp:agent",
    },
    "update_job_mission": {
        "fn": "update_job_mission",
        "params": ["job_id", "mission"],
        "scope": "mcp:agent",
    },
    "report_progress": {
        "fn": "report_progress",
        "params": ["job_id", "replace", "todo_append", "todo_items"],
        "scope": "mcp:agent",
    },
    "complete_job": {
        "fn": "complete_job",
        "params": ["acknowledge_closeout_todo", "acknowledge_messages_on_complete", "job_id", "result"],
        "scope": "mcp:agent",
    },
    "finalize_job": {
        "fn": "finalize_job",
        "params": ["caller_job_id", "job_id"],
        "scope": "mcp:agent",
    },
    "resume_or_dismiss_job": {
        "fn": "resume_or_dismiss_job",
        "params": ["action", "job_id", "reason"],
        "scope": "mcp:agent",
    },
    "set_agent_status": {
        "fn": "set_agent_status",
        "params": ["job_id", "reason", "status", "wake_in_minutes", "wake_on_signal"],
        "scope": "mcp:agent",
    },
    "get_job_mission": {
        "fn": "get_job_mission",
        "params": ["harness", "job_id", "protocol_etag", "section"],
        "scope": "mcp:agent",
    },
    "spawn_job": {
        "fn": "spawn_job",
        "params": [
            "agent_display_name",
            "agent_name",
            "inline_seed",
            "mission",
            "phase",
            "predecessor_job_id",
            "project_id",
        ],
        "scope": "mcp:agent",
    },
    "get_agent_result": {
        "fn": "get_agent_result",
        "params": ["job_id"],
        "scope": "mcp:agent",
    },
    "get_workflow_status": {
        "fn": "get_workflow_status",
        "params": ["exclude_job_id", "project_id"],
        "scope": "mcp:agent",
    },
    "get_context": {
        "fn": "get_context",
        "params": ["agent_name", "categories", "depth_config", "job_id", "output_format", "product_id", "project_id"],
        "scope": "mcp:read",
    },
    "search_memory": {
        "fn": "search_memory",
        "params": ["limit", "product_id", "query", "tag"],
        "scope": "mcp:read",
    },
    "write_project_closeout": {
        "fn": "write_project_closeout",
        "params": [
            "decisions_made",
            "force",
            "git_commits",
            "key_outcomes",
            "no_code_changes",
            "project_id",
            "summary",
            "tags",
        ],
        "scope": "mcp:agent",
    },
    "write_memory_entry": {
        "fn": "write_memory_entry",
        "params": [
            "acknowledge_closeout_todo",
            "author_job_id",
            "decisions_made",
            "entry_type",
            "git_commits",
            "key_outcomes",
            "no_code_changes",
            "project_id",
            "summary",
            "tags",
        ],
        "scope": "mcp:agent",
    },
    "create_product": {
        "fn": "create_product",
        "params": [
            "brand_guidelines",
            "core_features",
            "description",
            "name",
            "project_path",
            "target_platforms",
        ],
        "scope": "mcp:write",
    },
    "create_vision_document": {
        "fn": "create_vision_document",
        "params": ["content", "document_name", "product_id"],
        "scope": "mcp:write",
    },
    "get_vision_document": {
        "fn": "get_vision_document",
        "params": ["chunk", "product_id"],
        "scope": "mcp:read",
    },
    "update_product_context": {
        "fn": "update_product_context",
        "params": [
            "architecture",
            "consolidated_vision",
            "core_features",
            "emit_completion",
            "extraction_custom_instructions",
            "force",
            "is_active",
            "product_description",
            "product_id",
            "product_name",
            "project_path",
            "quality",
            "tech_stack",
            "testing",
            "vision_summaries",
        ],
        "scope": "mcp:write",
    },
    "health_check": {
        "fn": "health_check",
        "params": [],
        "scope": "mcp:read",
    },
    "get_giljo_guide": {
        "fn": "get_giljo_guide",
        "params": [],
        "scope": "mcp:read",
    },
    "giljo_setup": {
        "fn": "giljo_setup",
        "params": ["harness", "platform", "product_id", "scope"],
        "scope": "mcp:write",
    },
    "apply_context_tuning": {
        "fn": "apply_context_tuning",
        "params": ["force", "overall_summary", "product_id", "proposals"],
        "scope": "mcp:write",
    },
}


def _live_tool_surface() -> dict[str, dict[str, object]]:
    surface: dict[str, dict[str, object]] = {}
    for tool in mcp._tool_manager.list_tools():
        fn = getattr(tool, "fn", None)
        params = sorted(tool.parameters.get("properties", {}).keys()) if isinstance(tool.parameters, dict) else []
        surface[tool.name] = {
            "fn": getattr(fn, "__name__", None),
            "params": params,
            "scope": TOOL_SCOPES.get(tool.name),
        }
    return surface


def test_registered_tool_set_is_exactly_preserved():
    live_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected_names = set(EXPECTED_TOOL_SURFACE)
    assert live_names == expected_names, (
        f"Tool registry drift. Missing: {sorted(expected_names - live_names)}; "
        f"Unexpected: {sorted(live_names - expected_names)}"
    )
    assert len(live_names) == 49


def test_every_tool_fn_params_and_scope_preserved():
    assert _live_tool_surface() == EXPECTED_TOOL_SURFACE


def test_update_product_context_fn_matches_registered_name():
    surface = _live_tool_surface()
    assert "update_product_context" in surface
    assert surface["update_product_context"]["fn"] == "update_product_context"
    assert "update_product_fields" not in surface
    assert "write_product_from_analysis" not in surface


_INF6052A_OLD_NAMES: frozenset[str] = frozenset(
    {
        "close_project_and_update_memory",
        "fetch_context",
        "write_360_memory",
        "inspect_messages",
        "get_agent_mission",
        "update_agent_mission",
        "update_product_fields",
        "submit_tuning_review",
        "propose_product_context_update",
    }
)


def test_no_old_inf6052a_name_survives_in_live_registry():
    live_names = {t.name for t in mcp._tool_manager.list_tools()}
    survivors = _INF6052A_OLD_NAMES & live_names
    assert not survivors, f"Old INF-6052a names still present in mcp.list_tools(): {sorted(survivors)}"
