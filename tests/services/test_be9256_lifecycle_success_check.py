# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid

import pytest
from sqlalchemy import func, select

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import BaseGiljoError
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
from giljo_mcp.tenant import TenantManager


async def _seed_product_and_project(db_manager: DatabaseManager, tenant_key: str) -> str:
    product_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name="BE-9256 Success-Check Product",
                description="Real-session product for the transaction-rollback regression",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        session.add(
            Project(
                id=project_id,
                name="BE-9256 Success-Check Project",
                description="Real-session project for the transaction-rollback regression",
                mission="Verify a Tier-2 rejection raises and rolls back",
                status="active",
                tenant_key=tenant_key,
                product_id=product_id,
                series_number=random.randint(1, 9000),
            )
        )
    return project_id


@pytest.mark.asyncio
async def test_titleless_git_commit_raises_and_rolls_back(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    project_id = await _seed_product_and_project(db_manager, tenant_key)

    service = ProjectLifecycleService(db_manager=db_manager, tenant_manager=TenantManager())

    with pytest.raises(BaseGiljoError):
        await service.complete_project(
            project_id=project_id,
            summary="This closeout must be rejected because the commit has no title.",
            key_outcomes=["Should never persist"],
            decisions_made=["Should never persist"],
            tenant_key=tenant_key,
            git_commits=[{"sha": "abc123", "message": ""}],
        )

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()
        assert project.status != ProjectStatus.COMPLETED, (
            "project must NOT be marked completed when the closeout was rejected"
        )

        count_result = await session.execute(
            select(func.count()).select_from(ProductMemoryEntry).where(ProductMemoryEntry.project_id == project_id)
        )
        assert count_result.scalar_one() == 0, "zero memory entries must be written when the closeout was rejected"


@pytest.fixture
async def project_linked_to_product(db_session, test_product, test_tenant_key) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name="BE-9256 Success-Check Regression Project",
        description="Project for the mcp_result success-check regression",
        mission="Verify a Tier-2 rejection from close_project_and_update_memory raises",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.mark.asyncio
async def test_titleless_git_commit_error_carries_actionable_context(
    project_service_with_session,
    test_tenant_key,
    project_linked_to_product,
):
    with pytest.raises(BaseGiljoError) as exc_info:
        await project_service_with_session.complete_project(
            project_id=project_linked_to_product.id,
            summary="This closeout must be rejected because the commit has no title.",
            key_outcomes=["Should never persist"],
            decisions_made=["Should never persist"],
            tenant_key=test_tenant_key,
            git_commits=[{"sha": "abc123", "message": ""}],
        )

    exc = exc_info.value
    assert exc.default_status_code < 500, (
        f"expected an actionable 4xx, got default_status_code={exc.default_status_code}"
    )
    assert exc.error_code == "GIT_COMMIT_TITLE_REQUIRED", (
        f"expected the GIT_COMMIT_TITLE_REQUIRED code, got {exc.error_code!r}"
    )
    assert exc.context.get("hint"), f"expected a self-correcting hint in context, got {exc.context!r}"
