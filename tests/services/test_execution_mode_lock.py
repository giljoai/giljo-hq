# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.models import Product, Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


@pytest.mark.asyncio
async def test_update_execution_mode_allowed_before_staging(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Pre-Staging Project",
        mission="",
        description="Test description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="inactive",
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)
    result = await service.update_project(project.id, {"execution_mode": "claude_code_cli"})

    assert result.execution_mode == "claude_code_cli"
    assert result.id == project.id


@pytest.mark.asyncio
async def test_update_execution_mode_allowed_when_staged_but_not_launched(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Staged Not Launched Project",
        mission="Orchestrator-generated mission from staging.",
        description="Test description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="active",
        execution_mode="multi_terminal",
        staging_status="staging_complete",
        implementation_launched_at=None,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)
    result = await service.update_project(project.id, {"execution_mode": "claude_code_cli"})

    assert result.execution_mode == "claude_code_cli"


@pytest.mark.asyncio
async def test_update_execution_mode_blocked_after_implementation_launched(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Launched Project",
        mission="This is the orchestrator-generated mission for the project.",
        description="Test description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="active",
        execution_mode="claude_code_cli",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)

    with pytest.raises(ProjectStateError) as exc_info:
        await service.update_project(project.id, {"execution_mode": "multi_terminal"})

    error_msg = str(exc_info.value).lower()
    assert "launch" in error_msg or "implementation" in error_msg, (
        f"Expected error about implementation launch, got: {exc_info.value}"
    )


@pytest.mark.asyncio
async def test_update_other_fields_still_allowed_after_launch(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Locked Project",
        mission="Original generated mission",
        description="Original description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="active",
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)
    result = await service.update_project(
        project.id,
        {
            "name": "Updated Name",
            "description": "Updated description",
        },
    )

    assert result.name == "Updated Name"
    assert result.description == "Updated description"
    assert result.execution_mode == "multi_terminal"


@pytest.mark.asyncio
async def test_set_first_mode_allowed_when_unselected_despite_mission(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="CTX-like Project",
        mission="A bootstrap mission rendered at creation.",
        description="Test description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="inactive",
        execution_mode=None,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)
    result = await service.update_project(project.id, {"execution_mode": "claude_code_cli"})

    assert result.execution_mode == "claude_code_cli"
