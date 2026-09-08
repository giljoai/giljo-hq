# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9502b -- explicit-``product_id`` reads never leak the other product's rows.

Ruling 15: two harness sessions on one tenant, each driving a different
product. ``list_projects``, ``get_roadmap``, ``get_context``, and
``search_memory`` all accept an explicit ``product_id`` (BE-9499a) that is
validated tenant-owned and used WITHOUT falling back to "whichever product is
currently active" -- see each tool's own docstring. This proves that contract
at the MCP transport boundary, with two independent ``ClientSession``s issuing
concurrent calls against two different products under one tenant.

Real committed sessions, not ``TransactionalTestContext``: ``get_context``
(``fetch_context`` -> ``get_product_context`` et al.) opens its own session via
``db_manager`` and does not accept a test-session override, so seed data must
be committed for it to see it at all -- see BE-9502a's own MCP-boundary
fixtures (``test_be9502a_product_switch_mcp_boundary.py``) for the sibling
pattern of wiring ``state.db_manager`` to the real manager. Parallel-safe via
a fresh ``tenant_key`` per test; manual cleanup at teardown.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.roadmaps import Roadmap, RoadmapItem
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


def _payload(result) -> dict:
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool returned no content")


@pytest_asyncio.fixture
async def two_product_client(db_manager, monkeypatch):
    """(client_factory, tenant_key) wired to the REAL db_manager -- every MCP
    tool call in this file sees committed data, no shared test session."""
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor, prior_tm, prior_dbm = state.tool_accessor, state.tenant_manager, state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior_accessor, prior_tm, prior_dbm


async def _seed_product_with_data(db_manager, tenant_key: str, label: str, series_number: int) -> dict:
    """One product + one active project + one 360 memory entry, all uniquely
    named so a leak is unmistakable in the assertions."""
    product_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, name=f"{label} product", tenant_key=tenant_key, is_active=False))
        await session.flush()
        session.add(
            Project(
                id=project_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name=f"{label} project",
                description=f"{label} description",
                mission=f"{label} mission",
                status=ProjectStatus.ACTIVE,
                series_number=series_number,
            )
        )
        roadmap_id = str(uuid.uuid4())
        session.add(Roadmap(id=roadmap_id, tenant_key=tenant_key, product_id=product_id))
        await session.flush()
        session.add(
            RoadmapItem(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                roadmap_id=roadmap_id,
                item_type="project",
                project_id=project_id,
                sort_order=0,
            )
        )
        session.add(
            ProductMemoryEntry(
                id=uuid.uuid4(),
                tenant_key=tenant_key,
                product_id=product_id,
                project_id=project_id,
                sequence=1,
                entry_type="discovery",
                source="write_360_memory_v1",
                timestamp=datetime.now(UTC),
                summary=f"{label} memory needle {uuid.uuid4().hex[:8]}",
            )
        )
        await session.commit()
    return {"product_id": product_id, "project_id": project_id, "label": label}


@pytest_asyncio.fixture
async def two_products(db_manager, two_product_client):
    _client, tenant_key = two_product_client
    product_a = await _seed_product_with_data(db_manager, tenant_key, "ProductA", series_number=1)
    product_b = await _seed_product_with_data(db_manager, tenant_key, "ProductB", series_number=2)

    yield {"tenant_key": tenant_key, "a": product_a, "b": product_b}

    async with db_manager.get_session_async(tenant_key=tenant_key) as cleanup:
        await cleanup.execute(delete(ProductMemoryEntry).where(ProductMemoryEntry.tenant_key == tenant_key))
        await cleanup.execute(delete(RoadmapItem).where(RoadmapItem.tenant_key == tenant_key))
        await cleanup.execute(delete(Roadmap).where(Roadmap.tenant_key == tenant_key))
        await cleanup.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await cleanup.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await cleanup.commit()


@pytest.mark.asyncio
async def test_list_projects_explicit_product_id_never_leaks_the_other_product(two_product_client, two_products):
    client_factory, _tenant = two_product_client

    async def list_for(product_id: str):
        async with client_factory() as client:
            result = await client.call_tool("list_projects", {"product_id": product_id, "include_completed": True})
        assert result.is_error is False, result
        return _payload(result)

    import asyncio

    body_a, body_b = await asyncio.gather(
        list_for(two_products["a"]["product_id"]), list_for(two_products["b"]["product_id"])
    )

    names_a = {p["name"] for p in body_a["projects"]}
    names_b = {p["name"] for p in body_b["projects"]}
    assert "ProductA project" in names_a
    assert "ProductB project" not in names_a
    assert "ProductB project" in names_b
    assert "ProductA project" not in names_b


@pytest.mark.asyncio
async def test_get_roadmap_explicit_product_id_never_leaks_the_other_product(two_product_client, two_products):
    client_factory, _tenant = two_product_client

    async def roadmap_for(product_id: str):
        async with client_factory() as client:
            result = await client.call_tool("get_roadmap", {"product_id": product_id})
        assert result.is_error is False, result
        return _payload(result)

    import asyncio

    body_a, body_b = await asyncio.gather(
        roadmap_for(two_products["a"]["product_id"]), roadmap_for(two_products["b"]["product_id"])
    )

    assert body_a["product_id"] == two_products["a"]["product_id"]
    assert body_b["product_id"] == two_products["b"]["product_id"]
    item_names_a = {i.get("title") for i in body_a["items"]}
    item_names_b = {i.get("title") for i in body_b["items"]}
    assert "ProductA project" in item_names_a
    assert "ProductB project" not in item_names_a
    assert "ProductB project" in item_names_b
    assert "ProductA project" not in item_names_b


@pytest.mark.asyncio
async def test_get_context_explicit_product_id_never_leaks_the_other_product(two_product_client, two_products):
    """``get_context`` never had active-product fallback ambiguity at all --
    ``product_id`` is a required positional param. Still worth pinning: this
    is the one of the four tools without an implicit-fallback code path, so a
    leak here would be a straight scoping bug in ``get_product_context``."""
    client_factory, tenant_key = two_product_client

    async def context_for(product_id: str):
        async with client_factory() as client:
            result = await client.call_tool(
                "get_context",
                {"product_id": product_id, "tenant_key": tenant_key, "categories": ["product_core"]},
            )
        assert result.is_error is False, result
        return _payload(result)

    import asyncio

    body_a, body_b = await asyncio.gather(
        context_for(two_products["a"]["product_id"]), context_for(two_products["b"]["product_id"])
    )

    assert body_a["data"]["product_core"]["product_name"] == "ProductA product"
    assert body_b["data"]["product_core"]["product_name"] == "ProductB product"


@pytest.mark.asyncio
async def test_search_memory_explicit_product_id_never_leaks_the_other_product(two_product_client, two_products):
    client_factory, _tenant = two_product_client

    async def search_for(product_id: str):
        async with client_factory() as client:
            result = await client.call_tool("search_memory", {"query": "memory needle", "product_id": product_id})
        assert result.is_error is False, result
        return _payload(result)

    import asyncio

    body_a, body_b = await asyncio.gather(
        search_for(two_products["a"]["product_id"]), search_for(two_products["b"]["product_id"])
    )

    summaries_a = {r["summary"] for r in body_a["results"]}
    summaries_b = {r["summary"] for r in body_b["results"]}
    assert any(s.startswith("ProductA memory needle") for s in summaries_a)
    assert not any(s.startswith("ProductB memory needle") for s in summaries_a)
    assert any(s.startswith("ProductB memory needle") for s in summaries_b)
    assert not any(s.startswith("ProductA memory needle") for s in summaries_b)
