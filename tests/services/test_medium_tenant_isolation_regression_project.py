# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_consolidate_vision_blocks_cross_tenant(two_tenant_products):
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    data = two_tenant_products

    service = ConsolidatedVisionService()

    with pytest.raises(ResourceNotFoundError):
        await service.consolidate_vision_documents(
            product_id=data["product_b"].id,
            session=data["db_session"],
            tenant_key=data["tenant_a"],
        )




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_project_blocks_cross_tenant(two_tenant_products):
    data = two_tenant_products
    tenant_manager = TenantManager()
    service = ProjectService(
        db_manager=data["db_manager"],
        tenant_manager=tenant_manager,
        test_session=data["db_session"],
    )

    with pytest.raises(ResourceNotFoundError):
        await service.get_project(
            project_id=data["project_b"].id,
            tenant_key=data["tenant_a"],
        )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_project_same_tenant_includes_agents(two_tenant_products):
    data = two_tenant_products
    tenant_manager = TenantManager()
    service = ProjectService(
        db_manager=data["db_manager"],
        tenant_manager=tenant_manager,
        test_session=data["db_session"],
    )

    result = await service.get_project(
        project_id=data["project_a"].id,
        tenant_key=data["tenant_a"],
    )

    assert result is not None
    assert result.id == str(data["project_a"].id)
    assert result.agent_count >= 1




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_active_project_counts_only_own_tenant(two_tenant_products):
    data = two_tenant_products
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(data["tenant_a"])

    service = ProjectService(
        db_manager=data["db_manager"],
        tenant_manager=tenant_manager,
        test_session=data["db_session"],
    )

    result = await service.query.get_active_projects()

    assert len(result) == 1
    assert result[0].id == str(data["project_a"].id)
    assert result[0].agent_count >= 0
    assert result[0].message_count >= 0




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_job_executions_filters_by_tenant(two_tenant_products):
    from sqlalchemy import select

    data = two_tenant_products
    session = data["db_session"]

    with tenant_session_context(session, data["tenant_a"]):
        result = await session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == data["job_b"].job_id,
                AgentExecution.tenant_key == data["tenant_a"],
            )
        )
    cross_tenant_executions = result.scalars().all()
    assert len(cross_tenant_executions) == 0, "Cross-tenant execution data leaked!"

    with tenant_session_context(session, data["tenant_a"]):
        result = await session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == data["job_a"].job_id,
                AgentExecution.tenant_key == data["tenant_a"],
            )
        )
    same_tenant_executions = result.scalars().all()
    assert len(same_tenant_executions) == 1




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_medium_defense_in_depth_audit(two_tenant_products):
    data = two_tenant_products
    tenant_manager = TenantManager()
    violations = []

    product_service_a = ProductService(
        db_manager=data["db_manager"],
        tenant_key=data["tenant_a"],
        test_session=data["db_session"],
    )
    try:
        await product_service_a.memory.get_cascade_impact(product_id=data["product_b"].id)
        violations.append("get_cascade_impact() allowed cross-tenant access")
    except ResourceNotFoundError:
        pass

    try:
        await product_service_a.memory.get_product_statistics(product_id=data["product_b"].id)
        violations.append("get_product_statistics() allowed cross-tenant access")
    except ResourceNotFoundError:
        pass

    project_service_a = ProjectService(
        db_manager=data["db_manager"],
        tenant_manager=tenant_manager,
        test_session=data["db_session"],
    )
    try:
        await project_service_a.get_project(
            project_id=data["project_b"].id,
            tenant_key=data["tenant_a"],
        )
        violations.append("get_project() allowed cross-tenant access")
    except ResourceNotFoundError:
        pass

    assert len(violations) == 0, "MEDIUM defense-in-depth violations found!\n" + "\n".join(f"- {v}" for v in violations)
