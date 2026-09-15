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
from giljo_mcp.models.projects import TaxonomyType
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


async def _seed_product_with_aliased_rows(
    db_session, tenant_key: str, *, projects: int = 4, series_start: int = 1, task_series: int = 86
) -> dict:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid.uuid4()),
        name=f"Product {suffix}",
        description="BE-9474 ergonomics product",
        tenant_key=tenant_key,
        is_active=True,
    )
    proj_type = TaxonomyType(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        abbreviation="BE",
        label="Backend",
        color="#607D8B",
    )
    task_type = TaxonomyType(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        abbreviation="IMP",
        label="Implementation",
        color="#607D8B",
    )
    db_session.add_all([product, proj_type, task_type])
    await db_session.flush()

    project_rows = []
    for n in range(series_start, series_start + projects):
        project_rows.append(
            Project(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                product_id=product.id,
                name=f"Project {n} {suffix}",
                description="desc",
                mission="mission",
                project_type_id=proj_type.id,
                series_number=n,
            )
        )
    task = Task(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        title=f"Task {suffix}",
        description="desc",
        status="pending",
        priority="medium",
        task_type_id=task_type.id,
        series_number=task_series,
    )
    db_session.add_all([*project_rows, task])
    await db_session.commit()

    return {
        "product_id": product.id,
        "project_ids": [p.id for p in project_rows],
        "project_aliases": [f"BE-{n:04d}" for n in range(series_start, series_start + projects)],
        "task_id": task.id,
        "task_alias": f"IMP-{task_series:04d}",
    }


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




async def test_one_overlong_blocked_reason_rejects_every_valid_row(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    items = [
        {"item_type": "project", "project_id": pid, "sort_order": i} for i, pid in enumerate(seed["project_ids"][:3])
    ]
    items.append(
        {
            "item_type": "project",
            "project_id": seed["project_ids"][3],
            "sort_order": 3,
            "blocked": True,
            "blocked_reason": "x" * 580,
        }
    )

    async with new_client() as session:
        result = await session.call_tool("save_roadmap", {"items": items})
        assert result.is_error is True, _payload(result)

        after = await session.call_tool("get_roadmap", {})

    assert _payload(after)["items"] == [], "the three valid rows must not land -- the batch is atomic"


async def test_unresolvable_and_foreign_aliases_are_refused_identically(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    await _seed_product_with_aliased_rows(db_session, switch.value)

    other_tenant = TenantManager.generate_tenant_key()
    other = await _seed_product_with_aliased_rows(db_session, other_tenant, series_start=50, task_series=51)
    foreign_alias = other["project_aliases"][0]

    async with new_client() as session:
        nonexistent = await session.call_tool(
            "save_roadmap",
            {"items": [{"item_type": "project", "project_id": "BE-9999", "sort_order": 0}]},
        )
        foreign = await session.call_tool(
            "save_roadmap",
            {"items": [{"item_type": "project", "project_id": foreign_alias, "sort_order": 0}]},
        )

    assert nonexistent.is_error is True
    assert foreign.is_error is True
    assert "do not exist in this workspace" in _error_text(nonexistent)
    assert _error_text(foreign).replace(foreign_alias, "BE-9999") == _error_text(nonexistent)


async def test_unknown_uuid_is_never_retried_as_an_alias(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    await _seed_product_with_aliased_rows(db_session, switch.value)
    stranger = str(uuid.uuid4())

    async with new_client() as session:
        result = await session.call_tool(
            "save_roadmap",
            {"items": [{"item_type": "project", "project_id": stranger, "sort_order": 0}]},
        )

    assert result.is_error is True
    assert f"'{stranger}'" in _error_text(result)
    assert "do not exist in this workspace" in _error_text(result)


async def test_the_old_all_rows_all_uuids_call_still_works_untouched(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    items = [
        {
            "item_type": "project",
            "project_id": pid,
            "sort_order": i,
            "risk": "high",
            "complexity": "heavy",
            "blocked": True,
            "blocked_reason": f"blocked on {i}",
        }
        for i, pid in enumerate(seed["project_ids"])
    ]
    items.append({"item_type": "task", "task_id": seed["task_id"], "sort_order": 99, "risk": "low"})

    async with new_client() as session:
        result = await session.call_tool("save_roadmap", {"items": items, "summary": "ship foundations first"})
        assert result.is_error is False, _error_text(result)
        assert _payload(result)["items_upserted"] == 5

        after = await session.call_tool("get_roadmap", {})

    rows = {row.get("project_id") or row.get("task_id"): row for row in _payload(after)["items"]}
    assert set(rows) == {*seed["project_ids"], seed["task_id"]}
    for i, pid in enumerate(seed["project_ids"]):
        assert rows[pid]["sort_order"] == i
        assert rows[pid]["risk"] == "high"
        assert rows[pid]["complexity"] == "heavy"
        assert rows[pid]["blocked"] is True
        assert rows[pid]["blocked_reason"] == f"blocked on {i}"
    assert rows[seed["task_id"]]["sort_order"] == 99
    assert rows[seed["task_id"]]["risk"] == "low"


async def test_upsert_leaves_rows_it_was_not_sent_alone(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        first = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 0},
                    {"item_type": "project", "project_id": seed["project_ids"][1], "sort_order": 1},
                ]
            },
        )
        assert first.is_error is False, _error_text(first)

        second = await session.call_tool(
            "save_roadmap",
            {"items": [{"item_type": "project", "project_id": seed["project_ids"][2], "sort_order": 2}]},
        )
        assert second.is_error is False, _error_text(second)

        after = await session.call_tool("get_roadmap", {})

    landed = {row["project_id"] for row in _payload(after)["items"]}
    assert landed == set(seed["project_ids"][:3])


async def test_resending_one_row_without_its_other_fields_clears_them(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        seeded = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {
                        "item_type": "project",
                        "project_id": seed["project_ids"][0],
                        "sort_order": 0,
                        "risk": "high",
                        "complexity": "heavy",
                        "blocked": True,
                        "blocked_reason": "waiting on the migration",
                    }
                ]
            },
        )
        assert seeded.is_error is False, _error_text(seeded)

        moved = await session.call_tool(
            "save_roadmap",
            {"items": [{"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 5}]},
        )
        assert moved.is_error is False, _error_text(moved)

        after = await session.call_tool("get_roadmap", {})

    (row,) = _payload(after)["items"]
    assert row["sort_order"] == 5
    assert row["risk"] is None
    assert row["complexity"] is None
    assert row["blocked"] is False
    assert row["blocked_reason"] is None




async def test_every_invalid_row_is_named_in_one_response(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    items = [
        {"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 0},
        {"item_type": "project", "project_id": seed["project_ids"][1], "sort_order": 1, "risk": "extreme"},
        {"item_type": "project", "project_id": seed["project_ids"][2], "sort_order": 2},
        {
            "item_type": "project",
            "project_id": seed["project_ids"][3],
            "sort_order": 3,
            "blocked": True,
            "blocked_reason": "y" * 580,
        },
        {"item_type": "task", "task_id": seed["task_id"], "sort_order": "fourth"},
    ]

    async with new_client() as session:
        result = await session.call_tool("save_roadmap", {"items": items})

    assert result.is_error is True
    text = _error_text(result)
    assert "items[1].risk" in text, text
    assert "items[3].blocked_reason" in text, text
    assert "items[4].sort_order" in text, text


async def test_alias_resolves_to_the_same_row_as_its_uuid(roadmap_mcp_client, db_session):
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        result = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {"item_type": "project", "project_id": seed["project_aliases"][0], "sort_order": 0},
                    {"item_type": "task", "task_id": seed["task_alias"], "sort_order": 1},
                ]
            },
        )
        assert result.is_error is False, _error_text(result)

        after = await session.call_tool("get_roadmap", {})

    landed = {(row["item_type"], row.get("project_id") or row.get("task_id")) for row in _payload(after)["items"]}
    assert landed == {("project", seed["project_ids"][0]), ("task", seed["task_id"])}


async def test_the_wire_advertises_aliases_and_the_batched_rejection(roadmap_mcp_client):
    new_client, _switch = roadmap_mcp_client

    async with new_client() as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}

    assert "save_roadmap" in tools
    items_description = tools["save_roadmap"].input_schema["properties"]["items"]["description"]
    assert "taxonomy_alias" in items_description, items_description
    assert "BE-0001" in items_description, items_description
    assert "IMP-0086" in items_description, items_description
    assert "EVERY bad row" in items_description, items_description
    assert "<=500 chars" in items_description, items_description

    assert "update_roadmap_metadata" not in tools, (
        "the retired name is back on the wire -- the contract above must have exactly "
        "one carrier, which is what stopped two tools advertising the same prose"
    )
