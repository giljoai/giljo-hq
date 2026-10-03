# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    with tenant_session_context(db_session, tenant_key):
        res = await db_session.execute(
            select(func.count()).select_from(RoadmapItem).where(RoadmapItem.tenant_key == tenant_key)
        )
    return res.scalar_one()




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
    assert row["title"]
    assert "id" in row


async def test_get_roadmap_no_roadmap_yet_returns_empty(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert read["roadmap"] is None
    assert read["items"] == []
    assert read["product_id"] == seed["product_id"]




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
    seed = await _seed(db_session)
    ws = AsyncMock()
    svc = RoadmapService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
        websocket_manager=ws,
    )

    await svc.get_roadmap(tenant_key=seed["tenant_key"])

    ws.broadcast_to_tenant.assert_not_awaited()


def _dead_socket_manager(tenant_key: str):
    from unittest.mock import AsyncMock as _AsyncMock
    from unittest.mock import MagicMock as _MagicMock

    from fastapi import WebSocketDisconnect

    from api.websocket import WebSocketManager

    manager = WebSocketManager()
    socket = _MagicMock()
    socket.send_text = _AsyncMock(side_effect=WebSocketDisconnect(code=1006))
    manager.active_connections["dead-client"] = socket
    manager.tenant_connections[tenant_key] = {"dead-client"}
    return manager


async def test_get_roadmap_agent_active_broadcast_failure_never_blocks_read(db_manager, db_session):
    seed = await _seed(db_session)
    ws = _dead_socket_manager(seed["tenant_key"])
    svc = RoadmapService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
        websocket_manager=ws,
    )

    read = await svc.get_roadmap(tenant_key=seed["tenant_key"], emit_agent_active=True)
    assert read["product_id"] == seed["product_id"]
    assert "dead-client" not in ws.active_connections, "the dead client was attempted and evicted"




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
    seed = await _seed(db_session)
    second_project = Project(
        id=str(uuid.uuid4()),
        tenant_key=seed["tenant_key"],
        product_id=seed["product_id"],
        name="Second project",
        description="desc",
        mission="mission",
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
    assert by_type["task"]["taxonomy_color"] is None




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




async def test_cross_product_project_id_rejected(db_manager, db_session):
    seed = await _seed(db_session)
    other = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": other["project_id"], "sort_order": 0}],
            tenant_key=seed["tenant_key"],
        )
    assert await _count_items(db_session, seed["tenant_key"]) == 0


async def test_a_sibling_product_item_is_told_it_is_in_another_product_not_that_it_is_missing(db_manager, db_session):
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
    assert await _count_items(db_session, seed["tenant_key"]) == 0


async def test_a_genuinely_unknown_id_is_still_reported_as_nonexistent(db_manager, db_session):
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
    seed = await _seed(db_session)
    other = await _seed(db_session)
    svc = _svc(db_manager, db_session)

    with pytest.raises(ValidationError) as excinfo:
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": other["project_id"], "sort_order": 0}],
            tenant_key=seed["tenant_key"],
        )

    message = str(excinfo.value)
    assert "do not exist" in message, message
    assert "belong to a different product" not in message, message




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

    result = await svc.reorder(updates=[{"id": a_item_id, "sort_order": 99}], tenant_key=b["tenant_key"])
    assert result["items_reordered"] == 0

    a_after = (await svc.get_roadmap(tenant_key=a["tenant_key"]))["items"][0]
    assert a_after["sort_order"] == 0




async def test_get_roadmap_drops_completed_project(db_manager, db_session):
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
    assert await _count_items(db_session, seed["tenant_key"]) == 1


@pytest.mark.parametrize("terminal", [ProjectStatus.CANCELLED, ProjectStatus.TERMINATED])
async def test_get_roadmap_drops_cancelled_and_terminated_projects(db_manager, db_session, terminal):
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
    assert await _count_items(db_session, seed["tenant_key"]) == 1


async def test_get_roadmap_drops_soft_deleted_project(db_manager, db_session):
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




async def test_get_roadmap_reflects_renamed_project_live_not_snapshot(db_manager, db_session):
    from giljo_mcp.models.projects import TaxonomyType

    seed = await _seed(db_session)
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

    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one()
    proj.name = "New name"
    proj.series_number = 13
    await db_session.commit()

    after = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]
    assert after["title"] == "New name"
    assert after["taxonomy_alias"] == "FE-0013"


async def test_repoint_task_item_to_project_keeps_sort_order(db_manager, db_session):
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
    assert row["sort_order"] == 4


async def test_repoint_task_item_when_project_already_on_roadmap_drops_orphan(db_manager, db_session):
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

    assert repointed is False
    read = await svc.get_roadmap(tenant_key=seed["tenant_key"])
    assert len(read["items"]) == 1
    assert read["items"][0]["project_id"] == new_project.id
    assert read["items"][0]["sort_order"] == 5




async def test_remove_item_deletes_own_item(db_manager, db_session):
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
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one_or_none()
    assert proj is not None


async def test_remove_item_unknown_id_is_noop(db_manager, db_session):
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

    assert len((await svc.get_roadmap(tenant_key=a["tenant_key"]))["items"]) == 1


async def test_remove_item_wrong_product_is_noop(db_manager, db_session):
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seed["project_id"], "sort_order": 0}],
        tenant_key=seed["tenant_key"],
    )
    active_item_id = (await svc.get_roadmap(tenant_key=seed["tenant_key"]))["items"][0]["id"]

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

    result = await svc.remove_item(item_id=other_item.id, tenant_key=seed["tenant_key"])
    assert result["removed"] == 0

    still = (await db_session.execute(select(RoadmapItem).where(RoadmapItem.id == other_item.id))).scalar_one_or_none()
    assert still is not None
    ok = await svc.remove_item(item_id=active_item_id, tenant_key=seed["tenant_key"])
    assert ok["removed"] == 1


async def test_remove_item_without_active_product_raises(db_manager, db_session):
    seed = await _seed(db_session, active=False)
    svc = _svc(db_manager, db_session)
    with pytest.raises(ResourceNotFoundError):
        await svc.remove_item(item_id=str(uuid.uuid4()), tenant_key=seed["tenant_key"])




async def test_remove_param_evicts_referenced_item(db_manager, db_session):
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
    assert {row["item_type"] for row in read["items"]} == {"task"}
    proj = (await db_session.execute(select(Project).where(Project.id == seed["project_id"]))).scalar_one_or_none()
    assert proj is not None


async def test_remove_param_removes_task_ref(db_manager, db_session):
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
    seed = await _seed(db_session)
    svc = _svc(db_manager, db_session)
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
    result = await svc.upsert_metadata(
        items=[],
        remove=[{"item_type": "project", "project_id": a["project_id"]}],
        tenant_key=b["tenant_key"],
    )
    assert result["items_removed"] == 0
    assert len((await svc.get_roadmap(tenant_key=a["tenant_key"]))["items"]) == 1


async def test_remove_param_bad_shape_raises_validation(db_manager, db_session):
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
            remove=[{"item_type": "project"}],
            tenant_key=seed["tenant_key"],
        )
