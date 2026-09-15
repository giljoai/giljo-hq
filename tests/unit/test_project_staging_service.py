# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ProjectStateError, ResourceNotFoundError
from giljo_mcp.models import Product, Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.project_staging_service import ProjectStagingService


@pytest.fixture
def staging_service(db_session, test_tenant_key):
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return ProjectStagingService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_project(session, tenant_key, *, staging_status=None, status=ProjectStatus.INACTIVE):
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Staging Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    await session.flush()

    project = Project(
        tenant_key=tenant_key,
        product_id=product.id,
        name="Staging Project",
        description="seeded",
        mission="seeded mission",
        status=status,
        staging_status=staging_status,
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()
    return project




def test_check_staging_allowed_raises_when_staging():
    project = MagicMock()
    project.staging_status = "staging"
    project.id = "test-id"

    service = ProjectStagingService(MagicMock(), MagicMock())
    with pytest.raises(ProjectStateError):
        service.check_staging_allowed(project)


def test_check_staging_allowed_passes_when_not_staging():
    project = MagicMock()
    project.staging_status = None
    project.id = "test-id"

    service = ProjectStagingService(MagicMock(), MagicMock())
    service.check_staging_allowed(project)




@pytest.mark.asyncio
async def test_restage_raises_for_missing_project(staging_service, test_tenant_key):
    with pytest.raises(ResourceNotFoundError):
        await staging_service.restage("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_unstage_raises_for_missing_project(staging_service, test_tenant_key):
    with pytest.raises(ResourceNotFoundError):
        await staging_service.unstage("00000000-0000-0000-0000-000000000000")




@pytest.mark.asyncio
async def test_restage_success_resets_state(db_session, test_tenant_key):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    lifecycle = MagicMock()
    lifecycle._ensure_orchestrator_fixture = AsyncMock(return_value={"job_id": "J", "agent_id": "A"})
    service = ProjectStagingService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
        lifecycle_service=lifecycle,
    )

    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staging")
        project.execution_mode = "claude_code_cli"
        project.implementation_launched_at = datetime.now(UTC)
        await db_session.flush()

    result = await service.restage(str(project.id))

    assert result["message"] == "Project restaged successfully"
    assert result["new_orchestrator"] == {"job_id": "J", "agent_id": "A"}
    assert project.staging_status is None
    assert project.execution_mode == "claude_code_cli"
    assert project.mission == ""
    assert project.implementation_launched_at is None
    lifecycle._ensure_orchestrator_fixture.assert_awaited_once()


@pytest.mark.asyncio
async def test_restage_raises_when_not_staged(staging_service, db_session, test_tenant_key):
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status=None)

    with pytest.raises(ProjectStateError):
        await staging_service.restage(str(project.id))


@pytest.mark.asyncio
async def test_restage_from_staging_complete_succeeds(db_session, test_tenant_key):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    lifecycle = MagicMock()
    lifecycle._ensure_orchestrator_fixture = AsyncMock(return_value={"job_id": "J2", "agent_id": "A2"})
    service = ProjectStagingService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
        lifecycle_service=lifecycle,
    )

    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staging_complete")
        project.execution_mode = "claude_code_cli"
        await db_session.flush()

    result = await service.restage(str(project.id))

    assert result["message"] == "Project restaged successfully"
    assert project.staging_status is None
    assert project.mission == ""
    assert project.execution_mode == "claude_code_cli"
    lifecycle._ensure_orchestrator_fixture.assert_awaited_once()


@pytest.mark.asyncio
async def test_restage_blocked_when_implementation_launched(db_session, test_tenant_key):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    lifecycle = MagicMock()
    lifecycle._ensure_orchestrator_fixture = AsyncMock(return_value={"job_id": "J3", "agent_id": "A3"})
    service = ProjectStagingService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
        lifecycle_service=lifecycle,
    )

    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staging_complete")
        project.implementation_launched_at = datetime.now(UTC)
        await db_session.flush()

    with pytest.raises(ProjectStateError):
        await service.restage(str(project.id))

    lifecycle._ensure_orchestrator_fixture.assert_not_awaited()




@pytest.mark.asyncio
async def test_unstage_success_clears_staging_status_and_mission(staging_service, db_session, test_tenant_key):
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staged")

    assert project.mission

    result = await staging_service.unstage(str(project.id))

    assert result["message"] == "Project unstaged successfully"
    assert project.staging_status is None
    assert project.mission == ""

    project_service = ProjectService(MagicMock(), MagicMock())
    project_service._apply_project_updates(project, {"execution_mode": "claude_code_cli"})
    assert project.execution_mode == "claude_code_cli"


@pytest.mark.asyncio
async def test_unstage_raises_when_not_in_staged_state(staging_service, db_session, test_tenant_key):
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staging")

    with pytest.raises(ProjectStateError):
        await staging_service.unstage(str(project.id))




@pytest.mark.asyncio
async def test_cancel_staging_success_sets_cancelled(staging_service, db_session, test_tenant_key):
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(
            db_session, test_tenant_key, staging_status="staging", status=ProjectStatus.INACTIVE
        )

    result = await staging_service.cancel_staging(str(project.id))

    assert result.status == ProjectStatus.CANCELLED
    assert project.status == ProjectStatus.CANCELLED
    assert project.completed_at is not None


@pytest.mark.asyncio
async def test_cancel_staging_raises_when_not_inactive_staging(staging_service, db_session, test_tenant_key):
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status=None, status=ProjectStatus.INACTIVE)

    with pytest.raises(ProjectStateError):
        await staging_service.cancel_staging(str(project.id))
