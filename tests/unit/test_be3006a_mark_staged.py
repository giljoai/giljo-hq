# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Project
from giljo_mcp.models.products import Product
from giljo_mcp.services.project_staging_service import ProjectStagingService


@pytest.fixture
def staging_service(db_session, test_tenant_key):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return ProjectStagingService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_product(session, tenant_key):
    product = Product(id=str(uuid.uuid4()), tenant_key=tenant_key, name="Mark-Staged Test Product")
    session.add(product)
    await session.flush()
    return product


async def _seed_project(session, tenant_key, *, staging_status="staging", launched=False, execution_mode=None):
    product = await _seed_product(session, tenant_key)
    project = Project(
        tenant_key=tenant_key,
        product_id=product.id,
        name="Mark-Staged Project",
        description="seeded",
        mission="seeded mission",
        status=ProjectStatus.INACTIVE,
        staging_status=staging_status,
        execution_mode=execution_mode,
        implementation_launched_at=datetime.now(UTC) if launched else None,
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_mark_staged_persists_staged_and_mode(staging_service, db_session, test_tenant_key):
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, execution_mode=None)

    await staging_service.mark_staged(str(project.id), "claude_code_cli")

    assert project.staging_status == "staged"
    assert project.execution_mode == "claude_code_cli"


@pytest.mark.asyncio
async def test_mark_staged_respects_launch_lock(staging_service, db_session, test_tenant_key):
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, launched=True, execution_mode="multi_terminal")

    await staging_service.mark_staged(str(project.id), "claude_code_cli")

    assert project.staging_status == "staged"
    assert project.execution_mode == "multi_terminal"


@pytest.mark.asyncio
async def test_mark_staged_raises_for_missing_project(staging_service):
    with pytest.raises(ResourceNotFoundError):
        await staging_service.mark_staged("00000000-0000-0000-0000-000000000000", "multi_terminal")


@pytest.mark.asyncio
async def test_mark_staged_accepts_caller_session_and_explicit_tenant(db_session, test_tenant_key):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    db_manager = MagicMock()
    db_manager.get_session_async.side_effect = AssertionError("must not open a new session")
    staging_service = ProjectStagingService(db_manager=db_manager, tenant_manager=tenant_manager)

    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, execution_mode=None)

        await staging_service.mark_staged(
            str(project.id), "claude_code_cli", tenant_key=test_tenant_key, db_session=db_session
        )

    assert project.staging_status == "staged"
    assert project.execution_mode == "claude_code_cli"
    db_manager.get_session_async.assert_not_called()


@pytest.mark.asyncio
async def test_mark_staged_raises_for_missing_project_with_caller_session(db_session, test_tenant_key):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    staging_service = ProjectStagingService(db_manager=MagicMock(), tenant_manager=tenant_manager)

    with tenant_session_context(db_session, test_tenant_key), pytest.raises(ResourceNotFoundError):
        await staging_service.mark_staged(
            "00000000-0000-0000-0000-000000000000",
            "multi_terminal",
            tenant_key=test_tenant_key,
            db_session=db_session,
        )


@pytest.mark.asyncio
async def test_mark_staged_no_tenant_available_raises_validation_error():
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = None
    staging_service = ProjectStagingService(db_manager=MagicMock(), tenant_manager=tenant_manager)

    with pytest.raises(ValidationError):
        await staging_service.mark_staged(str(uuid.uuid4()), "multi_terminal")
