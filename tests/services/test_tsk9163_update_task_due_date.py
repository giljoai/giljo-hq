# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Task
from giljo_mcp.services.taxonomy_service import TaxonomyService


pytestmark = pytest.mark.asyncio


async def _insert_legacy_shaped_task(db_session, tenant_key: str, product_id: str) -> str:
    task_id = str(uuid4())
    db_session.add(
        Task(
            id=task_id,
            tenant_key=tenant_key,
            product_id=product_id,
            title="INF-legacy operator-gated deploy validation",
            description="legacy-shaped row for TSK-9163 repro",
            status="pending",
            priority="high",
            series_number=6010,
            created_at=datetime(2026, 5, 29, 2, 16, 5, tzinfo=UTC),
        )
    )
    await db_session.commit()
    return task_id


async def _get_due_date(db_session, tenant_key: str, task_id: str):
    with tenant_session_context(db_session, tenant_key):
        result = await db_session.execute(
            select(Task.due_date).where(Task.id == task_id, Task.tenant_key == tenant_key)
        )
        return result.scalar_one()


async def test_update_task_due_date_string_on_legacy_shaped_row(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]
    task_service = two_tenant_service_setup["task_service_a"]

    task_id = await _insert_legacy_shaped_task(db_session, tenant_a, product_a.id)

    result = await task_service.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
        due_date="2026-07-15",
    )

    assert "due_date" in result["updated_fields"]
    stored = await _get_due_date(db_session, tenant_a, task_id)
    assert stored is not None
    assert (stored.year, stored.month, stored.day) == (2026, 7, 15)


async def test_update_task_due_date_string_on_fresh_row(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service = two_tenant_service_setup["task_service_a"]

    taxonomy = TaxonomyService(db_manager=db_manager, session=db_session)
    await taxonomy.ensure_reserved_task_type(tenant_a)

    created = await task_service.create_task_for_mcp(
        title="fresh row due_date write",
        description="",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    task_id = created["task_id"]

    result = await task_service.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
        due_date="2026-07-15T09:00:00+00:00",
    )

    assert "due_date" in result["updated_fields"]
    stored = await _get_due_date(db_session, tenant_a, task_id)
    assert stored is not None
    assert (stored.year, stored.month, stored.day) == (2026, 7, 15)


async def test_update_task_due_date_garbage_string_is_agent_actionable(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]
    task_service = two_tenant_service_setup["task_service_a"]

    task_id = await _insert_legacy_shaped_task(db_session, tenant_a, product_a.id)

    with pytest.raises(ValidationError):
        await task_service.update_task_for_mcp(
            task_id=task_id,
            tenant_key=tenant_a,
            due_date="not-a-date",
        )

    assert await _get_due_date(db_session, tenant_a, task_id) is None


async def test_update_task_due_date_datetime_object_still_works(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]
    task_service = two_tenant_service_setup["task_service_a"]

    task_id = await _insert_legacy_shaped_task(db_session, tenant_a, product_a.id)

    result = await task_service.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
        due_date=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )

    assert "due_date" in result["updated_fields"]
    stored = await _get_due_date(db_session, tenant_a, task_id)
    assert (stored.year, stored.month, stored.day) == (2026, 7, 20)
