# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_task_service_log_task_blocks_cross_tenant_project(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]
    project_b = two_tenant_service_setup["project_b"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service_a.log_task(
            product_id=product_a.id,
            project_id=project_b.id,
            content="Malicious task creation attempt",
            tenant_key=tenant_a,
        )

    assert "project" in str(exc_info.value).lower() or "not found" in str(exc_info.value).lower()


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_task_service_log_task_same_tenant_succeeds(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]
    project_a = two_tenant_service_setup["project_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    result = await task_service_a.log_task(
        product_id=product_a.id,
        project_id=project_a.id,
        content="Valid task creation",
        tenant_key=tenant_a,
    )

    if isinstance(result, dict):
        assert result.get("success") is True or result.get("task_id") is not None, "Same-tenant task logging failed!"
    else:
        assert result is not None and isinstance(result, str), "Same-tenant task logging failed!"




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_full_tenant_isolation_workflow(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    project_b = two_tenant_service_setup["project_b"]
    product_a = two_tenant_service_setup["product_a"]

    project_service_a = two_tenant_service_setup["project_service_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    violations = []

    try:
        await project_service_a.get_project(project_id=project_b.id, tenant_key=tenant_a)
        violations.append("get_project() allowed cross-tenant access - no exception raised")
    except ResourceNotFoundError:
        pass

    try:
        await project_service_a.update_project_mission(
            project_id=project_b.id, mission="Hijacked mission", tenant_key=tenant_a
        )
        violations.append("update_project_mission() allowed cross-tenant modification - no exception raised")
    except ResourceNotFoundError:
        pass

    try:
        await task_service_a.log_task(
            product_id=product_a.id,
            project_id=project_b.id,
            content="Cross-tenant attack",
            tenant_key=tenant_a,
        )
        violations.append("log_task() allowed cross-tenant creation - no exception raised")
    except (ValidationError, ResourceNotFoundError):
        pass

    assert len(violations) == 0, "CRITICAL: Tenant isolation violated!\nViolations:\n" + "\n".join(
        f"- {v}" for v in violations
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_isolation_does_not_break_normal_access(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]
    project_a = two_tenant_service_setup["project_a"]

    project_service_a = two_tenant_service_setup["project_service_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    failures = []

    try:
        result = await project_service_a.get_project(project_id=project_a.id, tenant_key=tenant_a)
        if result is None:
            failures.append("get_project() returned None for same-tenant access")
    except Exception as e:
        failures.append(f"get_project() raised exception for same-tenant access: {e}")

    try:
        result = await task_service_a.log_task(
            product_id=product_a.id,
            project_id=project_a.id,
            content="Same-tenant task",
            tenant_key=tenant_a,
        )
        if result is None:
            failures.append("log_task() returned None for same-tenant access")
    except Exception as e:
        failures.append(f"log_task() raised exception for same-tenant access: {e}")

    assert len(failures) == 0, "Normal access broken by tenant isolation!\nFailures:\n" + "\n".join(
        f"- {f}" for f in failures
    )
