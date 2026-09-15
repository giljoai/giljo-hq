# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect

import api.endpoints.mcp_sdk_server as sdk


NAMED_IMPORT_SURFACE = [
    "mcp",
    "TOOL_SCOPES",
    "get_mcp_asgi_app",
    "start_mcp_session_manager",
    "stop_mcp_session_manager",
    "MCPAuthMiddleware",
    "_parse_iso_datetime_param",
    "_call_tool",
    "_PLACEHOLDER_JOB_IDS",
    "spawn_job",
    "report_progress",
    "get_context",
]

ATTRIBUTE_ACCESS_SURFACE = [
    "mcp",
    "giljo_setup",
    "_call_tool",
    "spawn_job",
    "report_progress",
    "get_context",
]


def test_named_import_surface_present():
    for name in NAMED_IMPORT_SURFACE:
        assert hasattr(sdk, name), f"mcp_sdk_server must re-export {name!r}"


def test_attribute_access_surface_present():
    for name in ATTRIBUTE_ACCESS_SURFACE:
        assert hasattr(sdk, name), f"mcp_sdk_server.{name} must be attribute-accessible"


def test_tool_wrapper_callables_reexported_and_async():
    for name in ("giljo_setup", "_call_tool"):
        attr = getattr(sdk, name)
        assert inspect.iscoroutinefunction(attr), f"{name} must remain an async callable"


def test_mcp_instance_is_the_sdk_server():
    from mcp.server.mcpserver import MCPServer

    assert isinstance(sdk.mcp, MCPServer)
