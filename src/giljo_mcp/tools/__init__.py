# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Giljo HQ Tools Package

All MCP tools are registered in api/endpoints/mcp_sdk_server.py via FastMCP SDK
and delegate to ToolAccessor methods which use the service layer.

Transport: Streamable HTTP (Anthropic MCP SDK) at /mcp endpoint.
Auth: Bearer token (JWT or API key) via MCPAuthMiddleware.
See: docs/api/MCP_OVER_HTTP_INTEGRATION.md
"""

__all__: list[str] = []
