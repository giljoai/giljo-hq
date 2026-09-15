# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.models import Project
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.schemas.service_responses import NuclearDeleteResult


@pytest.mark.asyncio
async def test_nuclear_delete_marks_memory_entries_in_table(
    db_session, test_tenant_key, test_product, project_service_with_session
):
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="Test Project for Memory Delete",
        description="Test project for memory table delete",
        mission="Test mission for project deletion",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)

    entries = []
    for i in range(3):
        entry = ProductMemoryEntry(
            tenant_key=test_tenant_key,
            product_id=test_product.id,
            project_id=project.id,
            sequence=i + 1,
            entry_type="project_closeout",
            source="test",
            timestamp=datetime.now(UTC),
            project_name=project.name,
            summary=f"Test entry {i + 1}",
            deleted_by_user=False,
        )
        db_session.add(entry)
        entries.append(entry)

    await db_session.commit()
    await db_session.refresh(project)
    for entry in entries:
        await db_session.refresh(entry)

    entry_ids = [entry.id for entry in entries]

    result = await project_service_with_session.deletion.nuclear_delete_project(
        project_id=project.id, websocket_manager=None
    )

    assert isinstance(result, NuclearDeleteResult)
    assert result.message
    assert result.deleted_counts["memory_entries_marked"] == 3

    await db_session.commit()
    from sqlalchemy import select

    stmt = select(ProductMemoryEntry).where(ProductMemoryEntry.id.in_(entry_ids))
    query_result = await db_session.execute(stmt)
    marked_entries = query_result.scalars().all()

    assert len(marked_entries) == 3
    for entry in marked_entries:
        assert entry.deleted_by_user is True
        assert entry.user_deleted_at is not None


@pytest.mark.asyncio
async def test_nuclear_delete_with_no_memory_entries(
    db_session, test_tenant_key, test_product, project_service_with_session
):
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="Test Project No Memory",
        description="Test project without memory entries",
        mission="Test mission without memory",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    result = await project_service_with_session.deletion.nuclear_delete_project(
        project_id=project.id, websocket_manager=None
    )

    assert isinstance(result, NuclearDeleteResult)
    assert result.deleted_counts["memory_entries_marked"] == 0


@pytest.mark.asyncio
async def test_nuclear_delete_tenant_isolation(db_session, test_tenant_key, test_product, project_service_with_session):
    project1 = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="Tenant 1 Project",
        description="Project for testing tenant isolation",
        mission="Test mission for tenant isolation",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project1)

    entry1 = ProductMemoryEntry(
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        project_id=project1.id,
        sequence=1,
        entry_type="project_closeout",
        source="test",
        timestamp=datetime.now(UTC),
        project_name=project1.name,
        summary="Tenant 1 entry",
        deleted_by_user=False,
    )
    db_session.add(entry1)

    await db_session.commit()

    result = await project_service_with_session.deletion.nuclear_delete_project(
        project_id=project1.id, websocket_manager=None
    )

    assert isinstance(result, NuclearDeleteResult)
    assert result.deleted_counts["memory_entries_marked"] == 1
