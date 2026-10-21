# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.model_factories import make_product


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


def _paths_with_tenant_key(node: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "tenant_key":
                found.append(f"{path}.{key}")
            found.extend(_paths_with_tenant_key(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_paths_with_tenant_key(value, f"{path}[{index}]"))
    return found


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    product = make_product(tenant_key=tenant_key, name=f"Scrub Product {suffix}", is_active=True)
    db_session.add(product)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    accessor._task_service = TaskService(db_manager=db_manager, tenant_manager=state.tenant_manager, session=db_session)
    state.tool_accessor = accessor
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant_key, product.id
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.execute(delete(Product).where(Product.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _call(client, name: str, args: dict[str, Any]) -> dict:
    async with client() as session:
        result = await session.call_tool(name, args)
    assert result.is_error is False, _error_text(result)
    return _payload(result)


def _assert_scrubbed(payload: dict, tool: str) -> None:
    assert _paths_with_tenant_key(payload) == [], f"{tool} reply leaks tenant_key"
    assert payload["_meta"]["skills_version"]


async def test_create_thread_reply_has_no_tenant_key(mcp_client):
    client, tenant_key, _pid = mcp_client
    payload = await _call(client, "create_thread", {"subject": "scrub", "creator_id": "agent-alpha"})
    assert payload["chat_id"].startswith("CHT-")
    _assert_scrubbed(payload, "create_thread")
    assert tenant_key not in json.dumps(payload)


async def test_create_task_reply_has_no_tenant_key(mcp_client):
    client, tenant_key, pid = mcp_client
    payload = await _call(
        client, "create_task", {"title": "scrub me", "description": "mutation reply", "product_id": pid}
    )
    _assert_scrubbed(payload, "create_task")
    assert tenant_key not in json.dumps(payload)


async def test_list_tasks_reply_has_no_tenant_key(mcp_client):
    client, tenant_key, pid = mcp_client
    await _call(client, "create_task", {"title": "listed", "description": "row", "product_id": pid})
    payload = await _call(client, "list_tasks", {"product_id": pid, "mode": "full"})
    assert payload["tasks"], "fixture must yield at least one task row so the walk is not vacuous"
    _assert_scrubbed(payload, "list_tasks")
    assert tenant_key not in json.dumps(payload)


async def test_get_context_reply_has_no_tenant_key(mcp_client):
    client, tenant_key, pid = mcp_client
    payload = await _call(client, "get_context", {"product_id": pid, "categories": ["products", "product_core"]})
    _assert_scrubbed(payload, "get_context")
    assert tenant_key not in json.dumps(payload)


async def test_scrub_removes_the_key_at_every_depth_and_keeps_everything_else():
    from api.endpoints.mcp_tools._reply_scrub import scrub_tenant_key

    reply = {
        "tenant_key": "tk_top",
        "metadata": {"count": 1, "tenant_key": "tk_nested"},
        "data": [{"id": "a", "tenant_key": "tk_row", "tags": [{"tenant_key": "tk_deep", "name": "x"}]}, "plain", 3],
        "tenant_keys_seen": 2,
    }
    assert scrub_tenant_key(reply) == {
        "metadata": {"count": 1},
        "data": [{"id": "a", "tags": [{"name": "x"}]}, "plain", 3],
        "tenant_keys_seen": 2,
    }
