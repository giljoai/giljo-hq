# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression tests for INF-9115 — MCP serverInfo.version SSoT fix.

FastMCP (mcp SDK 1.27.2) has no ``version=`` constructor kwarg. Without a
post-construction ``mcp._mcp_server.version`` assignment, the SDK's own
``Server.create_initialization_options()`` falls back to
``importlib.metadata.version("mcp")`` — the installed SDK PACKAGE's version,
not the GiljoAI product version — so every real MCP client's ``initialize``
handshake reported ``serverInfo.version == "1.27.2"`` instead of the VERSION
file's value.

``create_initialization_options()`` is the exact method
``StreamableHTTPSessionManager`` calls to build the response a live client
receives on ``initialize`` (mcp/server/streamable_http_manager.py:200,302) —
calling it directly here drives the same code path a real handshake hits,
not a mock.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

from api.endpoints.mcp_tools._base import mcp
from giljo_mcp import __version__ as giljo_version
from giljo_mcp import branding


def test_mcp_server_version_is_giljo_version():
    """The regression guard the WO mandates: the server's version is the PRODUCT version.

    INF-9371 re-point: 1.x had no ``version=`` constructor kwarg, so the value was
    patched on afterwards and read back off ``mcp._mcp_server.version``. SDK 2.0
    declares the kwarg and exposes ``MCPServer.version`` (read-only), so the same
    guarantee is now asserted through the public property. The assertion is unchanged
    -- what moved is where the SDK keeps the value.
    """
    assert mcp.version == giljo_version


def test_mcp_server_version_is_not_the_sdk_package_fallback():
    """Without the explicit version the SDK falls back to its own package version."""
    sdk_fallback = _pkg_version("mcp")
    if sdk_fallback == giljo_version:
        return  # coincidental version match; the declaration still holds (prior assertion)
    assert mcp.version != sdk_fallback


def test_live_initialize_handshake_reports_giljo_version():
    """Live handshake proof: the same call StreamableHTTPSessionManager makes
    per-connection to build the initialize response's serverInfo."""
    init_options = mcp._lowlevel_server.create_initialization_options()
    assert init_options.server_version == giljo_version
    assert init_options.server_name == branding.MCP_ALIAS
