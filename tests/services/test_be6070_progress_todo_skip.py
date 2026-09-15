# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.progress_service import ProgressService


pytestmark = pytest.mark.asyncio


@pytest.fixture
def ws_manager():
    mock = MagicMock()
    mock.broadcast_to_tenant = AsyncMock()
    return mock


@pytest.fixture
async def seeded_job(db_session, test_tenant_key):
    suffix = uuid4().hex[:8]
    product = Product(id=str(uuid4()), tenant_key=test_tenant_key, name=f"P {suffix}", description="x")
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        name=f"Proj {suffix}",
        description="x",
        mission="x",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="x",
        status="active",
    )
    db_session.add(job)
    execution = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_display_name="impl",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    for seq, item in enumerate(
        [
            {"content": "Step 1", "status": "completed"},
            {"content": "Step 2", "status": "in_progress"},
            {"content": "Step 3", "status": "pending"},
        ]
    ):
        db_session.add(
            AgentTodoItem(
                job_id=job_id,
                tenant_key=test_tenant_key,
                content=item["content"],
                status=item["status"],
                sequence=seq,
            )
        )
    await db_session.commit()
    return job_id


def _service_with_spies(db_session, test_tenant_key, ws_manager):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    service = ProgressService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
        websocket_manager=ws_manager,
    )
    counters = {"delete": 0, "insert": 0}
    real_delete = service._repo.delete_todo_items
    real_add = service._repo.add_todo_item

    async def _spy_delete(session, tenant_key, job_id):
        counters["delete"] += 1
        return await real_delete(session, tenant_key, job_id)

    async def _spy_add(session, todo_item):
        counters["insert"] += 1
        return await real_add(session, todo_item)

    service._repo.delete_todo_items = _spy_delete
    service._repo.add_todo_item = _spy_add
    return service, counters


_SAME_LIST = [
    {"content": "Step 1", "status": "completed"},
    {"content": "Step 2", "status": "in_progress"},
    {"content": "Step 3", "status": "pending"},
]


async def test_unchanged_list_skips_delete_and_insert(db_session, test_tenant_key, seeded_job, ws_manager):
    service, counters = _service_with_spies(db_session, test_tenant_key, ws_manager)

    result = await service.report_progress(job_id=seeded_job, tenant_key=test_tenant_key, todo_items=_SAME_LIST)

    assert result.status == "success"
    assert counters["delete"] == 0, "unchanged list must NOT delete rows"
    assert counters["insert"] == 0, "unchanged list must NOT insert rows"


async def test_changed_list_rewrites_rows(db_session, test_tenant_key, seeded_job, ws_manager):
    service, counters = _service_with_spies(db_session, test_tenant_key, ws_manager)

    changed = [
        {"content": "Step 1", "status": "completed"},
        {"content": "Step 2", "status": "completed"},
        {"content": "Step 3", "status": "pending"},
    ]
    result = await service.report_progress(job_id=seeded_job, tenant_key=test_tenant_key, todo_items=changed)

    assert result.status == "success"
    assert counters["delete"] == 1
    assert counters["insert"] == 3

    rows = (
        (
            await db_session.execute(
                select(AgentTodoItem)
                .where(AgentTodoItem.job_id == seeded_job, AgentTodoItem.tenant_key == test_tenant_key)
                .order_by(AgentTodoItem.sequence)
            )
        )
        .scalars()
        .all()
    )
    assert [r.status for r in rows] == ["completed", "completed", "pending"]


async def test_regression_guard_still_fires(db_session, test_tenant_key, seeded_job, ws_manager):
    service, counters = _service_with_spies(db_session, test_tenant_key, ws_manager)

    regressed = [
        {"content": "Step 1", "status": "pending"},
        {"content": "Step 2", "status": "pending"},
    ]
    with pytest.raises(ValidationError):
        await service.report_progress(job_id=seeded_job, tenant_key=test_tenant_key, todo_items=regressed)

    assert counters["delete"] == 0, "guard must reject BEFORE any delete"


async def test_unchanged_list_still_broadcasts_full_payload(db_session, test_tenant_key, seeded_job, ws_manager):
    service, _counters = _service_with_spies(db_session, test_tenant_key, ws_manager)

    await service.report_progress(job_id=seeded_job, tenant_key=test_tenant_key, todo_items=_SAME_LIST)

    progress_calls = [
        c for c in ws_manager.broadcast_to_tenant.call_args_list if c.kwargs.get("event_type") == "job:progress_update"
    ]
    assert progress_calls, "expected a job:progress_update broadcast"
    payload = progress_calls[-1].kwargs["data"]["todo_items"]
    assert payload == _SAME_LIST, f"WS payload should carry the full list, got {payload!r}"
