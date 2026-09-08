# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
RoadmapService unit tests (FE-6022a).

Covers the owning-service contract: lazy roadmap creation, UNIQUE product_id
(one roadmap per product), upsert de-duplication on the uq_roadmap_item
constraint, enum/range validation (→ 422-class ValidationError), same-product
ownership enforcement (no cross-product leakage), tenant isolation, and reorder.

Parallel-safe: each test owns its fixture data, uses the rolled-back
``db_session`` (TransactionalTestContext), and shares no module-level state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product, Project, Task
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.roadmaps import Roadmap, RoadmapItem
from giljo_mcp.services.roadmap_service import RoadmapService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


async def _seed(db_session, *, active: bool = True) -> dict:
    """Seed org + product (active) + one project + one task in a fresh tenant."""
    suffix = uuid.uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()

    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid.uuid4()),
        name=f"Product {suffix}",
        description="roadmap test product",
        tenant_key=tenant_key,
        is_active=active,
        # FE-9524: is_default is the read-fallback flag now (is_active is
        # shown/hidden only) -- mirror `active` here so this helper's
        # existing callers keep meaning "the resolvable product" vs "not".
        is_default=active,
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
        # BE-9429: uq_project_taxonomy_active is NULLS NOT DISTINCT, so two
        # untyped projects in one product collide unless the serial differs.
        series_number=next_series_number(),
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

    return {
        "tenant_key": tenant_key,
        "product_id": product.id,
        "project_id": project.id,
        "task_id": task.id,
    }


def _svc(db_manager, db_session) -> RoadmapService:
    return RoadmapService(db_manager=db_manager, tenant_manager=TenantManager(), session=db_session)


async def _count_items(db_session, tenant_key: str) -> int:
    """Count a tenant's roadmap items under an explicit tenant context.

    SEC-9276: some tests (e.g. test_cross_product_project_id_rejected) seed a
    SECOND, different tenant in the same shared db_session after the first, which
    leaves the session's flush-derived tenant context stale relative to this call's
    explicit tenant_key predicate. tenant_session_context re-anchors the read to
    the tenant actually being asked about -- the guard stays live and enforced,
    it is simply told which tenant this particular query is scoped to.
    """
    with tenant_session_context(db_session, tenant_key):
        res = await db_session.execute(
            select(func.count()).select_from(RoadmapItem).where(RoadmapItem.tenant_key == tenant_key)
        )
    return res.scalar_one()


# ---------------------------------------------------------------------------
# Lazy creation + read
# ---------------------------------------------------------------------------


async def test_first_write_lazily_creates_roadmap_and_item(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)

    result = await svc.upsert_metadata(
        items=[
            {
                "item_type": "project",
                "project_id": seed["project_id"],
                "sort_order": 0,
                "risk": "low",
                "complexity": "heavy",
            }
        ],
        summary="foundations first",
        tenant_key=seed["tenant_key"],
    )
    assert result["items_upserted"] == 1
    assert result["roadmap_id"]

    # Exactly one roadmap exists for the product (UNIQUE product_id).
    roadmaps = (
        (await db_session.execute(select(Roadmap).where(Roadmap.product_id == seed["product_id"]))).scalars().all()
    )
    assert len(roadmaps) == 1

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read["roadmap"]["summary"] == "foundations first"
    assert len(read["items"]) == 1
    row = read["items"][0]
    assert row["item_type"] == "project"
    assert row["project_id"] == seed["project_id"]
    assert row["risk"] == "low"
    assert row["complexity"] == "heavy"
    assert row["title"]  # project.name normalized to title
    assert "id" in row  # roadmap_item id exposed for reorder


async def test_get_roadmap_no_roadmap_yet_returns_empty(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read["roadmap"] is None
    assert read["items"] == []
    assert read["product_id"] == seed["product_id"]


# ---------------------------------------------------------------------------
# FE-6240: agent-active broadcast — the MCP read path raises the Roadmap pane's
# waiting spinner the moment the agent touches the tool; the REST read (user's
# own page load) does not (emit_agent_active defaults False).
# ---------------------------------------------------------------------------


async def test_get_roadmap_emits_agent_active_when_flagged(db_manager, db_session):
    seed = await _seed(db_session)
    ws = AsyncMock()
    svc = RoadmapService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
        websocket_manager=ws,
    )

    await svc.get_roadmap(tenant_key=seed["tenant_key"], emit_agent_active=True)

    ws.broadcast_to_tenant.assert_awaited_once()
    kwargs = ws.broadcast_to_tenant.await_args.kwargs
    assert kwargs["event_type"] == "roadmap:agent_active"
    assert kwargs["tenant_key"] == seed["tenant_key"]
    assert kwargs["data"]["product_id"] == seed["product_id"]


async def test_get_roadmap_does_not_emit_agent_active_by_default(db_manager, db_session):
    """The REST read path (the user's own page load) must never trip the spinner."""
    seed = await _seed(db_session)
    ws = AsyncMock()
    svc = RoadmapService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
        websocket_manager=ws,
    )

    await svc.get_roadmap(tenant_key=seed["tenant_key"])  # emit_agent_active defaults False

    ws.broadcast_to_tenant.assert_not_awaited()


async def test_get_roadmap_agent_active_broadcast_failure_never_blocks_read(db_manager, db_session):
    """A WS broadcast failure is best-effort: logged, never raised into the read."""
    seed = await _seed(db_session)
    ws = AsyncMock()
    ws.broadcast_to_tenant.side_effect = RuntimeError("ws down")
    svc = RoadmapService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
        websocket_manager=ws,
    )

    # Must still return the (empty) roadmap payload despite the broadcast raising.
    read = await svc.get_roadmap(tenant_key=seed["tenant_key"], emit_agent_active=True)
    assert read["product_id"] == seed["product_id"]
    ws.broadcast_to_tenant.assert_awaited_once()


# ---------------------------------------------------------------------------
# Upsert de-duplication (UNIQUE NULLS NOT DISTINCT)
# ---------------------------------------------------------------------------


async def test_upsert_same_item_twice_dedups_and_updates_sort_order(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 1}],
        tenant_key=seed["tenant_key"],
    )
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 7}],
        tenant_key=seed["tenant_key"],
    )

    assert await _count_items(db_session, seed["tenant_key"]) == 1
    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert len(read["items"]) == 1
    assert read["items"][0]["sort_order"] == 7


async def test_task_and_project_with_same_sort_order_coexist(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[
            {"item_type": "project", "project_id": seed["project_id"], "sort_order": 0},
            {"item_type": "task", "task_id": seed["task_id"], "sort_order": 0},
        ],
        tenant_key=seed["tenant_key"],
    )
    assert await _count_items(db_session, seed["tenant_key"]) == 2


async def test_get_roadmap_items_sorted_by_sort_order(db_manager, db_session):
    """The GET join returns items in ascending sort_order order (FE-6022b binds to
    this ranked ordering). Upsert scrambled priorities, assert the read is sorted."""
    seed = await _seed(db_session)
    # A second project so we have 3 distinct items with scrambled priorities.
    second_project = Project(
        id=str(uuid.uuid4()),
        tenant_key=seed["tenant_key"],
        product_id=seed["product_id"],
        name="Second project",
        description="desc",
        mission="mission",
        # BE-9429: shares a product with the seeded project, so it needs its own
        # serial under the NULLS NOT DISTINCT index.
        series_number=next_series_number(),
    )
    db_session.add(second_project)
    await db_session.commit()

    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[
            {"item_type": "project", "project_id": seed["project_id"], "sort_order": 5},
            {"item_type": "task", "task_id": seed["task_id"], "sort_order": 1},
            {"item_type": "project", "project_id": second_project.id, "sort_order": 3},
        ],
        tenant_key=seed["tenant_key"],
    )

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert [row["sort_order"] for row in read["items"]] == [1, 3, 5]


# ---------------------------------------------------------------------------
# Blocked dependency flag + taxonomy color (FE-6022d)
# ---------------------------------------------------------------------------


async def test_blocked_flag_persists_and_serializes(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[
            {
                "item_type": "project",
                "project_id": seed["project_id"],
                "sort_order": 0,
                "blocked": True,
                "blocked_reason": "needs the auth gate from BE-6077 first",
            }
        ],
        tenant_key=seed["tenant_key"],
    )
    row = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]
    assert row["blocked"] is True
    assert row["blocked_reason"] == "needs the auth gate from BE-6077 first"


async def test_blocked_defaults_false_when_omitted(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "task", "task_id": seed["task_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    row = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]
    assert row["blocked"] is False
    assert row["blocked_reason"] is None


async def test_unblocked_item_drops_reason(db_manager, db_session):
    """An item flagged not-blocked never carries a stale 'blocked by…' reason."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[
            {
                "item_type": "project",
                "project_id": seed["project_id"],
                "sort_order": 0,
                "blocked": False,
                "blocked_reason": "this should be discarded",
            }
        ],
        tenant_key=seed["tenant_key"],
    )
    row = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]
    assert row["blocked"] is False
    assert row["blocked_reason"] is None


async def test_reupsert_can_clear_blocked(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[
            {
                "item_type": "project",
                "project_id": seed["project_id"],
                "sort_order": 0,
                "blocked": True,
                "blocked_reason": "waiting on X",
            }
        ],
        tenant_key=seed["tenant_key"],
    )
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0, "blocked": False}],
        tenant_key=seed["tenant_key"],
    )
    row = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]
    assert row["blocked"] is False
    assert row["blocked_reason"] is None


async def test_blocked_non_bool_raises_validation(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0, "blocked": "yes"}],
            tenant_key=seed["tenant_key"],
        )


async def test_blocked_reason_too_long_raises_validation(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[
                {
                    "item_type": "project",
                    "project_id": seed["project_id"],
                    "sort_order": 0,
                    "blocked": True,
                    "blocked_reason": "x" * 501,
                }
            ],
            tenant_key=seed["tenant_key"],
        )


async def test_get_roadmap_surfaces_taxonomy_color(db_manager, db_session):
    """The alias chip color follows the item's TaxonomyType.color (matches the
    project/task list serial badges); None when the item has no type."""
    from giljo_mcp.models.projects import TaxonomyType

    seed = await _seed(db_session)
    ttype = TaxonomyType(
        id=str(uuid.uuid4()),
        tenant_key=seed["tenant_key"],
        abbreviation="BE",
        label="Backend",
        color="#6DB3E4",
    )
    db_session.add(ttype)
    await db_session.flush()
    # Attach the type to the seeded project.
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one()
    proj.project_type_id = ttype.id
    await db_session.commit()

    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[
            {"item_type": "project", "project_id": seed["project_id"], "sort_order": 0},
            {"item_type": "task", "task_id": seed["task_id"], "sort_order": 1},
        ],
        tenant_key=seed["tenant_key"],
    )
    items = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"]
    by_type = {row["item_type"]: row for row in items}
    assert by_type["project"]["taxonomy_color"] == "#6DB3E4"
    assert by_type["task"]["taxonomy_color"] is None  # task has no type assigned


# ---------------------------------------------------------------------------
# Validation (→ 422-class ValidationError, never a DB 500)
# ---------------------------------------------------------------------------


async def test_bad_item_type_raises_validation(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[{"item_type": "epic", "project_id": seed["project_id"], "sort_order": 0}],
            tenant_key=seed["tenant_key"],
        )


async def test_bad_risk_raises_validation(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0, "risk": "extreme"}],
            tenant_key=seed["tenant_key"],
        )


async def test_bad_complexity_raises_validation(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[{"item_type": "task", "task_id": seed["task_id"], "sort_order": 0, "complexity": "gigantic"}],
            tenant_key=seed["tenant_key"],
        )


async def test_sort_order_out_of_range_raises_validation(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 10_000_000}],
            tenant_key=seed["tenant_key"],
        )


async def test_project_item_missing_id_raises_validation(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[{"item_type": "project", "sort_order": 0}],
            tenant_key=seed["tenant_key"],
        )


# ---------------------------------------------------------------------------
# Same-product ownership (no cross-product leakage)
# ---------------------------------------------------------------------------


async def test_cross_product_project_id_rejected(db_manager, db_session):
    """A project_id that does not belong to the active product is rejected."""
    seed = await _seed(db_session)
    other = await _seed(db_session)  # different tenant + product entirely
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": other["project_id"], "sort_order": 0}],
            tenant_key=seed["tenant_key"],
        )
    assert await _count_items(db_session, seed["tenant_key"]) == 0


async def test_a_sibling_product_item_is_told_it_is_in_another_product_not_that_it_is_missing(db_manager, db_session):
    """BE-9420: the refusal has to be TRUE, not just loud.

    Both rejection reasons used to render as "not found in the active product".
    After a product flip -- an ordinary action -- the common case is an id that
    exists perfectly well one product over, and telling that user their project
    was "not found" is a false statement, not merely an unhelpful one. That is
    what made a correct boundary read as a bug.

    The existing cross-product test seeds a whole other TENANT, so it cannot
    exercise this branch: a foreign-tenant id is deliberately reported as
    nonexistent. This one keeps both products inside one tenant.
    """
    seed = await _seed(db_session)
    sibling_product = Product(
        id=str(uuid.uuid4()),
        name="Sibling Product",
        description="same tenant, different product",
        tenant_key=seed["tenant_key"],
        is_active=False,
    )
    db_session.add(sibling_product)
    await db_session.flush()
    # No next_series_number() here, deliberately, even though BE-9429 made it this
    # file's idiom: that counter exists because rows sharing a (tenant, product)
    # slot collide under the now-strict uq_project_taxonomy_active. This project
    # gets a product of its very own, minted per test run, so its slot cannot be
    # shared and a NULL serial cannot collide with anything.
    sibling_project = Project(
        id=str(uuid.uuid4()),
        tenant_key=seed["tenant_key"],
        product_id=sibling_product.id,
        name="Sibling Project",
        description="desc",
        mission="mission",
    )
    db_session.add(sibling_project)
    await db_session.commit()

    svc = _svc(db_manager, db_session)
    # BE-9523b: this tenant now owns two products, so an omitted product_id would
    # hit the new ambiguity gate before ever reaching the item-ownership check this
    # test is actually about. Name the active product explicitly -- it is the same
    # product the omitted-id path used to resolve to, and the object under test is
    # downstream of resolution (the sibling-item message), not resolution itself.
    with pytest.raises(ValidationError) as excinfo:
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": sibling_project.id, "sort_order": 0}],
            tenant_key=seed["tenant_key"],
            product_id=seed["product_id"],
        )

    message = str(excinfo.value)
    assert "belong to a different product" in message, message
    assert "do not exist" not in message, f"a real project must not be reported as nonexistent: {message}"
    assert seed["product_id"] in message, f"the refusal must name the active product: {message}"
    # The refusal still refuses -- nothing was written.
    assert await _count_items(db_session, seed["tenant_key"]) == 0


async def test_a_genuinely_unknown_id_is_still_reported_as_nonexistent(db_manager, db_session):
    """The other branch, so the disambiguation is proven to discriminate.

    Without this, the test above would pass against an implementation that simply
    said "belongs to a different product" for everything -- which would be exactly
    as false as the message it replaced, in the other direction.
    """
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)

    with pytest.raises(ValidationError) as excinfo:
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": str(uuid.uuid4()), "sort_order": 0}],
            tenant_key=seed["tenant_key"],
        )

    message = str(excinfo.value)
    assert "do not exist" in message, message
    assert "belong to a different product" not in message, message


async def test_another_tenants_project_is_reported_as_nonexistent(db_manager, db_session):
    """Deliberate: the disambiguation stays inside the tenant.

    Confirming that an id exists somewhere would answer a question the caller is
    not entitled to ask, so a foreign-tenant id gets the nonexistent branch even
    though the row is real. Pinned so a later "helpful" widening of the lookup
    has to argue with a test.
    """
    seed = await _seed(db_session)
    other = await _seed(db_session)  # different tenant entirely
    svc = _svc(db_manager, db_session)

    with pytest.raises(ValidationError) as excinfo:
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": other["project_id"], "sort_order": 0}],
            tenant_key=seed["tenant_key"],
        )

    message = str(excinfo.value)
    assert "do not exist" in message, message
    assert "belong to a different product" not in message, message


# ---------------------------------------------------------------------------
# No active product
# ---------------------------------------------------------------------------


async def test_upsert_without_active_product_raises(db_manager, db_session):
    seed = await _seed(db_session, active=False)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
            tenant_key=seed["tenant_key"],
        )


async def test_get_roadmap_without_active_product_raises(db_manager, db_session):
    seed = await _seed(db_session, active=False)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ResourceNotFoundError):
        await svc.get_roadmap(tenant_key=seed["tenant_key"])


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


async def test_get_roadmap_is_tenant_scoped(db_manager, db_session):
    a = await _seed(db_session)
    b = await _seed(db_session)
    svc = _svc(db_manager, db_session)

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": a["project_id"], "sort_order": 0}],
        tenant_key=a["tenant_key"],
    )
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": b["project_id"], "sort_order": 0}],
        tenant_key=b["tenant_key"],
    )

    read_a = await svc.get_roadmap(tenant_key=a["tenant_key"])
    a_project_ids = {row["project_id"] for row in read_a["items"]}
    assert a["project_id"] in a_project_ids
    assert b["project_id"] not in a_project_ids


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


async def test_reorder_updates_sort_order(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    item_id = read["items"][0]["id"]

    result = await svc.reorder(updates=[{"id": item_id, "sort_order": 42}], tenant_key=seed["tenant_key"])
    assert result["items_reordered"] == 1

    read2 = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read2["items"][0]["sort_order"] == 42


async def test_reorder_cross_tenant_item_is_noop(db_manager, db_session):
    a = await _seed(db_session)
    b = await _seed(db_session)
    svc = _svc(db_manager, db_session)

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": a["project_id"], "sort_order": 0}],
        tenant_key=a["tenant_key"],
    )
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": b["project_id"], "sort_order": 0}],
        tenant_key=b["tenant_key"],
    )
    a_item_id = (await svc.get_roadmap(tenant_key=a["tenant_key"]))["items"][0]["id"]

    # Tenant B tries to reorder tenant A's item -> 0 updated, A unchanged.
    result = await svc.reorder(updates=[{"id": a_item_id, "sort_order": 99}], tenant_key=b["tenant_key"])
    assert result["items_reordered"] == 0

    a_after = (await svc.get_roadmap(tenant_key=a["tenant_key"]))["items"][0]
    assert a_after["sort_order"] == 0


# ---------------------------------------------------------------------------
# 0006 HARD AUTO-DROP: terminal projects/tasks excluded from the active roadmap.
# Deliberately REVERSES the FE-6022c surface-with-badge behavior — a terminal
# item with no actionable state must not pin/lock the plan. `active` stays.
# ---------------------------------------------------------------------------


async def test_get_roadmap_drops_completed_project(db_manager, db_session):
    """0006: a roadmapped project that has since COMPLETED is auto-dropped from
    the active roadmap (reverses the FE-6022c surface-with-badge choice)."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one()
    proj.status = ProjectStatus.COMPLETED
    await db_session.commit()

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read["items"] == []
    # The roadmap_item row itself is untouched — only the READ excludes it (so a
    # later reactivation would surface it again without a re-rank).
    assert await _count_items(db_session, seed["tenant_key"]) == 1


@pytest.mark.parametrize("terminal", [ProjectStatus.CANCELLED, ProjectStatus.TERMINATED])
async def test_get_roadmap_drops_cancelled_and_terminated_projects(db_manager, db_session, terminal):
    """0006: cancelled / terminated projects are auto-dropped too (full
    LIFECYCLE_FINISHED_STATUSES coverage, not just completed)."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one()
    proj.status = terminal
    await db_session.commit()

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read["items"] == []


async def test_get_roadmap_drops_parked_project(db_manager, db_session):
    """IMP-9258: a parked project is dropped from the canned roadmap plan too --
    its own exclusion (NOT LIFECYCLE_FINISHED_STATUSES membership, since parked
    is resumable and stays visible in normal project lists elsewhere)."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one()
    proj.status = ProjectStatus.PARKED
    await db_session.commit()

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read["items"] == []
    # The roadmap_item row itself is untouched -- unparking would surface it
    # again without a re-rank, mirroring the completed-project behavior above.
    assert await _count_items(db_session, seed["tenant_key"]) == 1


async def test_get_roadmap_drops_soft_deleted_project(db_manager, db_session):
    """0006: a soft-deleted project (deleted_at set) is auto-dropped — 'deleted'
    is terminal. (Was SURFACED as status 'deleted' under FE-6022c.)"""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one()
    proj.deleted_at = datetime.now(UTC)
    await db_session.commit()

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read["items"] == []


async def test_get_roadmap_keeps_active_project(db_manager, db_session):
    """0006 two-sided: an ACTIVATED project is NOT terminal — it stays on the
    roadmap (reversible via Deactivate), unlike completed/cancelled/etc."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one()
    proj.status = ProjectStatus.ACTIVE
    await db_session.commit()

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert len(read["items"]) == 1
    assert read["items"][0]["status"] == "active"


async def test_get_roadmap_keeps_inactive_project_and_pending_task(db_manager, db_session):
    """0006 two-sided: the normal actionable states (inactive project, pending
    task) are untouched by the auto-drop filter."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[
            {"item_type": "project", "project_id": seed["project_id"], "sort_order": 0},
            {"item_type": "task", "task_id": seed["task_id"], "sort_order": 1},
        ],
        tenant_key=seed["tenant_key"],
    )
    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert {row["item_type"] for row in read["items"]} == {"project", "task"}


@pytest.mark.parametrize("terminal", ["completed", "cancelled"])
async def test_get_roadmap_drops_terminal_task(db_manager, db_session, terminal):
    """0006 (D1): terminal TASKS (completed/cancelled) auto-drop too, symmetric
    with projects — a finished task must not pin the plan either."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "task", "task_id": seed["task_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    task = (await db_session.execute(select(Task).where(Task.id == seed["task_id"]))).scalar_one()
    task.status = terminal
    await db_session.commit()

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read["items"] == []


async def test_get_roadmap_keeps_in_progress_task(db_manager, db_session):
    """0006 two-sided: an in_progress task is NOT terminal — it stays."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "task", "task_id": seed["task_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    task = (await db_session.execute(select(Task).where(Task.id == seed["task_id"]))).scalar_one()
    task.status = "in_progress"
    await db_session.commit()

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert len(read["items"]) == 1
    assert read["items"][0]["status"] == "in_progress"


# ---------------------------------------------------------------------------
# FE-6022c: convert re-point
# ---------------------------------------------------------------------------


async def test_get_roadmap_reflects_renamed_project_live_not_snapshot(db_manager, db_session):
    """Bug-2 (alias 0005): the read joins project title + taxonomy_alias LIVE on
    every fetch. Renaming a roadmapped project (new name + new series → new alias)
    is reflected on the next get_roadmap — never a stale denormalized snapshot
    captured at upsert time. Guards against any future re-introduction of a
    stored title/alias copy on the roadmap_item."""
    from giljo_mcp.models.projects import TaxonomyType

    seed = await _seed(db_session)
    # Give the project a taxonomy type + series so it has a real alias (FE-0005).
    ttype = TaxonomyType(
        id=str(uuid.uuid4()),
        tenant_key=seed["tenant_key"],
        abbreviation="FE",
        label="Frontend",
        color="#AB47BC",
    )
    db_session.add(ttype)
    await db_session.flush()
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one()
    proj.name = "Old name"
    proj.project_type_id = ttype.id
    proj.series_number = 5
    await db_session.commit()

    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    before = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]
    assert before["title"] == "Old name"
    assert before["taxonomy_alias"] == "FE-0005"

    # Rename: new title + new series number -> new derived alias.
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one()
    proj.name = "New name"
    proj.series_number = 13
    await db_session.commit()

    after = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]
    assert after["title"] == "New name"  # live, not the upsert-time value
    assert after["taxonomy_alias"] == "FE-0013"  # live, not "FE-0005"


async def test_repoint_task_item_to_project_keeps_sort_order(db_manager, db_session):
    """Convert re-point: a task roadmap item flips to its new project IN PLACE,
    preserving sort_order/position (no reorder, no CASCADE removal)."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "task", "task_id": seed["task_id"], "sort_order": 4, "risk": "med"}],
        tenant_key=seed["tenant_key"],
    )
    new_project = Project(
        id=str(uuid.uuid4()),
        tenant_key=seed["tenant_key"],
        product_id=seed["product_id"],
        name="Converted project",
        description="desc",
        mission="",
    )
    db_session.add(new_project)
    await db_session.flush()

    repointed = await svc.repoint_item_task_to_project(
        db_session,
        tenant_key=seed["tenant_key"],
        task_id=seed["task_id"],
        new_project_id=new_project.id,
    )
    assert repointed is True
    await db_session.commit()

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert len(read["items"]) == 1
    row = read["items"][0]
    assert row["item_type"] == "project"
    assert row["project_id"] == new_project.id
    assert row["task_id"] is None
    assert row["sort_order"] == 4  # position preserved across the convert


async def test_repoint_task_item_when_project_already_on_roadmap_drops_orphan(db_manager, db_session):
    """If the new project is ALREADY on the roadmap (uq_roadmap_item conflict),
    re-point drops the orphaned task item instead of creating a duplicate."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    new_project = Project(
        id=str(uuid.uuid4()),
        tenant_key=seed["tenant_key"],
        product_id=seed["product_id"],
        name="Already roadmapped",
        description="desc",
        mission="",
    )
    db_session.add(new_project)
    await db_session.flush()

    await svc.upsert_metadata(
        items=[
            {"item_type": "task", "task_id": seed["task_id"], "sort_order": 2},
            {"item_type": "project", "project_id": new_project.id, "sort_order": 5},
        ],
        tenant_key=seed["tenant_key"],
    )
    assert await _count_items(db_session, seed["tenant_key"]) == 2

    repointed = await svc.repoint_item_task_to_project(
        db_session,
        tenant_key=seed["tenant_key"],
        task_id=seed["task_id"],
        new_project_id=new_project.id,
    )
    await db_session.commit()

    # Conflict path: the orphaned task item is gone; the pre-existing project item stands.
    assert repointed is False
    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert len(read["items"]) == 1
    assert read["items"][0]["project_id"] == new_project.id
    assert read["items"][0]["sort_order"] == 5


# ---------------------------------------------------------------------------
# FE-6022c-polish: remove_item (tenant + active-product scoped delete)
# ---------------------------------------------------------------------------


async def test_remove_item_deletes_own_item(db_manager, db_session):
    """remove_item deletes the caller's own roadmap item (removed=1) and leaves
    the underlying project untouched."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    item_id = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]["id"]

    result = await svc.remove_item(item_id=item_id, tenant_key=seed["tenant_key"])
    assert result["removed"] == 1

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read["items"] == []
    # The roadmap_item is gone but the project itself still exists.
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one_or_none()
    assert proj is not None


async def test_remove_item_unknown_id_is_noop(db_manager, db_session):
    """An unknown item_id is a clean no-op (removed=0), never a 500."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    result = await svc.remove_item(item_id=str(uuid.uuid4()), tenant_key=seed["tenant_key"])
    assert result["removed"] == 0
    assert await _count_items(db_session, seed["tenant_key"]) == 1


async def test_remove_item_cross_tenant_is_noop(db_manager, db_session):
    """Tenant B cannot delete tenant A's roadmap item: no-op (removed=0), A intact."""
    a = await _seed(db_session)
    b = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": a["project_id"], "sort_order": 0}],
        tenant_key=a["tenant_key"],
    )
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": b["project_id"], "sort_order": 0}],
        tenant_key=b["tenant_key"],
    )
    a_item_id = (await svc.get_roadmap(tenant_key=a["tenant_key"]))["items"][0]["id"]

    result = await svc.remove_item(item_id=a_item_id, tenant_key=b["tenant_key"])
    assert result["removed"] == 0

    # A's item survives the cross-tenant delete attempt.
    assert len((await svc.get_roadmap(tenant_key=a["tenant_key"]))["items"]) == 1


async def test_remove_item_wrong_product_is_noop(db_manager, db_session):
    """An item that belongs to a DIFFERENT (non-active) product of the same tenant
    is not in the active product's roadmap -> no-op (removed=0)."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    active_item_id = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]["id"]

    # A second product (inactive) of the SAME tenant with its own roadmap item.
    other_product = Product(
        id=str(uuid.uuid4()),
        name="Other product",
        description="second product",
        tenant_key=seed["tenant_key"],
        is_active=False,
    )
    db_session.add(other_product)
    await db_session.flush()
    other_project = Project(
        id=str(uuid.uuid4()),
        tenant_key=seed["tenant_key"],
        product_id=other_product.id,
        name="Other project",
        description="desc",
        mission="mission",
    )
    db_session.add(other_project)
    await db_session.flush()
    other_roadmap = Roadmap(id=str(uuid.uuid4()), tenant_key=seed["tenant_key"], product_id=other_product.id)
    db_session.add(other_roadmap)
    await db_session.flush()
    other_item = RoadmapItem(
        id=str(uuid.uuid4()),
        tenant_key=seed["tenant_key"],
        roadmap_id=other_roadmap.id,
        item_type="project",
        project_id=other_project.id,
        sort_order=0,
    )
    db_session.add(other_item)
    await db_session.commit()

    # The active-product remove_item must not reach the OTHER product's item.
    result = await svc.remove_item(item_id=other_item.id, tenant_key=seed["tenant_key"])
    assert result["removed"] == 0

    # The other product's item survives; the active one is removable.
    still = (await db_session.execute(select(RoadmapItem).where(RoadmapItem.id == other_item.id))).scalar_one_or_none()
    assert still is not None
    ok = await svc.remove_item(item_id=active_item_id, tenant_key=seed["tenant_key"])
    assert ok["removed"] == 1


async def test_remove_item_without_active_product_raises(db_manager, db_session):
    """No active product -> ResourceNotFoundError (404), mirroring get/reorder."""
    seed = await _seed(db_session, active=False)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ResourceNotFoundError):
        await svc.remove_item(item_id=str(uuid.uuid4()), tenant_key=seed["tenant_key"])


# ---------------------------------------------------------------------------
# 0006: save_roadmap `remove` param (ref-based, same-call eviction)
# ---------------------------------------------------------------------------


async def test_remove_param_evicts_referenced_item(db_manager, db_session):
    """A {item_type, project_id} ref in `remove` drops that roadmap item in the
    same call; the underlying project is untouched."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[
            {"item_type": "project", "project_id": seed["project_id"], "sort_order": 0},
            {"item_type": "task", "task_id": seed["task_id"], "sort_order": 1},
        ],
        tenant_key=seed["tenant_key"],
    )
    result = await svc.upsert_metadata(
        items=[],
        remove=[{"item_type": "project", "project_id": seed["project_id"]}],
        tenant_key=seed["tenant_key"],
    )
    assert result["items_removed"] == 1
    assert result["items_upserted"] == 0

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    # Only the task remains; the project item is gone but the project survives.
    assert {row["item_type"] for row in read["items"]} == {"task"}
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one_or_none()
    assert proj is not None


async def test_remove_param_removes_task_ref(db_manager, db_session):
    """A task ref in `remove` evicts the task item."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "task", "task_id": seed["task_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    result = await svc.upsert_metadata(
        items=[],
        remove=[{"item_type": "task", "task_id": seed["task_id"]}],
        tenant_key=seed["tenant_key"],
    )
    assert result["items_removed"] == 1
    assert await _count_items(db_session, seed["tenant_key"]) == 0


async def test_remove_param_unknown_ref_is_noop(db_manager, db_session):
    """A ref not on the roadmap is a clean no-op (items_removed=0), never an error."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    result = await svc.upsert_metadata(
        items=[],
        remove=[{"item_type": "project", "project_id": str(uuid.uuid4())}],
        tenant_key=seed["tenant_key"],
    )
    assert result["items_removed"] == 0
    assert await _count_items(db_session, seed["tenant_key"]) == 1


async def test_remove_param_upsert_and_remove_in_one_call(db_manager, db_session):
    """A single call can upsert one item and remove another."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    # Seed the project item; the task is not yet on the roadmap.
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    result = await svc.upsert_metadata(
        items=[{"item_type": "task", "task_id": seed["task_id"], "sort_order": 1}],
        remove=[{"item_type": "project", "project_id": seed["project_id"]}],
        tenant_key=seed["tenant_key"],
    )
    assert result["items_upserted"] == 1
    assert result["items_removed"] == 1
    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert {row["item_type"] for row in read["items"]} == {"task"}


async def test_remove_param_same_item_in_both_lists_ends_removed(db_manager, db_session):
    """Contradictory same-item (in items AND remove) -> removal runs last, item
    ends removed (predictable last-write-wins)."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    result = await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        remove=[{"item_type": "project", "project_id": seed["project_id"]}],
        tenant_key=seed["tenant_key"],
    )
    assert result["items_removed"] == 1
    assert await _count_items(db_session, seed["tenant_key"]) == 0


async def test_remove_param_is_tenant_and_product_scoped(db_manager, db_session):
    """Tenant B's remove ref for tenant A's project cannot reach A's roadmap
    item (B's active product != A's project) — A's item survives."""
    a = await _seed(db_session)
    b = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": a["project_id"], "sort_order": 0}],
        tenant_key=a["tenant_key"],
    )
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": b["project_id"], "sort_order": 0}],
        tenant_key=b["tenant_key"],
    )
    # B references A's project id in a remove — scoped to B's roadmap, matches nothing.
    result = await svc.upsert_metadata(
        items=[],
        remove=[{"item_type": "project", "project_id": a["project_id"]}],
        tenant_key=b["tenant_key"],
    )
    assert result["items_removed"] == 0
    assert len((await svc.get_roadmap(tenant_key=a["tenant_key"]))["items"]) == 1


async def test_remove_param_bad_shape_raises_validation(db_manager, db_session):
    """A remove ref with a bad item_type / missing id -> 422-class ValidationError."""
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[],
            remove=[{"item_type": "epic", "project_id": seed["project_id"]}],
            tenant_key=seed["tenant_key"],
        )
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[],
            remove=[{"item_type": "project"}],  # missing project_id
            tenant_key=seed["tenant_key"],
        )
