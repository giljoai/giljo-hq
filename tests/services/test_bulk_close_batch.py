# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import Product, Project
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.models.tasks import Task
from giljo_mcp.services.bulk_close import BULK_EVENT_IDS_MAX, REASON_IN_CHAIN, REASON_NOT_FOUND, REASON_PENDING_HANDOVER
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


def _ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    ws.broadcast_project_update = AsyncMock()
    return ws


def _events(ws: MagicMock) -> list[str]:
    return [c.kwargs["event_type"] for c in ws.broadcast_to_tenant.await_args_list]


@pytest_asyncio.fixture
async def product(db_session, test_tenant_key):
    p = Product(
        id=str(uuid.uuid4()),
        name=f"bulk {uuid.uuid4().hex[:6]}",
        description="d",
        tenant_key=test_tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(p)
    await db_session.commit()
    return p




@pytest_asyncio.fixture
async def project_batch(db_manager, db_session, test_tenant_key):
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(test_tenant_key)
    ws = _ws()
    service = ProjectService(
        db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session, websocket_manager=ws
    )
    return service, ws


async def _projects(db_session, tenant_key, product_id, n, status="inactive") -> list[str]:
    ids = []
    for i in range(1, n + 1):
        p = Project(
            id=str(uuid.uuid4()),
            name=f"bulk project {i}",
            description="d",
            mission="m",
            status=status,
            tenant_key=tenant_key,
            product_id=product_id,
            series_number=next_series_number(),
            execution_mode="claude_code_cli",
        )
        db_session.add(p)
        ids.append(p.id)
    await db_session.commit()
    return ids


async def test_twenty_projects_archive_emits_exactly_one_event(project_batch, db_session, test_tenant_key, product):
    service, ws = project_batch
    ids = await _projects(db_session, test_tenant_key, product.id, 20)

    result = await service.bulk_close_projects("archive", ids, test_tenant_key)

    assert result == {"done": ids, "skipped": [], "failed": []}
    assert _events(ws) == ["projects:bulk_updated"]
    ws.broadcast_project_update.assert_not_awaited()
    data = ws.broadcast_to_tenant.await_args.kwargs["data"]
    assert data["action"] == "archive"
    assert data["count"] == 20
    assert data["ids"] == ids
    assert data["truncated"] is False
    hidden = (await db_session.execute(select(Project.hidden).where(Project.id.in_(ids)))).scalars().all()
    assert hidden == [True] * 20


async def test_unarchive_restores_visibility(project_batch, db_session, test_tenant_key, product):
    service, _ws_unused = project_batch
    ids = await _projects(db_session, test_tenant_key, product.id, 3)
    await service.bulk_close_projects("archive", ids, test_tenant_key)

    result = await service.bulk_close_projects("unarchive", ids, test_tenant_key)

    assert result["done"] == ids
    hidden = (await db_session.execute(select(Project.hidden).where(Project.id.in_(ids)))).scalars().all()
    assert hidden == [False] * 3


async def test_delete_soft_deletes_each_with_one_event(project_batch, db_session, test_tenant_key, product):
    service, ws = project_batch
    ids = await _projects(db_session, test_tenant_key, product.id, 4)

    result = await service.bulk_close_projects("delete", ids, test_tenant_key)

    assert result["done"] == ids
    assert _events(ws) == ["projects:bulk_updated"]
    ws.broadcast_project_update.assert_not_awaited()
    statuses = (await db_session.execute(select(Project.status).where(Project.id.in_(ids)))).scalars().all()
    assert {str(s.value if hasattr(s, "value") else s) for s in statuses} == {"deleted"}


async def test_other_tenants_project_is_not_found_and_untouched(project_batch, db_session, test_tenant_key, product):
    service, _ws_unused = project_batch
    mine = await _projects(db_session, test_tenant_key, product.id, 1)
    other_tenant = TenantManager.generate_tenant_key()
    other_product = Product(
        id=str(uuid.uuid4()), name="other", description="d", tenant_key=other_tenant, is_active=False, product_memory={}
    )
    db_session.add(other_product)
    await db_session.commit()
    theirs = await _projects(db_session, other_tenant, other_product.id, 1)

    result = await service.bulk_close_projects("archive", [mine[0], theirs[0]], test_tenant_key)

    assert result["done"] == mine
    assert result["skipped"] == [{"id": theirs[0], "reason": REASON_NOT_FOUND}]
    still = (await db_session.execute(select(Project.hidden).where(Project.id == theirs[0]))).scalar_one()
    assert still is False


async def test_chain_member_is_skipped_by_archive_and_delete(project_batch, db_session, test_tenant_key, product):
    service, _ws_unused = project_batch
    solo, member = await _projects(db_session, test_tenant_key, product.id, 2)
    db_session.add(
        SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=test_tenant_key,
            project_ids=[member],
            resolved_order=[member],
            execution_mode="subagent",
            status="running",
            project_statuses={},
        )
    )
    await db_session.commit()

    archived = await service.bulk_close_projects("archive", [solo, member], test_tenant_key)
    deleted = await service.bulk_close_projects("delete", [member], test_tenant_key)

    assert archived["done"] == [solo]
    assert archived["skipped"] == [{"id": member, "reason": REASON_IN_CHAIN}]
    assert deleted["done"] == []
    assert deleted["skipped"] == [{"id": member, "reason": REASON_IN_CHAIN}]
    assert (await db_session.execute(select(Project.hidden).where(Project.id == member))).scalar_one() is False


async def test_nothing_done_sends_no_event(project_batch, test_tenant_key):
    service, ws = project_batch

    result = await service.bulk_close_projects("archive", [str(uuid.uuid4())], test_tenant_key)

    assert result["done"] == []
    ws.broadcast_to_tenant.assert_not_awaited()


async def test_event_ids_are_capped_but_count_is_exact(project_batch, db_session, test_tenant_key, product):
    service, ws = project_batch
    ids = await _projects(db_session, test_tenant_key, product.id, BULK_EVENT_IDS_MAX + 5)

    await service.bulk_close_projects("archive", ids, test_tenant_key)

    data = ws.broadcast_to_tenant.await_args.kwargs["data"]
    assert data["count"] == BULK_EVENT_IDS_MAX + 5
    assert len(data["ids"]) == BULK_EVENT_IDS_MAX
    assert data["truncated"] is True




@pytest_asyncio.fixture
async def task_batch(db_manager, db_session, test_tenant_key):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    ws = _ws()
    service = TaskService(
        db_manager=db_manager, tenant_manager=tenant_manager, session=db_session, websocket_manager=ws
    )
    return service, ws


async def _tasks(db_session, tenant_key, product_id, creator_id, n, **extra) -> list[str]:
    ids = []
    for i in range(n):
        t = Task(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            product_id=product_id,
            title=f"bulk task {i}",
            description="d",
            status=extra.get("status", "pending"),
            priority="medium",
            created_by_user_id=creator_id,
            task_type_id=extra.get("task_type_id"),
        )
        db_session.add(t)
        ids.append(t.id)
    await db_session.commit()
    return ids


async def test_twenty_tasks_archive_emits_exactly_one_event(
    task_batch, db_session, test_tenant_key, product, test_user
):
    service, ws = task_batch
    ids = await _tasks(db_session, test_tenant_key, product.id, test_user.id, 20)

    result = await service.bulk_close_tasks("archive", ids, str(test_user.id))

    assert result == {"done": ids, "skipped": [], "failed": []}
    assert _events(ws) == ["tasks:bulk_updated"]
    data = ws.broadcast_to_tenant.await_args.kwargs["data"]
    assert (data["action"], data["count"], data["ids"]) == ("archive", 20, ids)
    hidden = (await db_session.execute(select(Task.hidden).where(Task.id.in_(ids)))).scalars().all()
    assert hidden == [True] * 20


async def test_tasks_unarchive_then_delete(task_batch, db_session, test_tenant_key, product, test_user):
    service, ws = task_batch
    ids = await _tasks(db_session, test_tenant_key, product.id, test_user.id, 3)
    await service.bulk_close_tasks("archive", ids, str(test_user.id))

    await service.bulk_close_tasks("unarchive", ids, str(test_user.id))
    hidden = (await db_session.execute(select(Task.hidden).where(Task.id.in_(ids)))).scalars().all()
    assert hidden == [False] * 3

    ws.broadcast_to_tenant.reset_mock()
    result = await service.bulk_close_tasks("delete", ids, str(test_user.id))

    assert result["done"] == ids
    assert _events(ws) == ["tasks:bulk_updated"]
    deleted = (await db_session.execute(select(Task.deleted_at).where(Task.id.in_(ids)))).scalars().all()
    assert all(d is not None for d in deleted)


async def test_other_tenants_task_is_not_found_and_untouched(
    task_batch, db_session, test_tenant_key, product, test_user
):
    service, _ws_unused = task_batch
    mine = await _tasks(db_session, test_tenant_key, product.id, test_user.id, 1)
    theirs = await _tasks(db_session, TenantManager.generate_tenant_key(), product.id, None, 1)

    result = await service.bulk_close_tasks("delete", [mine[0], theirs[0]], str(test_user.id))

    assert result["done"] == mine
    assert result["skipped"] == [{"id": theirs[0], "reason": REASON_NOT_FOUND}]
    assert (await db_session.execute(select(Task.deleted_at).where(Task.id == theirs[0]))).scalar_one() is None


async def test_task_made_by_someone_else_is_skipped_for_a_non_admin(
    task_batch, db_session, test_tenant_key, product, test_user
):
    service, _ws_unused = task_batch
    foreign = await _tasks(db_session, test_tenant_key, product.id, None, 1)

    result = await service.bulk_close_tasks("archive", foreign, str(test_user.id))

    assert result["done"] == []
    assert len(result["skipped"]) == 1
    assert (await db_session.execute(select(Task.hidden).where(Task.id == foreign[0]))).scalar_one() is False


async def test_pending_handover_is_not_archived_but_a_read_one_is(
    task_batch, db_session, test_tenant_key, product, test_user
):
    service, _ws_unused = task_batch
    hnd = TaxonomyType(id=str(uuid.uuid4()), tenant_key=test_tenant_key, abbreviation="HND", label="Handover")
    db_session.add(hnd)
    await db_session.commit()
    pending = await _tasks(db_session, test_tenant_key, product.id, test_user.id, 1, task_type_id=hnd.id)
    read = await _tasks(
        db_session, test_tenant_key, product.id, test_user.id, 1, task_type_id=hnd.id, status="in_progress"
    )

    result = await service.bulk_close_tasks("archive", [pending[0], read[0]], str(test_user.id))

    assert result["done"] == read
    assert result["skipped"] == [{"id": pending[0], "reason": REASON_PENDING_HANDOVER}]
