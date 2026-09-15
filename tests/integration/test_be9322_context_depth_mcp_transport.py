# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def depth_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    tenant_switch = _TenantSwitch(primary_tenant_key)
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_switch
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def test_tech_stack_depth_config_forwarded_as_sections_through_mcp_boundary(
    depth_mcp_client, primary_tenant_key, monkeypatch
):
    new_client, _switch = depth_mcp_client

    captured_kwargs: dict = {}

    async def fake_get_tech_stack(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "source": "tech_stack",
            "data": {"programming_languages": "Python"},
            "metadata": {"product_id": kwargs.get("product_id"), "tenant_key": kwargs.get("tenant_key")},
        }

    import sys

    import giljo_mcp.tools.context_tools.fetch_context  # noqa: F401 -- force submodule import

    fetch_module = sys.modules["giljo_mcp.tools.context_tools.fetch_context"]

    monkeypatch.setitem(fetch_module.CATEGORY_TOOLS, "tech_stack", AsyncMock(side_effect=fake_get_tech_stack))

    sentinel_product_id = "22222222-2222-2222-2222-222222222222"

    async with new_client() as session:
        result = await session.call_tool(
            "get_context",
            {
                "product_id": sentinel_product_id,
                "categories": ["tech_stack"],
                "depth_config": {"tech_stack": "required"},
            },
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert captured_kwargs.get("sections") == "required", (
        f"BE-9322 wrapper regression: 'required' override not forwarded as sections=. captured={captured_kwargs!r}"
    )
    assert captured_kwargs.get("tenant_key") == primary_tenant_key
    assert "tech_stack" in payload.get("categories_returned", [])


async def test_architecture_depth_config_still_not_forwarded_through_mcp_boundary(
    depth_mcp_client, primary_tenant_key, monkeypatch
):
    new_client, _switch = depth_mcp_client

    captured_kwargs: dict = {}

    async def fake_get_architecture(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "source": "architecture",
            "data": {"primary_pattern": "Layered"},
            "metadata": {"product_id": kwargs.get("product_id"), "tenant_key": kwargs.get("tenant_key")},
        }

    import sys

    import giljo_mcp.tools.context_tools.fetch_context  # noqa: F401 -- force submodule import

    fetch_module = sys.modules["giljo_mcp.tools.context_tools.fetch_context"]

    monkeypatch.setitem(fetch_module.CATEGORY_TOOLS, "architecture", AsyncMock(side_effect=fake_get_architecture))

    sentinel_product_id = "33333333-3333-3333-3333-333333333333"

    async with new_client() as session:
        result = await session.call_tool(
            "get_context",
            {
                "product_id": sentinel_product_id,
                "categories": ["architecture"],
                "depth_config": {"architecture": "overview"},
            },
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert "depth" not in captured_kwargs, f"depth_architecture must stay unwired -- got kwargs={captured_kwargs!r}"
    assert captured_kwargs.get("tenant_key") == primary_tenant_key
    assert "architecture" in payload.get("categories_returned", [])




async def _capture_category_kwargs(
    depth_mcp_client, monkeypatch, *, category: str, depth_value, product_id: str
) -> dict:
    import sys

    new_client, _switch = depth_mcp_client
    captured: dict = {}

    async def _fake(**kwargs):
        captured.update(kwargs)
        return {"source": category, "data": {}, "metadata": {}}

    import giljo_mcp.tools.context_tools.fetch_context  # noqa: F401 -- force submodule import

    fetch_module = sys.modules["giljo_mcp.tools.context_tools.fetch_context"]
    monkeypatch.setitem(fetch_module.CATEGORY_TOOLS, category, AsyncMock(side_effect=_fake))

    async with new_client() as session:
        result = await session.call_tool(
            "get_context",
            {"product_id": product_id, "categories": [category], "depth_config": {category: depth_value}},
        )
        assert result.is_error is False, _error_text(result)

    return captured


async def test_git_history_depth_forwarded_as_commits(depth_mcp_client, monkeypatch):
    captured = await _capture_category_kwargs(
        depth_mcp_client,
        monkeypatch,
        category="git_history",
        depth_value=5,
        product_id="44444444-4444-4444-4444-444444444444",
    )
    assert captured.get("commits") == 5, f"git_commits depth not forwarded. captured={captured!r}"


async def test_vision_documents_depth_forwarded_as_chunking(depth_mcp_client, monkeypatch):
    captured = await _capture_category_kwargs(
        depth_mcp_client,
        monkeypatch,
        category="vision_documents",
        depth_value="full",
        product_id="55555555-5555-5555-5555-555555555555",
    )
    assert captured.get("chunking") == "full", f"vision depth not forwarded. captured={captured!r}"


async def test_memory_360_depth_forwarded_as_last_n_projects(depth_mcp_client, monkeypatch):
    captured = await _capture_category_kwargs(
        depth_mcp_client,
        monkeypatch,
        category="memory_360",
        depth_value=1,
        product_id="66666666-6666-6666-6666-666666666666",
    )
    assert captured.get("last_n_projects") == 1, f"memory depth not forwarded. captured={captured!r}"


async def test_agent_templates_depth_forwarded_as_detail(depth_mcp_client, monkeypatch):
    captured = await _capture_category_kwargs(
        depth_mcp_client,
        monkeypatch,
        category="agent_templates",
        depth_value="full",
        product_id="77777777-7777-7777-7777-777777777777",
    )
    assert captured.get("detail") == "full", f"agent_templates depth not forwarded. captured={captured!r}"


async def test_db_style_depth_key_is_rejected_not_silently_defaulted(depth_mcp_client):
    new_client, _switch = depth_mcp_client

    async with new_client() as session:
        result = await session.call_tool(
            "get_context",
            {
                "product_id": "88888888-8888-8888-8888-888888888888",
                "categories": ["memory_360"],
                "depth_config": {"memory_last_n_projects": 1},
            },
        )

    assert result.is_error is True, (
        "BE-9322 Finding 3: a DB-style depth key was accepted instead of rejected -- "
        "it silently applies the default and nothing names the dropped key."
    )
    text = _error_text(result)
    assert "memory_last_n_projects" in text, f"error must name the offending key, got: {text}"
    assert "memory_360" in text, f"error must enumerate the accepted vocabulary, got: {text}"


async def test_valid_category_depth_key_still_accepted(depth_mcp_client, monkeypatch):
    captured = await _capture_category_kwargs(
        depth_mcp_client,
        monkeypatch,
        category="memory_360",
        depth_value=10,
        product_id="99999999-9999-9999-9999-999999999999",
    )
    assert captured.get("last_n_projects") == 10
