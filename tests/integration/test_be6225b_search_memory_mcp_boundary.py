# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Transport-layer tests for the ``search_memory`` MCP tool (BE-6225b).

Regression-at-the-failing-layer: ``search_memory`` is an @mcp.tool wrapper, so the
BE-5042 lesson applies — exercise it through the in-memory FastMCP transport, not
just the service. These tests drive the wrapper's kwarg-unpacking + ``_call_tool``
dispatch + tenant_key injection + active-product resolution + the length-cap →
422 surfacing.

Proves the BE-6225b DoD:
- a matching query returns the right tenant-scoped headlines (with score + tags);
- an empty query and a no-match query return a clean empty result (NOT an error);
- an over-length query (> MCP_SHORT_TEXT_MAX) surfaces a 422-class isError;
- a cross-tenant memory entry never leaks into another tenant's search.

Pattern reference: ``tests/integration/test_roadmap_tools_mcp_transport.py`` — same
in-memory ``create_connected_server_and_client_session`` transport + the
``_resolve_tenant`` monkeypatch + a ToolAccessor bound to the rolled-back session.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from api.endpoints.mcp_tools._base import MCP_SHORT_TEXT_MAX
from giljo_mcp.models import Product, Project
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
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


async def _seed_active_product(db_session, tenant_key: str) -> str:
    """Seed org + active product + one project for a tenant; return product_id."""
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid.uuid4()),
        name=f"Product {suffix}",
        description="search_memory transport test product",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="desc",
        mission="mission",
    )
    db_session.add(project)
    await db_session.flush()
    return product.id, project.id


async def _seed_memory_entry(
    db_session,
    tenant_key: str,
    product_id: str,
    project_id: str,
    sequence: int,
    summary: str,
    key_outcomes: list[str],
    tags: list[str],
) -> None:
    entry = ProductMemoryEntry(
        id=uuid.uuid4(),
        tenant_key=tenant_key,
        product_id=product_id,
        project_id=project_id,
        sequence=sequence,
        entry_type="project_completion",
        source="test",
        timestamp=datetime.now(UTC),
        project_name=f"Project seq {sequence}",
        summary=summary,
        key_outcomes=key_outcomes,
        decisions_made=[],
        tags=tags,
    )
    db_session.add(entry)
    await db_session.flush()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def search_memory_mcp_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_switch)`` against the live FastMCP server.

    Builds a ToolAccessor bound to the test ``db_session`` (test_session) so the
    ProductService / ProductMemoryService my adapter constructs read inside the
    rolled-back transaction, and monkeypatches ``_resolve_tenant`` to a mutable
    closure so a single client can switch identity to prove no cross-tenant leak.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    tenant_switch = _TenantSwitch(tenant_key)
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


async def test_search_memory_matching_query_returns_tenant_scoped_headlines(search_memory_mcp_client, db_session):
    new_client, switch = search_memory_mcp_client
    product_id, project_id = await _seed_active_product(db_session, switch.value)
    await _seed_memory_entry(
        db_session,
        switch.value,
        product_id,
        project_id,
        1,
        summary="Implemented the quantumwidget caching layer for fast reads.",
        key_outcomes=["quantumwidget cache shipped"],
        tags=["backend", "perf"],
    )
    await _seed_memory_entry(
        db_session,
        switch.value,
        product_id,
        project_id,
        2,
        summary="Unrelated work on the billing reconciliation job.",
        key_outcomes=["billing fixed"],
        tags=["backend"],
    )
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool("search_memory", {"query": "quantumwidget"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["count"] == 1
    assert payload["product_id"] == product_id
    hit = payload["results"][0]
    assert hit["sequence"] == 1
    assert "quantumwidget" in hit["summary"].lower()
    assert hit["score"] > 0
    assert "backend" in hit["tags"]
    # The non-matching billing entry must be absent.
    assert all("billing" not in r["summary"].lower() for r in payload["results"])


async def test_search_memory_tag_filter_narrows_results(search_memory_mcp_client, db_session):
    new_client, switch = search_memory_mcp_client
    product_id, project_id = await _seed_active_product(db_session, switch.value)
    # Both summaries match the keyword; only one carries the 'security' tag.
    await _seed_memory_entry(
        db_session,
        switch.value,
        product_id,
        project_id,
        1,
        summary="quantumwidget hardening pass",
        key_outcomes=[],
        tags=["backend", "security"],
    )
    await _seed_memory_entry(
        db_session,
        switch.value,
        product_id,
        project_id,
        2,
        summary="quantumwidget refactor",
        key_outcomes=[],
        tags=["backend", "refactor"],
    )
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool("search_memory", {"query": "quantumwidget", "tag": "security"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["count"] == 1
    assert payload["results"][0]["sequence"] == 1
    assert "security" in payload["results"][0]["tags"]


async def test_search_memory_empty_query_returns_clean_empty(search_memory_mcp_client, db_session):
    new_client, switch = search_memory_mcp_client
    product_id, project_id = await _seed_active_product(db_session, switch.value)
    await _seed_memory_entry(
        db_session,
        switch.value,
        product_id,
        project_id,
        1,
        summary="something",
        key_outcomes=[],
        tags=["backend"],
    )
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool("search_memory", {"query": ""})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["count"] == 0
    assert payload["results"] == []


async def test_search_memory_no_match_returns_clean_empty(search_memory_mcp_client, db_session):
    new_client, switch = search_memory_mcp_client
    product_id, project_id = await _seed_active_product(db_session, switch.value)
    await _seed_memory_entry(
        db_session,
        switch.value,
        product_id,
        project_id,
        1,
        summary="the cache layer was rewritten",
        key_outcomes=[],
        tags=["backend"],
    )
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool("search_memory", {"query": "zzznevermatchesxyz"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["count"] == 0
    assert payload["results"] == []


async def test_search_memory_over_length_query_is_422(search_memory_mcp_client, db_session):
    new_client, switch = search_memory_mcp_client
    await _seed_active_product(db_session, switch.value)
    await db_session.commit()

    too_long = "x" * (MCP_SHORT_TEXT_MAX + 1)
    async with new_client() as session:
        result = await session.call_tool("search_memory", {"query": too_long})

    # Over-length is rejected at the FastMCP arg-validation boundary (a 422-class
    # ToolError), never a 500 and never an unvalidated value reaching the DB.
    assert result.is_error is True
    text = _error_text(result).lower()
    assert "query" in text or "length" in text or "2000" in text


async def test_search_memory_no_cross_tenant_leak(search_memory_mcp_client, db_session):
    """Tenant B searching the SAME keyword never sees tenant A's memory entry."""
    new_client, switch = search_memory_mcp_client

    tenant_a = switch.value
    product_a, project_a = await _seed_active_product(db_session, tenant_a)
    await _seed_memory_entry(
        db_session,
        tenant_a,
        product_a,
        project_a,
        1,
        summary="tenant A secret quantumwidget work",
        key_outcomes=[],
        tags=["backend"],
    )

    tenant_b = TenantManager.generate_tenant_key()
    await _seed_active_product(db_session, tenant_b)
    await db_session.commit()

    switch.value = tenant_b
    async with new_client() as session:
        result = await session.call_tool("search_memory", {"query": "quantumwidget"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["count"] == 0, "tenant B must not see tenant A's memory entry"


async def test_search_memory_no_active_product_surfaces_error(search_memory_mcp_client, db_session):
    """No active product surfaces a ValidationError (→ isError), same contract as
    list_projects — proves tenant context propagates through the wrapper."""
    new_client, _switch = search_memory_mcp_client
    # Deliberately seed NOTHING for this fresh tenant (no active product).
    async with new_client() as session:
        result = await session.call_tool("search_memory", {"query": "anything"})

    assert result.is_error is True
    assert "active product" in _error_text(result).lower()
