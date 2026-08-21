# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-6042d characterization test — STRICT set-equality lock on the FastMCP @mcp.tool
registry exposed by api/endpoints/mcp_sdk_server.py.

This suite is the LOAD-BEARING behavior gate for the mechanical split of the
2,263-line ``mcp_sdk_server.py`` into a ``mcp_tools/`` wrapper subpackage. It runs
GREEN against the unmodified module FIRST, then unchanged after extraction. It
asserts THROUGH the FastMCP transport registry (the exact BE-5042 gap — a tool
can pass every service-layer test yet fail to register on the ``mcp`` instance):

- The full registered-tool SET is EXACTLY preserved (no tool dropped, added, or
  renamed) — ``EXPECTED_TOOL_SURFACE.keys()`` set-equality.
- For every tool: the underlying decorated function name, the sorted parameter
  names (signature lock), and the TOOL_SCOPES scope are byte-for-byte preserved.

Because ``@mcp.tool`` registers as a decorator side effect at import time, this
test also guards the import-time registration wiring: a domain wrapper module that
fails to import (and therefore fails to register its tools) is caught by the
set-equality assertion.

The module-level re-export surface (public symbols other code imports straight
from ``mcp_sdk_server``) is locked separately in
``test_be6042d_mcp_sdk_server_reexports.py``.
"""

from __future__ import annotations

from api.endpoints.mcp_sdk_server import TOOL_SCOPES, mcp


# Frozen baseline captured from the unmodified mcp_sdk_server.py (35 tools),
# plus update_roadmap_metadata added in FE-6022a (36), get_roadmap in FE-6022c (37),
# get_giljo_guide in INF-6049a (38), stage_project + implement_project in INF-6049b
# (40), 8 renames in INF-6052a (40, names updated), the 8 Agent Message Hub thread
# tools in BE-6054b (48), launch_implementation in BE-6115a (49), INF-6111b
# retired generate_download_token + renamed get_staging_context -> get_staging_instructions (48),
# and BE-6111c added diagnose_project_state (49). BE-6225a retired 3 dead-weight
# tools — get_pending_jobs, complete_task (folded into update_task via
# completion_notes), and list_agent_templates (folded into giljo_setup) — (46).
# Maps registered_tool_name -> {fn: decorated function __name__,
#                               params: sorted parameter names,
#                               scope: TOOL_SCOPES entry}.
# ``update_product_context`` is both the registered NAME and the decorated function
# name (INF-6052a rename from update_product_fields; explicit name= on the decorator
# is retained as a defensive lock). BE-6225a retired 3 tools (49->46); BE-6221a then
# added start_chain_run (headless chain entry point) -> 47; BE-6225b added
# search_memory (the missing 360-memory search JTBD) -> 48. BE-6225c hard-renamed
# propose_product_context_update -> apply_context_tuning (a NAME swap, count
# unchanged). BE-9012b (BE-6225e) merged reactivate_job + dismiss_reactivation into
# one resolve_reactivation tool -> 47. BE-9012d (bus retirement, phase d)
# hard-removed send_message / receive_messages / get_messages -> 44. The count is 44.
# BE-9197 added the pass_baton_to param to post_to_thread (atomic post-with-baton;
# param addition only, tool set + count unchanged). BE-9201 added create_product +
# create_vision_document (agent-side product bootstrap for the onboarding tutorial's
# prompt paths B/D) -> 46. BE-9291 added the sequence_run_id param to create_thread —
# the chain conductor stamps the hub thread's run link structurally instead of
# encoding it in the subject string, so discovery resolves on a real FK. DELIBERATELY
# ADMITTED: param addition only, tool set + count unchanged (count stays 46). This
# lock caught the change, which is exactly its job — a tool signature must not move
# silently. FE-9320 added the emit_completion param to update_product_context: the
# vision ingest became a STAGED write (the old one-call-covers-everything mandate
# failed a real run at 62,420 bytes), and the agent marks its final call instead of
# a new tool being introduced for the purpose. DELIBERATELY ADMITTED: param addition
# only, count stays 46 — that is the load-bearing half, since a new tool here would
# grow the surface of a product about to be submitted to a connector directory.
# BE-9477 added the patch_fields param to update_roadmap_metadata: editing one
# roadmap field used to clear the others, and the fix is an opt-in partial update on
# the EXISTING tool rather than a second write tool beside it. DELIBERATELY ADMITTED:
# param addition only, count stays 46. This lock caught it on CI's unit step, which is
# exactly its job — the change is intended, and it had to be admitted here by hand
# rather than land silently.
EXPECTED_TOOL_SURFACE: dict[str, dict[str, object]] = {
    # BE-9411: product_id binds the new project to a named product instead of
    # whatever is globally active at write time. Optional -- omitted, the tool
    # behaves exactly as before.
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
    # BE-6111c: read-only orchestrator self-healing diagnostic (net-new tool).
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
            # BE-9469: the opaque continuation token. A PARAMETER on the shipped tool,
            # never a new tool -- the operator ruling is standing.
            "cursor",
            "depth",
            "hidden",
            "include_completed",
            "include_superseded",
            "limit",  # BE-9468 read layer: bounded caller-facing row cap
            "memory_limit",
            "mode",
            "project_type",
            "query",  # BE-9468 read layer: substring search over name/id/alias
            "status",
            "status_filter",
            "summary_only",
            "taxonomy_alias_prefix",
        ],
        "scope": "mcp:read",
    },
    "update_project": {
        "fn": "update_project",
        "params": ["description", "name", "project_id", "project_type", "series_number", "status", "suffix"],
        "scope": "mcp:write",
    },
    "update_project_mission": {
        "fn": "update_project_mission",
        "params": ["mission", "project_id"],
        "scope": "mcp:agent",
    },
    # INF-6049b: project-lifecycle driving tools (40 tools).
    "stage_project": {
        "fn": "stage_project",
        "params": ["mode", "project_id"],
        "scope": "mcp:agent",
    },
    "implement_project": {
        "fn": "implement_project",
        "params": ["project_id"],
        "scope": "mcp:agent",
    },
    # BE-6115a: CLI door of the two-door implement gate (49 tools). mcp:agent;
    # kept OUT of the orchestrator auto-tool bundle so an agent cannot self-unlock.
    "launch_implementation": {
        "fn": "launch_implementation",
        "params": ["project_id"],
        "scope": "mcp:agent",
    },
    # BE-6221a: headless chain-start (Run Sequential equivalent), 50 tools. mcp:agent.
    "start_chain_run": {
        "fn": "start_chain_run",
        "params": ["chain_mission", "execution_mode", "project_ids", "resolved_order", "review_policy"],
        "scope": "mcp:agent",
    },
    # BE-9411: product_id binds the new task to a named product instead of
    # whatever is globally active at write time. Optional -- omitted, the tool
    # behaves exactly as before.
    "create_task": {
        "fn": "create_task",
        "params": ["assigned_to", "description", "priority", "product_id", "task_type", "title"],
        "scope": "mcp:write",
    },
    "update_task": {
        "fn": "update_task",
        # BE-6225a: completion_notes folded in from the retired complete_task tool.
        # BE-9382: convert_to_project promotes the task through the UI's own
        # conversion path (no separate convert tool).
        "params": [
            "completion_notes",
            "convert_to_project",
            "description",
            "due_date",
            "hidden",
            "priority",
            "status",
            "task_id",
            "task_type",
            "title",
        ],
        "scope": "mcp:write",
    },
    # BE-9468 added `limit` (bounded row cap, default/max from the read layer) and
    # `query` (substring search over title/description/taxonomy_alias). Both are
    # OPTIONAL with defaults, so every call that worked before still works -- the
    # signature grew, the contract did not change.
    "list_tasks": {
        "fn": "list_tasks",
        "params": [
            # BE-9469: the opaque continuation token. A PARAMETER, never a new tool.
            "cursor",
            "due_before",
            "hidden",
            "limit",
            "memory_limit",
            "mode",
            "priority",
            "query",
            "status",
            "summary_only",
            "task_type",
        ],
        "scope": "mcp:read",
    },
    # FE-6022a: Roadmapping Pane bulk-upsert tool. 0006 added the `remove` param
    # (drop items from the roadmap in the same call).
    # BE-9477: patch_fields makes an item patch only the metadata it carries --
    # an omitted field keeps its stored value, an explicitly empty one is
    # cleared. Optional and DEFAULT FALSE, so an existing caller takes the
    # identical path it always did.
    "update_roadmap_metadata": {
        "fn": "update_roadmap_metadata",
        "params": ["items", "patch_fields", "remove", "summary"],
        "scope": "mcp:write",
    },
    # FE-6022c: Roadmapping Pane read tool.
    "get_roadmap": {
        "fn": "get_roadmap",
        "params": [],
        "scope": "mcp:read",
    },
    # BE-6054b: Agent Message Hub (BBS) thread tools (8 new -> 48 total).
    # BE-9291: sequence_run_id is the chain conductor's structural hub link (see the
    # ledger above). Admitted deliberately; fn name and scope are unchanged.
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
    "join_thread": {
        "fn": "join_thread",
        "params": ["agent_id", "display_name", "role", "thread_id"],
        "scope": "mcp:agent",
    },
    "post_to_thread": {
        "fn": "post_to_thread",
        # BE-9379 added as_user: attribution is fail-closed — from_agent is required,
        # and posting in the human user's voice is an explicit as_user=true (the two
        # are mutually exclusive). DELIBERATELY ADMITTED — param addition only,
        # tool set + count unchanged.
        # BE-9475 added my_status: a headless participant's own status claim, the only
        # channel an agent with no agent_executions row has for saying what it is doing.
        # DELIBERATELY ADMITTED — param addition only, tool set + count unchanged.
        "params": [
            "as_user",
            "content",
            "from_agent",
            "loop_directive",
            "loop_interval_minutes",
            "my_status",
            "pass_baton_to",
            "requires_action",
            "set_status",
            "thread_id",
            "to_participant",
        ],
        "scope": "mcp:agent",
    },
    "get_my_turn": {
        "fn": "get_my_turn",
        "params": ["agent_id"],
        "scope": "mcp:read",
    },
    "await_my_turn": {
        "fn": "await_my_turn",
        "params": ["agent_id", "timeout_seconds"],
        "scope": "mcp:read",
    },
    "get_participant_liveness": {
        "fn": "get_participant_liveness",
        "params": ["thread_id"],
        "scope": "mcp:read",
    },
    "pass_baton": {
        "fn": "pass_baton",
        # BE-9296a added from_agent: the hander's id, so the recipient's alert names
        # WHO is waiting rather than only the thread. DELIBERATELY ADMITTED — param
        # addition only, optional, tool set + count unchanged.
        "params": ["from_agent", "thread_id", "to"],
        "scope": "mcp:agent",
    },
    "list_threads": {
        "fn": "list_threads",
        "params": ["owner", "product_id", "project_id", "status"],
        "scope": "mcp:read",
    },
    "get_thread_history": {
        "fn": "get_thread_history",
        # BE-6226: backward-compatible incremental-fetch params (since/after/tail).
        # BE-9012a: server-persistent per-participant cursor params added
        # (as_participant + unread_only/mark_read/directed_only/action_required_only).
        # Params only — still ONE tool, registry count unchanged (48 -> 48).
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
    "search_threads": {
        "fn": "search_threads",
        "params": ["query"],
        "scope": "mcp:read",
    },
    "request_approval": {
        "fn": "request_approval",
        "params": ["context", "job_id", "options", "project_id", "reason"],
        "scope": "mcp:agent",
    },
    "get_staging_instructions": {
        "fn": "get_staging_instructions",
        # BE-8003f (D2 activation): optional session harness preset threaded to the
        # conductor staging render (web_sandbox|desktop_app|chat; omit for CLI).
        "params": ["harness", "job_id"],
        # BE-6167: reclassified mcp:read -> mcp:agent (its BE-5122 CTX self-close
        # path writes project.status=COMPLETED; a read-scoped token must not reach it).
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
    "close_job": {
        "fn": "close_job",
        "params": ["job_id"],
        "scope": "mcp:agent",
    },
    # BE-9012b (BE-6225e): reactivate_job + dismiss_reactivation merged into a single
    # resolve_reactivation(job_id, action, reason) tool surface (48 -> 47). The two
    # SERVICE methods are kept (project_helpers internal caller) + remain in
    # TOOL_DISPATCH as internal targets; only the agent-facing tool surface is merged.
    "resolve_reactivation": {
        "fn": "resolve_reactivation",
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
        # BE-8003f (D2 activation): optional session harness preset threaded into the
        # S3/S4 mission render (web_sandbox|desktop_app|chat; omit for CLI).
        # BE-9083d: optional `section` — truncation recovery; fetch ONE named slice of
        # full_protocol (names from protocol_toc). A param on this tool, NEVER a new tool.
        "params": ["harness", "job_id", "protocol_etag", "section"],
        "scope": "mcp:agent",
    },
    "spawn_job": {
        "fn": "spawn_job",
        "params": ["agent_display_name", "agent_name", "mission", "phase", "predecessor_job_id", "project_id"],
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
    # BE-6225b: keyword search over 360 memory (the missing search JTBD), 47 -> 48.
    "search_memory": {
        "fn": "search_memory",
        "params": ["limit", "query", "tag"],
        "scope": "mcp:read",
    },
    "write_project_closeout": {
        "fn": "write_project_closeout",
        # BE-9165: force added — previously hardcoded False inside the wrapper,
        # making the CLOSEOUT_BLOCKED "pass force=true" hint unwirable from the
        # transport.
        "params": ["decisions_made", "force", "git_commits", "key_outcomes", "project_id", "summary", "tags"],
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
            "project_id",
            "summary",
            "tags",
        ],
        "scope": "mcp:agent",
    },
    # BE-9201: agent-side product bootstrap (45th/46th tools). create_product
    # establishes the row (populate stays update_product_context's job);
    # create_vision_document is the MCP twin of the REST vision upload.
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
    "get_vision_doc": {
        "fn": "get_vision_doc",
        "params": ["chunk", "product_id"],
        "scope": "mcp:read",
    },
    # BE-9118 (Option B): the 17 flat prose params were regrouped into 4 typed
    # dicts (tech_stack, architecture, quality, testing). Net 23 -> 11 params.
    # The wrapper unpacks the dicts to the SAME flat ProductService kwargs, so the
    # DB/service/columns are untouched — only the agent-facing param SHAPE changed.
    # BE-9167: added project_path (11 -> 12) so the vision-analysis agent can fill
    # the product card's "Codebase Folder"; user-owned skip, same style as
    # product_name/product_description.
    "update_product_context": {
        "fn": "update_product_context",
        "params": [
            "architecture",
            "consolidated_vision",
            "core_features",
            "emit_completion",
            "force",
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
        # BE-8003g: optional session harness preset (web_sandbox|desktop_app|chat;
        # omit for CLI), the harness param's second wrapper after BE-8003f's
        # get_staging_instructions/get_job_mission.
        "params": ["harness", "platform"],
        "scope": "mcp:write",
    },
    # BE-6225c: renamed from propose_product_context_update (the tool APPLIES tuning
    # directly, it does not propose). Hard rename; scope/params unchanged.
    "apply_context_tuning": {
        "fn": "apply_context_tuning",
        "params": ["force", "overall_summary", "product_id", "proposals"],
        "scope": "mcp:write",
    },
}


def _live_tool_surface() -> dict[str, dict[str, object]]:
    """Build the current registry surface map from the live FastMCP instance."""
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
    """STRICT set-equality: no @mcp.tool dropped, added, or renamed.

    BE-6115a added launch_implementation (CLI door of the two-door implement
    gate): 48 -> 49 tools. INF-6111b retired generate_download_token: 49 -> 48.
    BE-6111c added diagnose_project_state: 48 -> 49. BE-6225a retired
    get_pending_jobs, complete_task, and list_agent_templates: 49 -> 46.
    BE-6221a added start_chain_run (headless chain entry point): 46 -> 47.
    BE-6225b added search_memory (the missing 360-memory search JTBD): 47 -> 48.
    BE-9012b (BE-6225e) merged reactivate_job + dismiss_reactivation into
    resolve_reactivation: 48 -> 47. BE-9012d hard-removed the 3 bus tools:
    47 -> 44. BE-9201 added create_product + create_vision_document
    (agent-side product bootstrap): 44 -> 46. BE-9296a added await_my_turn (the
    blocking form of get_my_turn — the server wake signal): 46 -> 47, and
    get_participant_liveness (the orchestrator's who-is-still-there read): 47 -> 48.
    BE-9385b added set_agent_export_alias (the install-time "keep both" rename, which
    MUST round-trip to the server or spawn-by-name silently stops resolving): 48 -> 49.
    BE-9396 retracted that tool one day later, before it reached any release: the
    operator ruled that giljo_setup guarantees server -> disk and nothing beyond it,
    so a file the user renames by hand leaves the guarantee rather than pulling the
    server into chasing it. The install prose now flags the conflict and lets the
    installing LLM resolve it with the user -- the round-trip was the enforcement
    layer, and enforcement was the part that was over-built: 49 -> 48.
    """
    live_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected_names = set(EXPECTED_TOOL_SURFACE)
    assert live_names == expected_names, (
        f"Tool registry drift. Missing: {sorted(expected_names - live_names)}; "
        f"Unexpected: {sorted(live_names - expected_names)}"
    )
    assert len(live_names) == 48


def test_every_tool_fn_params_and_scope_preserved():
    """Per-tool lock: decorated fn name, sorted param names, and scope unchanged."""
    assert _live_tool_surface() == EXPECTED_TOOL_SURFACE


def test_update_product_context_fn_matches_registered_name():
    """Regression (INF-6049a, INF-6052a): the wrapper fn name matches the registered name.

    Originally ``write_product_from_analysis``, aligned to ``update_product_fields``
    in INF-6049a, then renamed to ``update_product_context`` in INF-6052a.
    The explicit ``name="update_product_context"`` on the decorator is retained defensively.
    """
    surface = _live_tool_surface()
    assert "update_product_context" in surface
    assert surface["update_product_context"]["fn"] == "update_product_context"
    assert "update_product_fields" not in surface
    assert "write_product_from_analysis" not in surface


# INF-6052a: old registered names must be completely absent from the live surface.
# BE-6225c: propose_product_context_update joins the set -- hard-renamed to
# apply_context_tuning, so the old name must NOT survive in the live registry
# (the rename-heal redirects callers via the server-authored tuning prompt).
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
    """INF-6052a: every pre-rename registered name must be absent from mcp.list_tools().

    The live surface = 40 tools. A partial rename (e.g. re-export left stale, or
    TOOL_SCOPES key not updated) would leave an old name registered. This catches it.
    """
    live_names = {t.name for t in mcp._tool_manager.list_tools()}
    survivors = _INF6052A_OLD_NAMES & live_names
    assert not survivors, f"Old INF-6052a names still present in mcp.list_tools(): {sorted(survivors)}"
