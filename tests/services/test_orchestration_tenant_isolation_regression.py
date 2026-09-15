# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture(scope="function")
async def two_tenant_orchestration(db_session, db_manager):
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()

    product_a = Product(
        id=str(uuid.uuid4()),
        name="Tenant A Product",
        description="Product for tenant A",
        tenant_key=tenant_a,
        is_active=True,
    )
    product_b = Product(
        id=str(uuid.uuid4()),
        name="Tenant B Product",
        description="Product for tenant B",
        tenant_key=tenant_b,
        is_active=True,
    )
    db_session.add(product_a)
    db_session.add(product_b)
    await db_session.commit()

    project_a = Project(
        id=str(uuid.uuid4()),
        name="Tenant A Project",
        description="Project for tenant A",
        mission="Tenant A mission",
        tenant_key=tenant_a,
        product_id=product_a.id,
        status="active",
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    project_b = Project(
        id=str(uuid.uuid4()),
        name="Tenant B Project",
        description="Project for tenant B",
        mission="Tenant B mission",
        tenant_key=tenant_b,
        product_id=product_b.id,
        status="active",
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_a)
    db_session.add(project_b)
    await db_session.commit()

    job_a = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_a,
        project_id=project_a.id,
        job_type="implementer",
        mission="Implement feature for tenant A",
        status="active",
        created_at=datetime.now(UTC),
        job_metadata={},
    )
    job_b = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_b,
        project_id=project_b.id,
        job_type="implementer",
        mission="Implement feature for tenant B",
        status="active",
        created_at=datetime.now(UTC),
        job_metadata={},
    )
    db_session.add(job_a)
    db_session.add(job_b)
    await db_session.commit()

    exec_a = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job_a.job_id,
        tenant_key=tenant_a,
        agent_display_name="implementer",
        status="working",
        started_at=datetime.now(UTC),
        mission_acknowledged_at=datetime.now(UTC),
    )
    exec_b = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job_b.job_id,
        tenant_key=tenant_b,
        agent_display_name="implementer",
        status="working",
        started_at=datetime.now(UTC),
        mission_acknowledged_at=datetime.now(UTC),
    )
    db_session.add(exec_a)
    db_session.add(exec_b)
    await db_session.commit()

    for obj in [job_a, job_b, exec_a, exec_b]:
        await db_session.refresh(obj)

    tenant_manager = TenantManager()
    service = OrchestrationService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "product_a": product_a,
        "product_b": product_b,
        "project_a": project_a,
        "project_b": project_b,
        "job_a": job_a,
        "job_b": job_b,
        "exec_a": exec_a,
        "exec_b": exec_b,
        "service": service,
    }




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_report_progress_blocks_cross_tenant(db_session, two_tenant_orchestration):
    tenant_a = two_tenant_orchestration["tenant_a"]
    job_b = two_tenant_orchestration["job_b"]
    service = two_tenant_orchestration["service"]

    with pytest.raises(ResourceNotFoundError):
        await service.report_progress(
            job_id=job_b.job_id,
            todo_items=[{"content": "Cross-tenant task", "status": "pending"}],
            tenant_key=tenant_a,
        )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_report_progress_same_tenant_succeeds(db_session, two_tenant_orchestration):
    tenant_a = two_tenant_orchestration["tenant_a"]
    job_a = two_tenant_orchestration["job_a"]
    service = two_tenant_orchestration["service"]

    result = await service.report_progress(
        job_id=job_a.job_id,
        todo_items=[{"content": "Same-tenant task", "status": "in_progress"}],
        tenant_key=tenant_a,
    )

    assert result.status == "success"




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_agent_mission_blocks_cross_tenant(db_session, two_tenant_orchestration):
    tenant_a = two_tenant_orchestration["tenant_a"]
    job_b = two_tenant_orchestration["job_b"]
    service = two_tenant_orchestration["service"]

    with pytest.raises(ResourceNotFoundError):
        await service.get_agent_mission(
            job_id=job_b.job_id,
            tenant_key=tenant_a,
        )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_agent_mission_same_tenant_succeeds(db_session, two_tenant_orchestration):
    tenant_a = two_tenant_orchestration["tenant_a"]
    job_a = two_tenant_orchestration["job_a"]
    service = two_tenant_orchestration["service"]

    result = await service.get_agent_mission(
        job_id=job_a.job_id,
        tenant_key=tenant_a,
    )

    assert result.job_id == job_a.job_id
    assert "Implement feature for tenant A" in result.mission




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_complete_job_blocks_cross_tenant(db_session, two_tenant_orchestration):
    tenant_a = two_tenant_orchestration["tenant_a"]
    job_b = two_tenant_orchestration["job_b"]
    exec_b = two_tenant_orchestration["exec_b"]
    service = two_tenant_orchestration["service"]

    with pytest.raises(ResourceNotFoundError):
        await service.complete_job(
            job_id=job_b.job_id,
            result={"output": "Cross-tenant completion"},
            tenant_key=tenant_a,
        )

    await db_session.refresh(exec_b)
    assert exec_b.status == "working", "Cross-tenant complete_job modified another tenant's execution!"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_complete_job_same_tenant_succeeds(db_session, two_tenant_orchestration):
    tenant_a = two_tenant_orchestration["tenant_a"]
    job_a = two_tenant_orchestration["job_a"]
    service = two_tenant_orchestration["service"]

    result = await service.complete_job(
        job_id=job_a.job_id,
        result={"output": "Same-tenant completion"},
        tenant_key=tenant_a,
    )

    assert result.job_id == job_a.job_id




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_report_error_blocks_cross_tenant(db_session, two_tenant_orchestration):
    tenant_a = two_tenant_orchestration["tenant_a"]
    job_b = two_tenant_orchestration["job_b"]
    exec_b = two_tenant_orchestration["exec_b"]
    service = two_tenant_orchestration["service"]

    with pytest.raises(ResourceNotFoundError):
        await service.set_agent_status(
            job_id=job_b.job_id,
            status="blocked",
            reason="Cross-tenant error report",
            tenant_key=tenant_a,
        )

    await db_session.refresh(exec_b)
    assert exec_b.status == "working", "Cross-tenant set_agent_status modified another tenant's execution!"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_set_agent_status_same_tenant_succeeds(db_session, two_tenant_orchestration):
    tenant_a = two_tenant_orchestration["tenant_a"]
    job_a = two_tenant_orchestration["job_a"]
    service = two_tenant_orchestration["service"]

    result = await service.set_agent_status(
        job_id=job_a.job_id,
        status="blocked",
        reason="Same-tenant error report",
        tenant_key=tenant_a,
    )

    assert result.job_id == job_a.job_id




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_orchestration_service_cross_tenant_audit(db_session, two_tenant_orchestration):
    tenant_a = two_tenant_orchestration["tenant_a"]
    job_b = two_tenant_orchestration["job_b"]
    exec_b = two_tenant_orchestration["exec_b"]
    service = two_tenant_orchestration["service"]

    violations = []

    try:
        await service.report_progress(
            job_id=job_b.job_id,
            todo_items=[{"content": "Cross-tenant", "status": "pending"}],
            tenant_key=tenant_a,
        )
        violations.append("report_progress() allowed cross-tenant progress report")
    except (ResourceNotFoundError, ValidationError):
        pass

    try:
        await service.get_agent_mission(
            job_id=job_b.job_id,
            tenant_key=tenant_a,
        )
        violations.append("get_agent_mission() allowed cross-tenant mission fetch")
    except (ResourceNotFoundError, ValidationError):
        pass

    try:
        await service.complete_job(
            job_id=job_b.job_id,
            result={"output": "Cross-tenant"},
            tenant_key=tenant_a,
        )
        violations.append("complete_job() allowed cross-tenant completion")
    except (ResourceNotFoundError, ValidationError):
        pass

    try:
        await service.set_agent_status(
            job_id=job_b.job_id,
            status="blocked",
            reason="Cross-tenant error",
            tenant_key=tenant_a,
        )
        violations.append("set_agent_status() allowed cross-tenant status change")
    except (ResourceNotFoundError, ValidationError):
        pass

    await db_session.refresh(exec_b)
    if exec_b.status != "working":
        violations.append(f"Tenant B execution status changed from 'working' to '{exec_b.status}'")

    assert len(violations) == 0, "CRITICAL: Tenant isolation violated!\nViolations:\n" + "\n".join(
        f"- {v}" for v in violations
    )
