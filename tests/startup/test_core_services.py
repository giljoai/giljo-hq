# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for core services initialization module"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.app_state import APIState


@pytest.mark.asyncio
async def test_init_core_services_initializes_tenant_manager():
    """Should initialize TenantManager on state"""
    from api.startup.core_services import init_core_services

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()

    with (
        patch("api.startup.core_services.TenantManager") as mock_tenant_mgr,
        patch("api.startup.core_services.WebSocketManager"),
        patch("api.startup.core_services.ToolAccessor"),
        patch("api.startup.core_services.AuthManager"),
        patch("api.startup.core_services.asyncio.create_task"),
        patch.dict(os.environ, {}, clear=True),
    ):
        await init_core_services(state)

        mock_tenant_mgr.assert_called_once()
        assert state.tenant_manager is not None


@pytest.mark.asyncio
async def test_init_core_services_initializes_websocket_manager():
    """Should initialize WebSocketManager before ToolAccessor"""
    from api.startup.core_services import init_core_services

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()

    with (
        patch("api.startup.core_services.TenantManager"),
        patch("api.startup.core_services.WebSocketManager") as mock_ws_mgr,
        patch("api.startup.core_services.ToolAccessor"),
        patch("api.startup.core_services.AuthManager"),
        patch("api.startup.core_services.asyncio.create_task"),
        patch.dict(os.environ, {}, clear=True),
    ):
        await init_core_services(state)

        mock_ws_mgr.assert_called_once()
        assert state.websocket_manager is not None


@pytest.mark.asyncio
async def test_init_core_services_initializes_tool_accessor():
    """ToolAccessor should be initialized with db_manager, tenant_manager, websocket_manager"""
    from api.startup.core_services import init_core_services

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()

    with (
        patch("api.startup.core_services.TenantManager") as mock_tenant_mgr,
        patch("api.startup.core_services.WebSocketManager") as mock_ws_mgr,
        patch("api.startup.core_services.ToolAccessor") as mock_tool_accessor,
        patch("api.startup.core_services.AuthManager"),
        patch("api.startup.core_services.asyncio.create_task"),
        patch.dict(os.environ, {}, clear=True),
    ):
        mock_tenant_instance = MagicMock()
        mock_tenant_mgr.return_value = mock_tenant_instance

        mock_ws_instance = MagicMock()
        mock_ws_mgr.return_value = mock_ws_instance

        await init_core_services(state)

        # Verify ToolAccessor was called with all required dependencies
        mock_tool_accessor.assert_called_once_with(
            state.db_manager, mock_tenant_instance, websocket_manager=mock_ws_instance
        )
        assert state.tool_accessor is not None


@pytest.mark.asyncio
async def test_init_core_services_initializes_auth_manager():
    """AuthManager should be initialized with config and db=None"""
    from api.startup.core_services import init_core_services

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()

    with (
        patch("api.startup.core_services.TenantManager"),
        patch("api.startup.core_services.WebSocketManager"),
        patch("api.startup.core_services.ToolAccessor"),
        patch("api.startup.core_services.AuthManager") as mock_auth,
        patch("api.startup.core_services.asyncio.create_task"),
        patch.dict(os.environ, {}, clear=True),
    ):
        await init_core_services(state)

        mock_auth.assert_called_once_with(state.config, db=None)
        assert state.auth is not None


@pytest.mark.asyncio
async def test_init_core_services_loads_api_key_from_env():
    """Should load API_KEY from environment if available"""
    from api.startup.core_services import init_core_services

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()

    api_key = "test_api_key" + "_12345678"

    with (
        patch("api.startup.core_services.TenantManager"),
        patch("api.startup.core_services.WebSocketManager"),
        patch("api.startup.core_services.ToolAccessor"),
        patch("api.startup.core_services.AuthManager") as mock_auth,
        patch("api.startup.core_services.asyncio.create_task"),
        patch.dict(os.environ, {"API_KEY": api_key}),
    ):
        mock_auth_instance = MagicMock()
        mock_auth_instance.api_keys = {}
        mock_auth.return_value = mock_auth_instance

        await init_core_services(state)

        # Verify API key was added to AuthManager
        assert api_key in state.auth.api_keys
        assert state.auth.api_keys[api_key]["name"] == "Installer Generated"
        assert state.auth.api_keys[api_key]["active"] is True


@pytest.mark.asyncio
async def test_init_core_services_loads_giljo_mcp_api_key():
    """Should load GILJO_MCP_API_KEY as fallback"""
    from api.startup.core_services import init_core_services

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()

    api_key = "giljo_key" + "_87654321"

    with (
        patch("api.startup.core_services.TenantManager"),
        patch("api.startup.core_services.WebSocketManager"),
        patch("api.startup.core_services.ToolAccessor"),
        patch("api.startup.core_services.AuthManager") as mock_auth,
        patch("api.startup.core_services.asyncio.create_task"),
        patch.dict(os.environ, {"GILJO_MCP_API_KEY": api_key}),
    ):
        mock_auth_instance = MagicMock()
        mock_auth_instance.api_keys = {}
        mock_auth.return_value = mock_auth_instance

        await init_core_services(state)

        # Verify API key was added
        assert api_key in state.auth.api_keys


@pytest.mark.asyncio
async def test_init_core_services_starts_heartbeat_task():
    """Should start WebSocket heartbeat task"""
    from api.startup.core_services import init_core_services

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()

    with (
        patch("api.startup.core_services.TenantManager"),
        patch("api.startup.core_services.WebSocketManager") as mock_ws_mgr,
        patch("api.startup.core_services.ToolAccessor"),
        patch("api.startup.core_services.AuthManager"),
        patch("api.startup.core_services.asyncio.create_task") as mock_create_task,
        patch.dict(os.environ, {}, clear=True),
    ):
        mock_ws_instance = MagicMock()
        mock_ws_instance.start_heartbeat = MagicMock(return_value=AsyncMock())
        mock_ws_mgr.return_value = mock_ws_instance

        mock_task = MagicMock()
        mock_create_task.return_value = mock_task

        await init_core_services(state)

        # Verify heartbeat task was created
        mock_create_task.assert_called_once()
        assert state.heartbeat_task is not None


@pytest.mark.asyncio
async def test_init_core_services_correct_initialization_order():
    """Services must be initialized in correct order: TenantManager → WebSocketManager → ToolAccessor → AuthManager"""
    from api.startup.core_services import init_core_services

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()

    call_order = []

    def track_tenant_mgr():
        call_order.append("tenant")
        return MagicMock()

    def track_ws_mgr():
        call_order.append("websocket")
        return MagicMock()

    def track_tool_accessor(*args, **kwargs):
        call_order.append("tool_accessor")
        return MagicMock()

    def track_auth_mgr(*args, **kwargs):
        call_order.append("auth")
        mock_auth = MagicMock()
        mock_auth.api_keys = {}
        return mock_auth

    with (
        patch("api.startup.core_services.TenantManager", side_effect=track_tenant_mgr),
        patch("api.startup.core_services.WebSocketManager", side_effect=track_ws_mgr),
        patch("api.startup.core_services.ToolAccessor", side_effect=track_tool_accessor),
        patch("api.startup.core_services.AuthManager", side_effect=track_auth_mgr),
        patch("api.startup.core_services.asyncio.create_task"),
        patch.dict(os.environ, {}, clear=True),
    ):
        await init_core_services(state)

        # Verify order
        assert call_order == ["tenant", "websocket", "tool_accessor", "auth"]


@pytest.mark.asyncio
async def test_auth_manager_failure_aborts_boot_and_leaves_state_auth_unset():
    """SEC-9572: the four core-service blocks are FATAL by design, not "non-fatal".

    Their comments used to read "startup resilience, non-fatal initialization"
    while the bodies re-raised. Production proved the code right and the comment
    wrong -- a worker whose AuthManager raised did not degrade, it died, and took
    the uvicorn parent with it. This pins the behaviour so the comment cannot
    drift back: a half-built AuthManager must abort boot, because ``state.auth``
    stays None and AuthMiddleware is wired with a callable that never reaches its
    own not-configured guard.
    """
    from api.startup.core_services import init_core_services

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()

    with (
        patch("api.startup.core_services.TenantManager"),
        patch("api.startup.core_services.WebSocketManager"),
        patch("api.startup.core_services.ToolAccessor"),
        patch(
            "api.startup.core_services.AuthManager",
            side_effect=ValueError("Fernet key must be 32 url-safe base64-encoded bytes."),
        ),
        patch("api.startup.core_services.asyncio.create_task"),
        patch.dict(os.environ, {}, clear=True),
        pytest.raises(ValueError, match="Fernet key"),
    ):
        await init_core_services(state)

    assert state.auth is None
