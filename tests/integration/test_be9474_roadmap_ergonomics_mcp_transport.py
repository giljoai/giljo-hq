# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9474 -- ``save_roadmap`` ergonomics, exercised at the MCP boundary.

The defect this file pins was found by an agent using the tool, not by a unit test: it
built a 17-row roadmap, ONE row carried a ~580-char ``blocked_reason``, and the
call rejected all seventeen while naming only that first bad row. The agent then
had to resend the whole batch to discover the next problem.

Boundary, not service (house rule + BE-5042): the failure the agent experienced
is the one the FastMCP ``@mcp.tool`` wrapper returns, so the assertions run
through the in-memory MCP transport. Harness + fixtures mirror
``tests/integration/test_roadmap_tools_mcp_transport.py`` exactly.

Edition Scope: CE.
"""

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
    """Seed org + active product + N aliased projects + one aliased task.

    Every project gets a real ``taxonomy_alias`` (BE-0001, BE-0002, ...) via a
    TaxonomyType abbreviation + series_number, because the alias half of this
    suite is meaningless against rows whose alias is NULL.
    """
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
    """``(new_client, tenant_switch)`` against the live FastMCP server.

    Verbatim from ``test_roadmap_tools_mcp_transport.py`` so a red here is a red
    in the tool, not in a fixture this file invented.
    """
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


# ---------------------------------------------------------------------------
# REPRODUCTION -- these hold on BOTH sides of the fix (atomicity is deliberate)
# ---------------------------------------------------------------------------


async def test_one_overlong_blocked_reason_rejects_every_valid_row(roadmap_mcp_client, db_session):
    """The reported failure: three good rows die for one bad field, and NOTHING lands.

    Atomicity is the right behaviour and stays -- a partially-applied re-rank is
    worse than a rejected one. What BE-9474 changes is how much the agent learns
    from the rejection, not whether the batch is atomic.
    """
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
    """Alias resolution must not become a tenant-probe surface (pre-ruling 4).

    An alias that names nothing and an alias that names ANOTHER TENANT's project
    must produce the same refusal, word for word. If they differed, an agent
    could enumerate a neighbouring tenant's roadmap by watching which sentence
    came back -- the reason BE-9469 refused ``before_id``.
    """
    new_client, switch = roadmap_mcp_client
    await _seed_product_with_aliased_rows(db_session, switch.value)

    # The neighbour's aliases start at BE-0050 so they cannot collide with the
    # caller's own BE-0001..BE-0004 -- otherwise "foreign" would resolve locally
    # and the test would prove nothing.
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
    """A UUID-shaped reference takes the pre-BE-9474 path with no lookup at all.

    Asserted through behaviour rather than by counting queries: an unknown UUID
    is refused as a missing id, exactly as before, instead of being re-tried as
    an alias and producing some other sentence.
    """
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
    """The pre-BE-9474 caller -- every row, every field, raw UUIDs -- is unchanged.

    This is the backward-compatibility assertion the whole change is measured
    against: nothing an existing caller sends takes a new path or lands
    differently.
    """
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
    """Refutation probe: the tool is NOT full-replace at the ROW level.

    Saving one row does not drop the rows already on the roadmap, so "move one
    item" never needed a 17-row resend for that reason. The resend tax is real
    but it comes from somewhere else -- see the field-level probe below.
    """
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
    """Refutation probe: the resend tax is FIELD-level, not row-level.

    ``ON CONFLICT DO UPDATE`` writes every metadata column from the incoming
    row, so a row resent to change only ``sort_order`` silently loses its
    ``risk`` / ``complexity`` / ``blocked`` state. That -- not full-replace --
    is what forces an agent to carry every field of every row it touches.
    """
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


# ---------------------------------------------------------------------------
# RED -- these fail on master and are the fix's acceptance assertions
# ---------------------------------------------------------------------------


async def test_every_invalid_row_is_named_in_one_response(roadmap_mcp_client, db_session):
    """RED: three bad rows, and the agent is told about exactly one of them."""
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
    """RED: ranking by ``BE-0001`` / ``IMP-0086`` must land the same rows as the UUIDs."""
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
    """A capability the agent is never told about is a capability it will not use.

    Docstring ``Args:`` never reach FastMCP; only ``Field(description=...)``
    does (BE-9470 fixed exactly that on ``list_projects``). This reads the
    advertised ``inputSchema`` off the transport rather than the source, so a
    description that stops arriving fails here instead of silently costing an
    agent a lookup round trip it did not need.
    """
    new_client, _switch = roadmap_mcp_client

    async with new_client() as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}

    # BE-9554 re-based: the tool is now `save_roadmap` (the old name said "metadata",
    # but it writes the roadmap itself). THIS TEST DID ITS JOB DURING THAT RENAME -- the
    # compat shim declares bare params, so the descriptions stopped arriving on the old
    # name and this went red on CI exactly as its docstring promises. The contract lives
    # on the renamed tool, so the assertions follow it there.
    assert "save_roadmap" in tools
    items_description = tools["save_roadmap"].input_schema["properties"]["items"]["description"]
    # "taxonomy_alias" is the shipped wire vocabulary (list_projects already
    # advertises taxonomy_alias_prefix), and it is also what tells the
    # neutrality guard these serials are the PRODUCT's own handles rather
    # than internal ticket citations leaking into customer-rendered text.
    assert "taxonomy_alias" in items_description, items_description
    assert "BE-0001" in items_description, items_description
    assert "IMP-0086" in items_description, items_description
    assert "EVERY bad row" in items_description, items_description
    # The cap has been on the wire since BE-6052e/BE-8003m; keep it there.
    assert "<=500 chars" in items_description, items_description

    # The compat shim is GONE (BE-9554 final names). While it existed this block
    # asserted it stayed a pointer rather than a second copy of the parameter prose;
    # now the guarantee is simply that the retired name no longer answers, so there
    # is exactly one tool carrying this contract.
    assert "update_roadmap_metadata" not in tools, (
        "the retired name is back on the wire -- the contract above must have exactly "
        "one carrier, which is what stopped two tools advertising the same prose"
    )
