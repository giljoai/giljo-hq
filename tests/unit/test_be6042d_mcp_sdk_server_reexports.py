# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-6042d re-export surface lock for api/endpoints/mcp_sdk_server.py.

The set-equality registry test guards that tools REGISTER, but it would pass even
if the module-level Python re-export surface broke — because tools register on the
shared ``mcp`` instance regardless of whether ``mcp_sdk_server.giljo_setup`` is
still importable as a module attribute.

External code imports these names DIRECTLY from ``api.endpoints.mcp_sdk_server``
(verified by grep across api/, src/, tests/, scripts/). After the wrapper split
moves the @mcp.tool functions and shared helpers into the ``mcp_tools/``
subpackage, ``mcp_sdk_server`` MUST keep re-exporting every one of them, both via
``from ... import NAME`` and via ``mcp_sdk_server.NAME`` attribute access.
"""

from __future__ import annotations

import inspect

import api.endpoints.mcp_sdk_server as sdk


# Named imports used by production + test code (from ... import NAME).
# The @mcp.tool wrapper names + _PLACEHOLDER_JOB_IDS are imported DIRECTLY from
# mcp_sdk_server by existing tests (test_0411a imports spawn_job; test_0435a/b
# import _PLACEHOLDER_JOB_IDS; test_ce_0033 inspects get_context/report_progress
# source). After BE-6042d moved them into mcp_tools/, the re-export must persist —
# this list locks the names that have a proven external consumer.
# INF-6052a: fetch_context renamed to get_context; update re-export surface.
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

# Attribute-style access used by tests (mcp_sdk_server.NAME(...)).
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
    """giljo_setup + _call_tool must remain async callables on the module."""
    for name in ("giljo_setup", "_call_tool"):
        attr = getattr(sdk, name)
        assert inspect.iscoroutinefunction(attr), f"{name} must remain an async callable"


def test_mcp_instance_is_the_sdk_server():
    """The shared instance is the SDK's server object.

    INF-9371: SDK 2.0 renamed ``FastMCP`` to ``MCPServer`` and deleted
    ``mcp.server.fastmcp``. Only the class name moved — this still asserts the
    same thing it always did, that ``mcp_sdk_server.mcp`` is the SDK's server and
    not a stand-in of ours.
    """
    from mcp.server.mcpserver import MCPServer

    assert isinstance(sdk.mcp, MCPServer)
