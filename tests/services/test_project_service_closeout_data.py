# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for ProjectService.get_closeout_data (Handover 0249a).
Updated 0730d: Exception-based error handling patterns (no success wrappers).
Updated 0731c: Typed returns - get_closeout_data returns CloseoutData model.
"""

import random
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.schemas.service_responses import CloseoutData
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


@pytest.mark.asyncio
async def test_get_closeout_data_all_agents_complete(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    """Closeout data reflects all agents completed successfully."""
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Closeout Ready",
        mission="Finish the reporting module",
        description="Reporting work",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    for i in range(3):
        job = AgentJob(
            job_id=f"job-complete-{i}",
            tenant_key=tenant_key,
            project_id=project.id,
            job_type="developer",
            mission="Implement feature",
        )
        db_session.add(job)
        db_session.add(
            AgentExecution(
                job_id=job.job_id,
                tenant_key=tenant_key,
                agent_display_name="developer",
                status="complete",
            )
        )

    await db_session.commit()

    service = ProjectService(db_manager, tenant_manager)
    # 0731c: get_closeout_data returns CloseoutData typed model
    data = await service.closeout.get_closeout_data(project.id, db_session=db_session)

    assert isinstance(data, CloseoutData)
    assert data.project_id == project.id
    assert data.project_name == "Closeout Ready"
    assert data.agent_count == 3
    assert data.completed_agents == 3
    assert data.blocked_agents == 0
    assert data.all_agents_complete is True
    assert data.has_blocked_agents is False


@pytest.mark.asyncio
async def test_get_closeout_data_with_blocked_agents(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    """Closeout data reports blocked agents and incomplete status."""
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Mixed Outcomes",
        mission="Ship analytics",
        description="Analytics work",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job1 = AgentJob(
        job_id="job-ok-1",
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="developer",
        mission="Implement",
    )
    db_session.add(job1)
    db_session.add(
        AgentExecution(
            job_id=job1.job_id,
            tenant_key=tenant_key,
            agent_display_name="developer",
            status="complete",
        )
    )

    job2 = AgentJob(
        job_id="job-failed-1",
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="tester",
        mission="Test",
    )
    db_session.add(job2)
    db_session.add(
        AgentExecution(
            job_id=job2.job_id,
            tenant_key=tenant_key,
            agent_display_name="tester",
            status="blocked",
        )
    )

    job3 = AgentJob(
        job_id="job-working-1",
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="analyst",
        mission="Analyze",
    )
    db_session.add(job3)
    db_session.add(
        AgentExecution(
            job_id=job3.job_id,
            tenant_key=tenant_key,
            agent_display_name="analyst",
            status="working",
        )
    )

    await db_session.commit()

    service = ProjectService(db_manager, tenant_manager)
    # 0731c: get_closeout_data returns CloseoutData typed model
    data = await service.closeout.get_closeout_data(project.id, db_session=db_session)

    assert isinstance(data, CloseoutData)
    assert data.project_id == project.id
    assert data.project_name == "Mixed Outcomes"
    assert data.agent_count == 3
    assert data.completed_agents == 1
    assert data.blocked_agents == 1
    assert data.all_agents_complete is False
    assert data.has_blocked_agents is True


@pytest.mark.asyncio
async def test_get_closeout_data_with_git_integration(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    """Closeout data reflects Git integration when enabled on the product."""
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    product = Product(
        name="Git Product",
        tenant_key=tenant_key,
        product_memory={"git_integration": {"enabled": True, "repo_name": "demo-repo"}},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        name="Git Enabled Project",
        mission="Ship CLI",
        description="CLI delivery",
        tenant_key=tenant_key,
        product_id=product.id,
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id="job-complete-git",
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="developer",
        mission="Implement",
    )
    db_session.add(job)
    await db_session.flush()

    db_session.add(
        AgentExecution(
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="developer",
            status="complete",
        )
    )

    await db_session.commit()

    service = ProjectService(db_manager, tenant_manager)
    # 0731c: get_closeout_data returns CloseoutData typed model
    data = await service.closeout.get_closeout_data(project.id, db_session=db_session)

    assert isinstance(data, CloseoutData)
    assert data.project_id == project.id
    assert data.project_name == "Git Enabled Project"
    assert data.agent_count == 1
    assert data.completed_agents == 1
    assert data.blocked_agents == 0
    assert data.all_agents_complete is True
    assert data.has_blocked_agents is False


@pytest.mark.asyncio
async def test_get_closeout_data_tenant_isolation(db_manager, db_session: AsyncSession, tenant_manager: TenantManager):
    """Closeout data cannot be fetched across tenants."""
    tenant_one = TenantManager.generate_tenant_key()
    tenant_two = TenantManager.generate_tenant_key()

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_one,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Tenant One Project",
        mission="Isolation check",
        description="Isolation test",
        tenant_key=tenant_one,
        product_id=_owning_product_project.id,
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()

    tenant_manager.set_current_tenant(tenant_two)
    service = ProjectService(db_manager, tenant_manager)

    # 0731c: Exception-based error handling - raises ResourceNotFoundError
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await service.closeout.get_closeout_data(project.id)

    assert "not found" in str(exc_info.value).lower()
