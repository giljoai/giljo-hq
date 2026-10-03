# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
import json
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._base import MCP_ID_MAX
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_dispatch import attach_registry_service_autospecs
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


LONG_ID = "x" * (MCP_ID_MAX + 1)


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
    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    try:
        yield lambda: create_connected_server_and_client_session(mcp)
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


def _assert_validation_error(result, field: str) -> None:
    assert result.is_error is False, result.content
    payload = json.loads(result.content[0].text)
    assert payload.get("error") == "VALIDATION_ERROR", payload
    assert field in payload.get("field", ""), payload


REJECTED_CALLS = [
    ("unlink_projects", {"run_id": LONG_ID}, "run_id"),
    ("get_context", {"product_id": LONG_ID, "categories": ["product_core"]}, "product_id"),
    ("get_context", {"agent_name": "a" * 201, "categories": ["self_identity"]}, "agent_name"),
    ("get_context", {"categories": [LONG_ID]}, "categories"),
    ("get_context", {"categories": ["product_core"], "output_format": "foo"}, "output_format"),
    ("get_vision_document", {"product_id": LONG_ID}, "product_id"),
    ("stage_project", {"project_id": LONG_ID}, "project_id"),
    ("get_implementation_prompt", {"project_id": LONG_ID}, "project_id"),
    ("link_projects", {"project_ids": [str(uuid4()), LONG_ID]}, "project_ids"),
    ("link_projects", {"project_ids": [str(uuid4()), str(uuid4())], "ordered": [LONG_ID]}, "ordered"),
    ("update_thread", {"thread_id": str(uuid4()), "project_ids": [LONG_ID]}, "project_ids"),
    ("update_thread", {"thread_id": str(uuid4()), "project_ids": [str(uuid4()) for _ in range(51)]}, "project_ids"),
    ("list_threads", {"status": "archived"}, "status"),
    ("request_approval", {"job_id": LONG_ID, "project_id": str(uuid4()), "reason": "r", "options": []}, "job_id"),
    (
        "write_memory_entry",
        {
            "project_id": str(uuid4()),
            "summary": "s",
            "key_outcomes": [],
            "decisions_made": [],
            "author_job_id": LONG_ID,
        },
        "author_job_id",
    ),
    ("update_task", {"task_id": str(uuid4()), "hidden": "maybe"}, "hidden"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "arguments", "field"), REJECTED_CALLS)
async def test_malformed_argument_is_a_validation_error(autospec_client, tool, arguments, field):
    async with autospec_client() as session:
        result = await session.call_tool(tool, arguments)
    _assert_validation_error(result, field)


@pytest.mark.asyncio
async def test_update_thread_accepts_fifty_project_tags(autospec_client):
    async with autospec_client() as session:
        result = await session.call_tool(
            "update_thread", {"thread_id": str(uuid4()), "project_ids": [str(uuid4()) for _ in range(50)]}
        )
    assert result.is_error is False, result.content
    assert "VALIDATION_ERROR" not in result.content[0].text
