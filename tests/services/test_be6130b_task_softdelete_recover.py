# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Task
from giljo_mcp.models.auth import User
from giljo_mcp.models.products import Product


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def active_product(db_session, test_tenant_key) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"BE6130b Product {uuid4().hex[:6]}",
        description="soft-delete/recover task tests",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest_asyncio.fixture
async def admin_user(db_session, test_tenant_key) -> User:
    user = User(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        username=f"admin_{uuid4().hex[:6]}",
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _create_task(task_service, tenant_key) -> dict:
    return await task_service.create_task_for_mcp(
        title=f"task {uuid4().hex[:6]}", description="be6130b soft-delete test task", tenant_key=tenant_key
    )


async def test_delete_then_recover_round_trips(task_service, db_session, test_tenant_key, active_product, admin_user):
    created = await _create_task(task_service, test_tenant_key)
    task_id = created["task_id"]

    assert task_id in {t.id for t in await task_service.list_tasks(tenant_key=test_tenant_key)}

    await task_service.delete_task(task_id, str(admin_user.id))

    with pytest.raises(ResourceNotFoundError):
        await task_service.get_task(task_id)
    assert task_id not in {t.id for t in await task_service.list_tasks(tenant_key=test_tenant_key)}

    trashed = await task_service.list_deleted_tasks(product_id=active_product.id, tenant_key=test_tenant_key)
    assert task_id in {t.id for t in trashed}
    assert next(t for t in trashed if t.id == task_id).deleted_at is not None

    restored = await task_service.restore_task(task_id)
    assert restored.deleted_at is None
    assert task_id in {t.id for t in await task_service.list_tasks(tenant_key=test_tenant_key)}
    assert (await task_service.get_task(task_id)).id == task_id
    trashed = await task_service.list_deleted_tasks(product_id=active_product.id, tenant_key=test_tenant_key)
    assert task_id not in {t.id for t in trashed}


async def test_trashed_task_frees_serial_and_restore_remints(
    task_service, db_session, test_tenant_key, active_product, admin_user
):
    a = await _create_task(task_service, test_tenant_key)
    task_a = (await db_session.execute(select(Task).where(Task.id == a["task_id"]))).scalar_one()
    assert task_a.series_number == 1

    await task_service.delete_task(a["task_id"], str(admin_user.id))

    b = await _create_task(task_service, test_tenant_key)
    task_b = (await db_session.execute(select(Task).where(Task.id == b["task_id"]))).scalar_one()
    assert task_b.series_number == 1

    restored = await task_service.restore_task(a["task_id"])
    assert restored.series_number == 2
    assert restored.series_number != task_b.series_number


async def test_recover_window_expired_is_rejected(
    task_service, db_session, test_tenant_key, active_product, admin_user
):
    created = await _create_task(task_service, test_tenant_key)
    task_id = created["task_id"]
    await task_service.delete_task(task_id, str(admin_user.id))

    await db_session.execute(
        update(Task).where(Task.id == task_id).values(deleted_at=datetime.now(UTC) - timedelta(days=31))
    )
    await db_session.flush()

    with pytest.raises(ValidationError):
        await task_service.restore_task(task_id)

    trashed = await task_service.list_deleted_tasks(product_id=active_product.id, tenant_key=test_tenant_key)
    assert task_id in {t.id for t in trashed}


async def test_restore_is_tenant_isolated(
    task_service, db_manager, db_session, test_tenant_key, active_product, admin_user
):
    created = await _create_task(task_service, test_tenant_key)
    task_id = created["task_id"]
    await task_service.delete_task(task_id, str(admin_user.id))

    from unittest.mock import MagicMock

    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.tenant import TenantManager

    other_tenant = TenantManager.generate_tenant_key()
    other_tm = MagicMock()
    other_tm.get_current_tenant.return_value = other_tenant
    other_service = TaskService(db_manager=db_manager, tenant_manager=other_tm, session=db_session)
    with pytest.raises(ResourceNotFoundError):
        await other_service.restore_task(task_id)

    restored = await task_service.restore_task(task_id)
    assert restored.id == task_id
