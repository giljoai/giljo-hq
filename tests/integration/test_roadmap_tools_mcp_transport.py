# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio

from giljo_mcp.models import Product, Project, Task
from giljo_mcp.models.organizations import Organization
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


async def _seed_active_product(db_session, tenant_key: str) -> dict:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid.uuid4()),
        name=f"Product {suffix}",
        description="roadmap transport test product",
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
    task = Task(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        title=f"Task {suffix}",
        description="desc",
        status="pending",
        priority="medium",
    )
    db_session.add_all([project, task])
    await db_session.commit()
    return {"product_id": product.id, "project_id": project.id, "task_id": task.id}


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def roadmap_mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.roadmap_service import RoadmapService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._roadmap_service = RoadmapService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        session=db_session,
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


async def test_update_roadmap_metadata_happy_path(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_active_product(db_session, switch.value)

    async with new_client() as session:
        result = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {
                        "item_type": "project",
                        "project_id": seed["project_id"],
                        "sort_order": 0,
                        "risk": "med",
                        "complexity": "light",
                    }
                ],
                "summary": "ship foundations first",
            },
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["items_upserted"] == 1
    assert payload["product_id"] == seed["product_id"]
    assert payload["roadmap_id"]


async def test_update_roadmap_metadata_bad_enum_surfaces_error(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_active_product(db_session, switch.value)

    async with new_client() as session:
        result = await session.call_tool(
            "save_roadmap",
            {"items": [{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0, "risk": "nuclear"}]},
        )

    assert result.is_error is True
    text = _error_text(result).lower()
    assert "risk" in text or "nuclear" in text


async def test_update_roadmap_metadata_cross_tenant_project_rejected(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client

    tenant_a = switch.value
    seed_a = await _seed_active_product(db_session, tenant_a)

    tenant_b = TenantManager.generate_tenant_key()
    await _seed_active_product(db_session, tenant_b)

    switch.value = tenant_b
    async with new_client() as session:
        result = await session.call_tool(
            "save_roadmap",
            {"items": [{"item_type": "project", "project_id": seed_a["project_id"], "sort_order": 0}]},
        )

    assert result.is_error is True, "cross-product project_id must be rejected, not silently accepted"


async def test_get_roadmap_reads_back_through_transport(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_active_product(db_session, switch.value)

    async with new_client() as session:
        await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {
                        "item_type": "project",
                        "project_id": seed["project_id"],
                        "sort_order": 0,
                        "risk": "low",
                        "complexity": "heavy",
                    }
                ],
                "summary": "foundations first",
            },
        )
        result = await session.call_tool("get_roadmap", {})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["product_id"] == seed["product_id"]
    assert payload["roadmap"] is not None
    assert payload["roadmap"]["summary"] == "foundations first"
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["item_type"] == "project"
    assert item["project_id"] == seed["project_id"]
    assert item["risk"] == "low"
    assert item["complexity"] == "heavy"


async def test_update_roadmap_metadata_blocked_and_sort_order_round_trip(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_active_product(db_session, switch.value)

    async with new_client() as session:
        write = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {
                        "item_type": "project",
                        "project_id": seed["project_id"],
                        "sort_order": 7,
                        "blocked": True,
                        "blocked_reason": "waiting on the auth gate in BE-6077",
                    }
                ]
            },
        )
        read = await session.call_tool("get_roadmap", {})

    assert write.is_error is False, _error_text(write)
    item = _payload(read)["items"][0]
    assert item["sort_order"] == 7
    assert item["blocked"] is True
    assert item["blocked_reason"] == "waiting on the auth gate in BE-6077"


async def test_update_roadmap_metadata_bad_blocked_type_surfaces_error(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_active_product(db_session, switch.value)

    async with new_client() as session:
        result = await session.call_tool(
            "save_roadmap",
            {"items": [{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0, "blocked": "yes"}]},
        )

    assert result.is_error is True
    assert "blocked" in _error_text(result).lower()


async def test_update_roadmap_metadata_remove_param_evicts_through_transport(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_active_product(db_session, switch.value)

    async with new_client() as session:
        await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {"item_type": "project", "project_id": seed["project_id"], "sort_order": 0},
                    {"item_type": "task", "task_id": seed["task_id"], "sort_order": 1},
                ]
            },
        )
        result = await session.call_tool(
            "save_roadmap",
            {
                "items": [],
                "remove": [{"item_type": "project", "project_id": seed["project_id"]}],
            },
        )
        read = await session.call_tool("get_roadmap", {})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["items_removed"] == 1
    assert payload["items_upserted"] == 0

    read_payload = _payload(read)
    assert {item["item_type"] for item in read_payload["items"]} == {"task"}


async def test_update_roadmap_metadata_remove_bad_shape_surfaces_error(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_active_product(db_session, switch.value)

    async with new_client() as session:
        result = await session.call_tool(
            "save_roadmap",
            {"items": [], "remove": [{"item_type": "epic", "project_id": seed["project_id"]}]},
        )

    assert result.is_error is True
    text = _error_text(result).lower()
    assert "item_type" in text or "epic" in text


async def test_get_roadmap_no_active_product_surfaces_error(roadmap_mcp_client, db_session):
    new_client, _switch = roadmap_mcp_client
    async with new_client() as session:
        result = await session.call_tool("get_roadmap", {})

    assert result.is_error is True
    assert "active product" in _error_text(result).lower()


async def test_removing_last_item_clears_summary_through_transport(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_active_product(db_session, switch.value)

    async with new_client() as session:
        await session.call_tool(
            "save_roadmap",
            {
                "items": [{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
                "summary": "Ships the foundation project first.",
            },
        )
        write = await session.call_tool("get_roadmap", {})
        assert _payload(write)["roadmap"]["summary"] == "Ships the foundation project first."

        await session.call_tool(
            "save_roadmap",
            {"items": [], "remove": [{"item_type": "project", "project_id": seed["project_id"]}]},
        )
        read = await session.call_tool("get_roadmap", {})

    payload = _payload(read)
    assert payload["items"] == []
    assert payload["roadmap"]["summary"] is None
