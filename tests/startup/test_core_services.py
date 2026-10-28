# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.app_state import APIState


@pytest.mark.asyncio
async def test_init_core_services_initializes_tenant_manager():
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

        mock_tool_accessor.assert_called_once_with(
            state.db_manager, mock_tenant_instance, websocket_manager=mock_ws_instance
        )
        assert state.tool_accessor is not None


@pytest.mark.asyncio
async def test_init_core_services_initializes_auth_manager():
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
        patch.dict(os.environ, {"API_KEY": api_key, "GILJO_MODE": "ce"}),
    ):
        mock_auth_instance = MagicMock()
        mock_auth_instance.api_keys = {}
        mock_auth.return_value = mock_auth_instance

        await init_core_services(state)

        assert api_key in state.auth.api_keys
        assert state.auth.api_keys[api_key]["name"] == "Installer Generated"
        assert state.auth.api_keys[api_key]["active"] is True


@pytest.mark.asyncio
async def test_init_core_services_loads_giljo_mcp_api_key():
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
        patch.dict(os.environ, {"GILJO_MCP_API_KEY": api_key, "GILJO_MODE": "ce"}),
    ):
        mock_auth_instance = MagicMock()
        mock_auth_instance.api_keys = {}
        mock_auth.return_value = mock_auth_instance

        await init_core_services(state)

        assert api_key in state.auth.api_keys


@pytest.mark.asyncio
async def test_init_core_services_starts_heartbeat_task():
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

        mock_create_task.assert_called_once()
        assert state.heartbeat_task is not None


@pytest.mark.asyncio
async def test_init_core_services_correct_initialization_order():
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

        assert call_order == ["tenant", "websocket", "tool_accessor", "auth"]


@pytest.mark.asyncio
async def test_auth_manager_failure_aborts_boot_and_leaves_state_auth_unset():
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


async def _boot_core_services_with_installer_key(monkeypatch, tmp_path, *, mode: str, variable: str, key: str):
    from api.startup.core_services import init_core_services

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "sec9824_test_secret")
    monkeypatch.setenv("GILJO_MODE", mode)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("GILJO_MCP_API_KEY", raising=False)
    monkeypatch.setenv(variable, key)

    state = APIState()
    state.db_manager = MagicMock()
    state.config = MagicMock()
    with (
        patch("api.startup.core_services.TenantManager"),
        patch("api.startup.core_services.WebSocketManager"),
        patch("api.startup.core_services.ToolAccessor"),
        patch("api.startup.core_services.asyncio.create_task"),
    ):
        await init_core_services(state)
    return state


def _request_with_x_api_key(key: str):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/anything",
        "headers": [(b"x-api-key", key.encode())],
        "app": MagicMock(state=MagicMock(db_manager=None)),
    }
    return Request(scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("variable", ["API_KEY", "GILJO_MCP_API_KEY"])
async def test_saas_mode_refuses_the_static_installer_key(monkeypatch, tmp_path, caplog, variable):
    key = "sec9824_static" + "_key_value_0001"
    with caplog.at_level("WARNING"):
        state = await _boot_core_services_with_installer_key(
            monkeypatch, tmp_path, mode="saas", variable=variable, key=key
        )

    assert key not in state.auth.api_keys
    assert state.auth.validate_api_key(key) is None
    result = await state.auth.authenticate_request(_request_with_x_api_key(key))
    assert result["authenticated"] is False

    warnings = [r for r in caplog.records if r.levelname == "WARNING" and variable in r.getMessage()]
    assert len(warnings) == 1
    assert all(key not in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("variable", ["API_KEY", "GILJO_MCP_API_KEY"])
async def test_ce_mode_still_accepts_the_static_installer_key(monkeypatch, tmp_path, variable):
    key = "sec9824_static" + "_key_value_0002"
    state = await _boot_core_services_with_installer_key(monkeypatch, tmp_path, mode="ce", variable=variable, key=key)

    assert state.auth.validate_api_key(key) is not None


def test_config_manager_ignores_the_static_installer_key_in_saas(monkeypatch):
    from giljo_mcp.config_manager import ConfigManager

    monkeypatch.setenv("GILJO_MCP_API_KEY", "sec9824_cfg" + "_key_value_0003")
    monkeypatch.setenv("GILJO_MODE", "saas")
    saas = ConfigManager()
    monkeypatch.setenv("GILJO_MODE", "ce")
    ce = ConfigManager()

    assert saas.server.api_key is None
    assert ce.server.api_key == "sec9824_cfg" + "_key_value_0003"
