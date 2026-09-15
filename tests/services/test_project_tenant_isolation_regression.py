# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture(scope="function")
async def two_tenant_projects(db_session, db_manager):
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

    active_a = Project(
        id=str(uuid.uuid4()),
        name="Tenant A Active",
        description="Active project A desc",
        mission="Active project A",
        tenant_key=tenant_a,
        product_id=product_a.id,
        status="active",
        series_number=8101,
    )
    active_b = Project(
        id=str(uuid.uuid4()),
        name="Tenant B Active",
        description="Active project B desc",
        mission="Active project B",
        tenant_key=tenant_b,
        product_id=product_b.id,
        status="active",
        series_number=8102,
    )

    deleted_a = Project(
        id=str(uuid.uuid4()),
        name="Tenant A Deleted",
        description="Deleted project A desc",
        mission="Deleted project A",
        tenant_key=tenant_a,
        product_id=product_a.id,
        status="deleted",
        deleted_at=datetime.now(UTC),
        series_number=8103,
    )

    cancelled_b = Project(
        id=str(uuid.uuid4()),
        name="Tenant B Cancelled",
        description="Cancelled project B desc",
        mission="Cancelled project B",
        tenant_key=tenant_b,
        product_id=product_b.id,
        status="cancelled",
        completed_at=datetime.now(UTC),
        series_number=8104,
    )

    db_session.add_all([active_a, active_b, deleted_a, cancelled_b])
    await db_session.commit()

    for obj in [active_a, active_b, deleted_a, cancelled_b]:
        await db_session.refresh(obj)

    tenant_manager = TenantManager()
    service = ProjectService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "active_a": active_a,
        "active_b": active_b,
        "deleted_a": deleted_a,
        "cancelled_b": cancelled_b,
        "service": service,
        "tenant_manager": tenant_manager,
    }




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_restore_project_blocks_cross_tenant(db_session, two_tenant_projects):
    tenant_a = two_tenant_projects["tenant_a"]
    cancelled_b = two_tenant_projects["cancelled_b"]
    service = two_tenant_projects["service"]

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await service.deletion.restore_project(
            project_id=cancelled_b.id,
            tenant_key=tenant_a,
        )

    assert "not found" in exc_info.value.message.lower() or "access denied" in exc_info.value.message.lower()

    await db_session.refresh(cancelled_b)
    assert cancelled_b.status == "cancelled", "Cross-tenant restore modified another tenant's project!"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_restore_project_same_tenant_succeeds(db_session, two_tenant_projects):
    tenant_a = two_tenant_projects["tenant_a"]
    deleted_a = two_tenant_projects["deleted_a"]
    service = two_tenant_projects["service"]

    result = await service.deletion.restore_project(
        project_id=deleted_a.id,
        tenant_key=tenant_a,
    )

    assert "restored" in result.message.lower()

    await db_session.refresh(deleted_a)
    assert deleted_a.status == "inactive"
    assert deleted_a.deleted_at is None


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_restore_project_requires_tenant_key(db_session, two_tenant_projects):
    cancelled_b = two_tenant_projects["cancelled_b"]
    service = two_tenant_projects["service"]

    with pytest.raises(TypeError):
        await service.deletion.restore_project(project_id=cancelled_b.id)


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_with_project_type_blocks_cross_tenant_reload(db_session, two_tenant_projects):
    tenant_a = two_tenant_projects["tenant_a"]
    tenant_b = two_tenant_projects["tenant_b"]
    active_b = two_tenant_projects["active_b"]
    taxonomy_b = TaxonomyType(
        id=str(uuid.uuid4()),
        tenant_key=tenant_b,
        abbreviation="BE",
        label="Backend",
    )
    active_b.project_type_id = taxonomy_b.id
    db_session.add(taxonomy_b)
    await db_session.commit()

    repo = ProjectRepository()

    result = await repo.get_with_project_type(db_session, tenant_a, active_b.id)

    assert result is None


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_with_project_type_same_tenant_succeeds(db_session, two_tenant_projects):
    tenant_a = two_tenant_projects["tenant_a"]
    active_a = two_tenant_projects["active_a"]
    taxonomy_a = TaxonomyType(
        id=str(uuid.uuid4()),
        tenant_key=tenant_a,
        abbreviation="BE",
        label="Backend",
    )
    active_a.project_type_id = taxonomy_a.id
    db_session.add(taxonomy_a)
    await db_session.commit()

    repo = ProjectRepository()

    result = await repo.get_with_project_type(db_session, tenant_a, active_a.id)

    assert result is not None
    assert result.id == active_a.id
    assert result.project_type.abbreviation == "BE"




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_project_service_cross_tenant_audit(db_session, two_tenant_projects):
    tenant_a = two_tenant_projects["tenant_a"]
    active_b = two_tenant_projects["active_b"]
    cancelled_b = two_tenant_projects["cancelled_b"]
    service = two_tenant_projects["service"]

    violations = []

    try:
        await service.deletion.restore_project(project_id=cancelled_b.id, tenant_key=tenant_a)
        violations.append("restore_project() allowed cross-tenant restoration")
    except (ResourceNotFoundError, ValidationError):
        pass

    try:
        await service.get_project(project_id=active_b.id, tenant_key=tenant_a)
        violations.append("get_project() allowed cross-tenant access")
    except (ResourceNotFoundError, ValidationError):
        pass

    assert len(violations) == 0, "CRITICAL: Tenant isolation violated!\nViolations:\n" + "\n".join(
        f"- {v}" for v in violations
    )


def test_seeded_serials_are_deterministic_and_distinct():
    source = Path(__file__).read_text(encoding="utf-8")

    assert "series_number=" in source, "fixture no longer assigns series_number -- update this guard"

    assert re.search(r"series_number\s*=\s*random", source) is None, (
        "taxonomy serials must be deterministic literals: two seeded projects "
        "sharing a tenant and product fall in the same scope of "
        "uq_project_taxonomy_active, and independent random draws collide"
    )

    serials = re.findall(r"series_number=(\d+)", source)
    assert len(serials) == len(set(serials)), f"seeded serials must be distinct, got {serials}"
