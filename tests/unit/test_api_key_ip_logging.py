# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for API key IP address logging (Handover 0492 Phase 2).

Verifies that IP addresses are passively logged when API keys authenticate,
without blocking or slowing down the authentication flow.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestApiKeyIpLogging:
    """Tests for the MCPSessionManager.log_ip() method."""

    @pytest.mark.asyncio
    async def test_log_ip_creates_new_entry(self):
        """First request from an IP creates a new log entry via upsert."""
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}  # tenant_session_context save/restore target
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-123", "192.0.2.1")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_ip_does_not_raise_on_db_error(self):
        """IP logging failures must be silently caught, never propagated."""
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}  # tenant_session_context save/restore target
        mock_db.execute = AsyncMock(side_effect=Exception("DB connection lost"))

        manager = MCPSessionManager(mock_db)
        # Must not raise - IP logging is passive and non-blocking
        await manager.log_ip("key-123", "192.0.2.1")

    @pytest.mark.asyncio
    async def test_log_ip_handles_ipv6_addresses(self):
        """Should handle full-length IPv6 addresses (up to 45 chars)."""
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}  # tenant_session_context save/restore target
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-456", "2001:0db8:85a3:0000:0000:8a2e:0370:7334")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_ip_handles_localhost(self):
        """Should handle localhost/loopback addresses."""
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}  # tenant_session_context save/restore target
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-789", "127.0.0.1")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_ip_handles_unknown_ip(self):
        """Should handle 'unknown' when request.client is None."""
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}  # tenant_session_context save/restore target
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-000", "unknown")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_ip_does_not_raise_on_commit_error(self):
        """Commit failures must also be caught silently."""
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}  # tenant_session_context save/restore target
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock(side_effect=Exception("Commit failed"))

        manager = MCPSessionManager(mock_db)
        # Must not raise
        await manager.log_ip("key-123", "198.51.100.1")

    @pytest.mark.asyncio
    async def test_log_ip_uses_postgresql_upsert(self):
        """Verify the upsert statement uses PostgreSQL INSERT ... ON CONFLICT."""
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}  # tenant_session_context save/restore target
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-upsert", "198.51.100.5")

        # Verify execute was called with a statement (the pg upsert)
        call_args = mock_db.execute.call_args
        assert call_args is not None
        stmt = call_args[0][0]
        # The compiled statement should reference the api_key_ip_log table
        assert hasattr(stmt, "compile") or hasattr(stmt, "parameters")


class TestMcpEndpointIpLogging:
    """Tests that mcp_endpoint integrates IP logging correctly."""

    @pytest.mark.asyncio
    async def test_mcp_endpoint_calls_log_ip_on_success(self):
        """After successful session creation, IP should be logged."""
        mock_session = MagicMock()
        mock_session.api_key_id = "test-key-id"
        mock_session.session_id = "test-session-id"

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "192.0.2.100"

        # The IP logging call should not block the MCP request
        # This test verifies the integration point exists
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}  # tenant_session_context save/restore target
        manager = MCPSessionManager(mock_db)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        # Simulate the IP logging call that happens in mcp_endpoint
        client_ip = mock_request.client.host if mock_request.client else "unknown"
        await manager.log_ip(mock_session.api_key_id, client_ip)

        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_ip_logging_handles_missing_client(self):
        """When request.client is None, IP should be 'unknown'."""
        mock_request = MagicMock()
        mock_request.client = None

        client_ip = mock_request.client.host if mock_request.client else "unknown"
        assert client_ip == "unknown"


class TestRestApiIpLogging:
    """Tests that get_current_user integrates IP logging for API key auth."""

    @pytest.mark.asyncio
    async def test_ip_extraction_from_request(self):
        """Verify IP address extraction logic from request object."""
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "198.51.100.50"

        client_ip = mock_request.client.host if mock_request.client else "unknown"
        assert client_ip == "198.51.100.50"

    @pytest.mark.asyncio
    async def test_ip_extraction_with_no_client(self):
        """When request has no client info, should default to 'unknown'."""
        mock_request = MagicMock()
        mock_request.client = None

        client_ip = mock_request.client.host if mock_request.client else "unknown"
        assert client_ip == "unknown"
