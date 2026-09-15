# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.tools.context_tools.get_tasks import get_tasks


pytestmark = pytest.mark.asyncio


async def test_get_tasks_returns_open_tasks_only(db_session, db_manager, two_tenant_service_setup):
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.services.taxonomy_service import TaxonomyService
    from giljo_mcp.tenant import TenantManager

    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]

    tax = TaxonomyService(db_manager=db_manager, session=db_session)
    await tax.create_type(tenant_key=tenant_a, abbreviation="BE", label="Backend")
    await db_session.commit()

    task_service = TaskService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
    )
    open_response = await task_service.create_task_for_mcp(
        title="Open task",
        description="still pending",
        task_type="BE",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    closed_response = await task_service.create_task_for_mcp(
        title="Closed task",
        description="done",
        task_type="BE",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    await task_service.update_task_for_mcp(
        task_id=closed_response["task_id"],
        status="completed",
        tenant_key=tenant_a,
    )
    await db_session.commit()

    result = await get_tasks(
        product_id=product_a.id,
        tenant_key=tenant_a,
        db_manager=db_manager,
        session=db_session,
    )

    assert result["source"] == "tasks"
    rows = result["data"]["tasks"]
    ids = {r["task_id"] for r in rows}
    assert open_response["task_id"] in ids
    assert closed_response["task_id"] not in ids
    assert result["data"]["open_count"] == len(rows)


async def test_get_tasks_does_not_leak_other_tenant_tasks(db_session, db_manager, two_tenant_service_setup):
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.services.taxonomy_service import TaxonomyService
    from giljo_mcp.tenant import TenantManager

    tenant_a = two_tenant_service_setup["tenant_a"]
    tenant_b = two_tenant_service_setup["tenant_b"]
    product_a = two_tenant_service_setup["product_a"]

    tax = TaxonomyService(db_manager=db_manager, session=db_session)
    await tax.create_type(tenant_key=tenant_b, abbreviation="BE", label="Backend")
    await db_session.commit()

    task_service_b = TaskService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
    )
    b_response = await task_service_b.create_task_for_mcp(
        title="tenant B only",
        description="x",
        task_type="BE",
        tenant_key=tenant_b,
        db_manager=db_manager,
    )
    await db_session.commit()

    result = await get_tasks(
        product_id=product_a.id,
        tenant_key=tenant_a,
        db_manager=db_manager,
        session=db_session,
    )
    ids = {r["task_id"] for r in result["data"]["tasks"]}
    assert b_response["task_id"] not in ids
