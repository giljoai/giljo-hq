# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest


class TestCorsClaudeConnectorOrigins:

    @pytest.mark.parametrize("origin", ["https://claude.ai", "https://claude.com"])
    @pytest.mark.asyncio
    async def test_preflight_allows_anthropic_connector_origin(self, api_client, origin):
        response = await api_client.options(
            "/mcp",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert response.status_code == 200, (
            f"Preflight for {origin} returned {response.status_code}; body: {response.text}"
        )
        echoed = response.headers.get("access-control-allow-origin", "")
        assert echoed == origin, f"Expected access-control-allow-origin: {origin}, got: {echoed!r}"


class TestCorsMcpProtocolHeaders:

    @pytest.mark.asyncio
    async def test_preflight_allows_mcp_protocol_version_header(self, api_client):
        response = await api_client.options(
            "/mcp",
            headers={
                "Origin": "https://claude.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "mcp-protocol-version,authorization,content-type",
            },
        )
        assert response.status_code == 200, response.text
        allowed_headers = response.headers.get("access-control-allow-headers", "").lower()
        assert "mcp-protocol-version" in allowed_headers, (
            f"MCP-Protocol-Version not in allow_headers: {allowed_headers!r}"
        )

    @pytest.mark.asyncio
    async def test_preflight_allows_mcp_session_id_header(self, api_client):
        response = await api_client.options(
            "/mcp",
            headers={
                "Origin": "https://claude.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "mcp-session-id,authorization,content-type",
            },
        )
        assert response.status_code == 200, response.text
        allowed_headers = response.headers.get("access-control-allow-headers", "").lower()
        assert "mcp-session-id" in allowed_headers, f"Mcp-Session-Id not in allow_headers: {allowed_headers!r}"
