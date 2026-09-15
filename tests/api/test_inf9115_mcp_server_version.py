# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from importlib.metadata import version as _pkg_version

from api.endpoints.mcp_tools._base import mcp
from giljo_mcp import __version__ as giljo_version
from giljo_mcp import branding


def test_mcp_server_version_is_giljo_version():
    assert mcp.version == giljo_version


def test_mcp_server_version_is_not_the_sdk_package_fallback():
    sdk_fallback = _pkg_version("mcp")
    if sdk_fallback == giljo_version:
        return
    assert mcp.version != sdk_fallback


def test_live_initialize_handshake_reports_giljo_version():
    init_options = mcp._lowlevel_server.create_initialization_options()
    assert init_options.server_version == giljo_version
    assert init_options.server_name == branding.MCP_ALIAS
