# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MCP @mcp.tool wrapper subpackage (BE-6042d).

The 2,263-line ``mcp_sdk_server.py`` god-module was split here. ``_base`` owns the
single ``FastMCP`` instance, the tool scope registry, and the shared dispatch
helpers. Each ``_*_tools`` module holds the @mcp.tool wrappers for one domain,
grouped to mirror the BE-6042a ``tool_accessor`` mixin map.

Importing this package imports every domain module, which is what triggers the
``@mcp.tool`` decorator side effects that register every tool on the shared
``mcp`` instance. The live registered count is roster-locked by
``tests/unit/test_be6042d_mcp_tool_registry_surface.py`` (not restated here to
avoid re-drifting on the next roster change). ``mcp_sdk_server`` imports this
package for exactly that effect and re-exports ``mcp`` + the shared helpers as
its public surface.

BE-9561: because that registration completes HERE, this is also the one place a
post-registration pass can run exactly once over the full roster --
``sync_annotation_titles()`` at the bottom copies each tool's canonical
``Tool.title`` into the legacy ``ToolAnnotations.title`` that Anthropic's
connector submission portal scans. See ``_tool_annotations.py``'s module
docstring for why both fields must be set and why the second is never
hand-maintained at the 49 wrapper call sites.
"""

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


# BE-9561: every @mcp.tool decorator has now fired, so the roster is complete and
# this runs exactly once, over all of it. Placed after the imports above rather
# than inside any one domain module for that reason -- a per-module call would
# see only its own slice.
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
