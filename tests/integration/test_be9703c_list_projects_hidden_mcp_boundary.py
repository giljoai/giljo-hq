# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
import json
from unittest.mock import create_autospec

import pytest
import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_dispatch import attach_registry_service_autospecs
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


@pytest_asyncio.fixture
async def autospec_client(monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    accessor = create_autospec(ToolAccessor, instance=True)
    for attr_name in dir(ToolAccessor):
        if not attr_name.startswith("_") and inspect.iscoroutinefunction(getattr(ToolAccessor, attr_name, None)):
            getattr(accessor, attr_name).return_value = {"ok": True}
    attach_registry_service_autospecs(accessor, {"ok": True})
    state.tool_accessor = accessor
    state.tenant_manager = TenantManager()
    state.db_manager = None
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: TenantManager.generate_tenant_key())
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    try:
        yield lambda: create_connected_server_and_client_session(mcp)
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


@pytest.mark.asyncio
async def test_unknown_hidden_value_is_a_validation_error(autospec_client):
    async with autospec_client() as client:
        result = await client.call_tool("list_projects", {"hidden": "maybe"})
    assert result.is_error is False, result.content
    payload = json.loads(result.content[0].text)
    assert payload.get("error") == "VALIDATION_ERROR", payload
    assert payload.get("field") == "hidden", payload
