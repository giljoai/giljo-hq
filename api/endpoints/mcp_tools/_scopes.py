# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from starlette.requests import Request as StarletteRequest



SCOPE_READ = "mcp:read"
SCOPE_WRITE = "mcp:write"
SCOPE_AGENT = "mcp:agent"

TOOL_SCOPES: dict[str, str] = {
    "create_project": SCOPE_WRITE,
    "list_projects": SCOPE_READ,
    "update_project": SCOPE_WRITE,
    "update_project_mission": SCOPE_AGENT,
    "diagnose_project_state": SCOPE_READ,
    "stage_project": SCOPE_AGENT,
    "get_implementation_prompt": SCOPE_AGENT,
    "launch_implementation": SCOPE_AGENT,
    "link_projects": SCOPE_AGENT,
    "unlink_projects": SCOPE_AGENT,
    "update_job_mission": SCOPE_AGENT,
    "get_staging_instructions": SCOPE_AGENT,
    "create_thread": SCOPE_AGENT,
    "update_thread": SCOPE_AGENT,
    "join_thread": SCOPE_AGENT,
    "post_to_thread": SCOPE_AGENT,
    "set_next_actor": SCOPE_AGENT,
    "get_my_turn": SCOPE_READ,
    "get_participant_liveness": SCOPE_READ,
    "list_threads": SCOPE_READ,
    "get_thread_history": SCOPE_READ,
    "create_task": SCOPE_WRITE,
    "update_task": SCOPE_WRITE,
    "list_tasks": SCOPE_READ,
    "save_roadmap": SCOPE_WRITE,
    "get_roadmap": SCOPE_READ,
    "request_approval": SCOPE_AGENT,
    "decide_approval": SCOPE_AGENT,
    "health_check": SCOPE_READ,
    "get_giljo_guide": SCOPE_READ,
    "giljo_setup": SCOPE_WRITE,
    "report_progress": SCOPE_AGENT,
    "complete_job": SCOPE_AGENT,
    "finalize_job": SCOPE_AGENT,
    "resume_or_dismiss_job": SCOPE_AGENT,
    "set_agent_status": SCOPE_AGENT,
    "get_job_mission": SCOPE_AGENT,
    "spawn_job": SCOPE_AGENT,
    "get_agent_result": SCOPE_AGENT,
    "get_workflow_status": SCOPE_AGENT,
    "get_context": SCOPE_READ,
    "search_memory": SCOPE_READ,
    "write_project_closeout": SCOPE_AGENT,
    "write_memory_entry": SCOPE_AGENT,
    "apply_context_tuning": SCOPE_WRITE,
    "get_vision_document": SCOPE_READ,
    "update_product_context": SCOPE_WRITE,
    "create_product": SCOPE_WRITE,
    "create_vision_document": SCOPE_WRITE,
}


def _scopes_from_request(request: StarletteRequest | None) -> set[str] | None:
    if request is None:
        return None
    state = request.scope.get("state", {}) if hasattr(request, "scope") else {}
    if state.get("auth_method") == "api_key":
        return None
    scopes = state.get("scopes")
    if not scopes:
        return set()
    return set(scopes)



PROFILE_CORE = "core"
PROFILE_STANDARD = "standard"
PROFILE_FULL = "full"

_CORE_PROFILE_TOOLS: frozenset[str] = frozenset(
    {
        "health_check",
        "get_giljo_guide",
        "get_context",
        "list_projects",
        "create_project",
        "create_task",
        "update_task",
        "list_tasks",
        "search_memory",
        "get_job_mission",
        "report_progress",
        "complete_job",
        "write_project_closeout",
        "post_to_thread",
    }
)

_STANDARD_PROFILE_TOOLS: frozenset[str] = _CORE_PROFILE_TOOLS | frozenset(
    {
        "create_thread",
        "update_thread",
        "join_thread",
        "get_my_turn",
        "set_next_actor",
        "get_participant_liveness",
        "list_threads",
        "get_thread_history",
        "get_roadmap",
        "save_roadmap",
        "get_vision_document",
        "update_product_context",
        "apply_context_tuning",
        "create_product",
        "create_vision_document",
        "diagnose_project_state",
    }
)

PROFILE_ORCHESTRATOR = "orchestrator"

_LAUNCH_GATE_TOOLS: frozenset[str] = frozenset({"launch_implementation"})
_ORCHESTRATOR_PROFILE_TOOLS: frozenset[str] = frozenset(TOOL_SCOPES) - _LAUNCH_GATE_TOOLS

_HITL_FENCED_TOOLS: frozenset[str] = _LAUNCH_GATE_TOOLS | frozenset({"decide_approval"})

PROFILE_LISTING = "listing"

_LISTING_PROFILE_TOOLS: frozenset[str] = frozenset(
    {
        "health_check",
        "get_giljo_guide",
        "get_context",
        "list_projects",
        "create_project",
        "update_project",
        "list_tasks",
        "create_task",
        "update_task",
        "search_memory",
        "get_roadmap",
    }
)

TOOL_PROFILES: dict[str, frozenset[str] | None] = {
    PROFILE_CORE: _CORE_PROFILE_TOOLS,
    PROFILE_STANDARD: _STANDARD_PROFILE_TOOLS,
    PROFILE_ORCHESTRATOR: _ORCHESTRATOR_PROFILE_TOOLS,
    PROFILE_LISTING: _LISTING_PROFILE_TOOLS,
    PROFILE_FULL: None,
}


def _normalize_scopes(scopes: object) -> set[str]:
    if not scopes:
        return set()
    if isinstance(scopes, str):
        return {s for s in scopes.split() if s}
    return {str(s) for s in scopes}


def _auth_derived_profile_toolset_from_state(state: dict) -> frozenset[str] | None:
    if state.get("auth_method") == "jwt":
        if "mcp:agent" in _normalize_scopes(state.get("scopes")):
            return TOOL_PROFILES[PROFILE_ORCHESTRATOR]
        return TOOL_PROFILES[PROFILE_STANDARD]
    if state.get("auth_method") == "api_key":
        return TOOL_PROFILES[PROFILE_FULL]
    return frozenset()


def _profile_toolset_from_state(state: dict) -> frozenset[str] | None:
    declared = state.get("tool_profile")
    if isinstance(declared, str) and declared in TOOL_PROFILES:
        candidate = TOOL_PROFILES[declared]
        baseline = _auth_derived_profile_toolset_from_state(state)
        if baseline is None:
            return candidate
        if candidate is None or not candidate <= baseline:
            pass
        else:
            return candidate
    return _auth_derived_profile_toolset_from_state(state)


def _profile_toolset_from_request(request: StarletteRequest | None) -> frozenset[str] | None:
    if request is None:
        return None
    state = request.scope.get("state", {}) if hasattr(request, "scope") else {}
    return _profile_toolset_from_state(state)
