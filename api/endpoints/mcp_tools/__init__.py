# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from api.endpoints.mcp_tools import (
    _chain_tools,
    _comm_edit_tools,
    _comm_tools,
    _context_tools,
    _job_tools,
    _memory_tools,
    _message_tools,
    _project_tools,
    _roadmap_tools,
    _setup_tools,
    _task_tools,
)
from api.endpoints.mcp_tools._base import (
    _HITL_FENCED_TOOLS,
    _LAUNCH_GATE_TOOLS,
    _ORCHESTRATOR_PROFILE_TOOLS,
    PROFILE_CORE,
    PROFILE_FULL,
    PROFILE_STANDARD,
    SCOPE_AGENT,
    SCOPE_READ,
    SCOPE_WRITE,
    TOOL_PROFILES,
    TOOL_SCOPES,
    _call_tool,
    _get_tenant_manager,
    _get_tool_accessor,
    _parse_iso_datetime_param,
    _profile_toolset_from_request,
    _profile_toolset_from_state,
    _resolve_tenant,
    _resolve_user_id,
    _scopes_from_request,
    _set_tenant_context,
    logger,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import sync_annotation_titles


sync_annotation_titles(mcp._tool_manager.list_tools())


__all__ = [
    "PROFILE_CORE",
    "PROFILE_FULL",
    "PROFILE_STANDARD",
    "SCOPE_AGENT",
    "SCOPE_READ",
    "SCOPE_WRITE",
    "TOOL_PROFILES",
    "TOOL_SCOPES",
    "_HITL_FENCED_TOOLS",
    "_LAUNCH_GATE_TOOLS",
    "_ORCHESTRATOR_PROFILE_TOOLS",
    "_call_tool",
    "_chain_tools",
    "_comm_edit_tools",
    "_comm_tools",
    "_context_tools",
    "_get_tenant_manager",
    "_get_tool_accessor",
    "_job_tools",
    "_memory_tools",
    "_message_tools",
    "_parse_iso_datetime_param",
    "_profile_toolset_from_request",
    "_profile_toolset_from_state",
    "_project_tools",
    "_resolve_tenant",
    "_resolve_user_id",
    "_roadmap_tools",
    "_scopes_from_request",
    "_set_tenant_context",
    "_setup_tools",
    "_task_tools",
    "logger",
    "mcp",
    "sync_annotation_titles",
]
