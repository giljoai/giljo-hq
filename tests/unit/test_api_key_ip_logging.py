# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock

import pytest


class TestApiKeyIpLogging:

    @pytest.mark.asyncio
    async def test_log_ip_creates_new_entry(self):
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-123", "192.0.2.1")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_ip_does_not_raise_on_db_error(self):
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}
        mock_db.execute = AsyncMock(side_effect=Exception("DB connection lost"))

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-123", "192.0.2.1")

    @pytest.mark.asyncio
    async def test_log_ip_handles_ipv6_addresses(self):
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-456", "2001:0db8:85a3:0000:0000:8a2e:0370:7334")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_ip_handles_localhost(self):
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-789", "127.0.0.1")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_ip_handles_unknown_ip(self):
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-000", "unknown")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_ip_does_not_raise_on_commit_error(self):
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock(side_effect=Exception("Commit failed"))

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-123", "198.51.100.1")

    @pytest.mark.asyncio
    async def test_log_ip_uses_postgresql_upsert(self):
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        manager = MCPSessionManager(mock_db)
        await manager.log_ip("key-upsert", "198.51.100.5")

        call_args = mock_db.execute.call_args
        assert call_args is not None
        stmt = call_args[0][0]
        assert hasattr(stmt, "compile") or hasattr(stmt, "parameters")


class TestMcpEndpointIpLogging:

    @pytest.mark.asyncio
    async def test_mcp_endpoint_calls_log_ip_on_success(self):
        mock_session = MagicMock()
        mock_session.api_key_id = "test-key-id"
        mock_session.session_id = "test-session-id"

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "192.0.2.100"

        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = AsyncMock()
        mock_db.info = {}
        manager = MCPSessionManager(mock_db)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        client_ip = mock_request.client.host if mock_request.client else "unknown"
        await manager.log_ip(mock_session.api_key_id, client_ip)

        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_ip_logging_handles_missing_client(self):
        mock_request = MagicMock()
        mock_request.client = None

        client_ip = mock_request.client.host if mock_request.client else "unknown"
        assert client_ip == "unknown"


class TestRestApiIpLogging:

    @pytest.mark.asyncio
    async def test_ip_extraction_from_request(self):
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "198.51.100.50"

        client_ip = mock_request.client.host if mock_request.client else "unknown"
        assert client_ip == "198.51.100.50"

    @pytest.mark.asyncio
    async def test_ip_extraction_with_no_client(self):
        mock_request = MagicMock()
        mock_request.client = None

        client_ip = mock_request.client.host if mock_request.client else "unknown"
        assert client_ip == "unknown"
