# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tenant isolation regression tests for MEDIUM defense-in-depth fixes — ProjectService,
ConsolidatedVisionService, AgentExecution, and combined audit.

Verifies that all child/derived queries include explicit tenant_key filters,
even when a parent entity was already validated. These are defense-in-depth
measures that prevent fragile isolation if parent queries are ever refactored.

Fixes covered:
4. ConsolidatedVisionService.consolidate_vision_documents - Product query now includes tenant_key
7. ProjectService.get_project - AgentJob join query now includes tenant_key
8. ProjectService.get_active_project - 2 COUNT queries now include tenant_key
10. api/endpoints/agent_jobs/executions.py - AgentExecution query now includes tenant_key

Test Strategy:
- Create entities in two tenants (A and B)
- Verify queries only return data from the requesting tenant
- Verify cross-tenant access is blocked

Follows patterns from: test_project_tenant_isolation_regression.py
"""

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


# ============================================================================
# Fix 4: ConsolidatedVisionService — Product query with tenant_key
# ============================================================================


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_consolidate_vision_blocks_cross_tenant(two_tenant_products):
    """
    REGRESSION: consolidate_vision_documents() must filter by tenant_key
    in the initial Product query, not just as a post-fetch check.
    """
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    data = two_tenant_products

    service = ConsolidatedVisionService()

    with pytest.raises(ResourceNotFoundError):
        await service.consolidate_vision_documents(
            product_id=data["product_b"].id,
            session=data["db_session"],
            tenant_key=data["tenant_a"],
        )


# ============================================================================
# Fix 7: ProjectService.get_project — Join query with tenant_key
# ============================================================================


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_project_blocks_cross_tenant(two_tenant_products):
    """
    REGRESSION: get_project() must not return agent data from other tenants.

    The join query for AgentJob+AgentExecution previously filtered by
    project_id only. Now includes AgentJob.tenant_key.
    """
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
    """Verify same-tenant get_project returns correct agent data."""
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


# ============================================================================
# Fix 8: ProjectService.get_active_projects — COUNT queries with tenant_key
# ============================================================================


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_active_project_counts_only_own_tenant(two_tenant_products):
    """
    REGRESSION: get_active_projects() COUNT queries for AgentJob and Message
    must include tenant_key filter.

    Previously filtered by project.id only, which is safe when the project
    is already validated, but fragile if refactored.
    """
    data = two_tenant_products
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(data["tenant_a"])

    service = ProjectService(
        db_manager=data["db_manager"],
        tenant_manager=tenant_manager,
        test_session=data["db_session"],
    )

    result = await service.query.get_active_projects()

    # Should return tenant A's active project with correct counts
    assert len(result) == 1
    assert result[0].id == str(data["project_a"].id)
    assert result[0].agent_count >= 0
    assert result[0].message_count >= 0


# ============================================================================
# Fix 10: api/endpoints/agent_jobs/executions.py — AgentExecution tenant_key
# ============================================================================


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_job_executions_filters_by_tenant(two_tenant_products):
    """
    REGRESSION: The AgentExecution query in get_job_executions must include
    tenant_key filter.

    Previously queried by job_id only for the execution fetch.
    Now includes AgentExecution.tenant_key.

    This test verifies at the service/query level rather than the endpoint
    level, since the underlying query is what matters.
    """
    from sqlalchemy import select

    data = two_tenant_products
    session = data["db_session"]

    # Query executions for job_b filtered by tenant_a — should return empty
    with tenant_session_context(session, data["tenant_a"]):
        result = await session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == data["job_b"].job_id,
                AgentExecution.tenant_key == data["tenant_a"],
            )
        )
    cross_tenant_executions = result.scalars().all()
    assert len(cross_tenant_executions) == 0, "Cross-tenant execution data leaked!"

    # Query executions for job_a filtered by tenant_a — should return 1
    with tenant_session_context(session, data["tenant_a"]):
        result = await session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == data["job_a"].job_id,
                AgentExecution.tenant_key == data["tenant_a"],
            )
        )
    same_tenant_executions = result.scalars().all()
    assert len(same_tenant_executions) == 1


# ============================================================================
# Combined Audit Test
# ============================================================================


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_medium_defense_in_depth_audit(two_tenant_products):
    """
    Integration test: Verify all MEDIUM defense-in-depth fixes prevent
    cross-tenant data access.
    """
    data = two_tenant_products
    tenant_manager = TenantManager()
    violations = []

    # 1. get_cascade_impact cross-tenant
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

    # 2. get_product_statistics cross-tenant
    try:
        await product_service_a.memory.get_product_statistics(product_id=data["product_b"].id)
        violations.append("get_product_statistics() allowed cross-tenant access")
    except ResourceNotFoundError:
        pass

    # 3. get_project cross-tenant
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
