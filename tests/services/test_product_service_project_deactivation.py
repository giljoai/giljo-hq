# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.models import Product, Project
from giljo_mcp.services.product_service import ProductService
from tests.fixtures.base_fixtures import TestData


@pytest.mark.asyncio
async def test_activate_product_does_not_deactivate_projects_in_other_products(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()

    product_a = Product(
        id=str(uuid.uuid4()),
        name="Product A",
        description="First product",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product_a)
    await db_session.flush()

    project_x = Project(
        id=str(uuid.uuid4()),
        name="Project X",
        description="Active project in Product A",
        mission="Test mission",
        tenant_key=tenant_key,
        product_id=product_a.id,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_x)
    await db_session.commit()

    product_b = Product(
        id=str(uuid.uuid4()),
        name="Product B",
        description="Second product",
        tenant_key=tenant_key,
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product_b)
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)
    result = await service.activate_product(product_b.id)

    assert result.is_active is True

    await db_session.refresh(product_a)
    await db_session.refresh(product_b)
    await db_session.refresh(project_x)

    assert product_a.is_active is True
    assert project_x.status == "active", (
        f"Showing Product B must not touch Product A's project, but status is '{project_x.status}'"
    )


@pytest.mark.asyncio
async def test_activate_product_emits_no_bulk_deactivation_event(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()

    product_a = Product(
        id=str(uuid.uuid4()),
        name="Product A",
        description="First product",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product_a)
    await db_session.flush()

    project_1 = Project(
        id=str(uuid.uuid4()),
        name="Project 1",
        description="First project",
        mission="Test mission 1",
        tenant_key=tenant_key,
        product_id=product_a.id,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_1)
    await db_session.commit()

    product_b = Product(
        id=str(uuid.uuid4()),
        name="Product B",
        description="Second product",
        tenant_key=tenant_key,
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product_b)
    await db_session.commit()

    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()

    service = ProductService(
        db_manager,
        tenant_key=tenant_key,
        websocket_manager=mock_ws,
        test_session=db_session,
    )
    result = await service.activate_product(product_b.id)

    assert result.is_active is True
    mock_ws.broadcast_to_tenant.assert_not_called()


@pytest.mark.asyncio
async def test_product_switch_multi_tenant_isolation(db_session, db_manager):
    tenant_a = TestData.generate_tenant_key()
    tenant_b = TestData.generate_tenant_key()

    product_a = Product(
        id=str(uuid.uuid4()),
        name="Product A",
        tenant_key=tenant_a,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product_a)
    await db_session.flush()

    project_x_tenant_a = Project(
        id=str(uuid.uuid4()),
        name="Project X",
        description="Project in Tenant A",
        tenant_key=tenant_a,
        product_id=product_a.id,
        status="active",
        mission="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_x_tenant_a)

    product_b = Product(
        id=str(uuid.uuid4()),
        name="Product B",
        tenant_key=tenant_a,
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product_b)

    product_c = Product(
        id=str(uuid.uuid4()),
        name="Product C",
        tenant_key=tenant_b,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product_c)
    await db_session.flush()

    project_y_tenant_b = Project(
        id=str(uuid.uuid4()),
        name="Project Y",
        description="Project in Tenant B",
        tenant_key=tenant_b,
        product_id=product_c.id,
        status="active",
        mission="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_y_tenant_b)
    await db_session.commit()

    service_a = ProductService(db_manager, tenant_key=tenant_a, test_session=db_session)
    result = await service_a.activate_product(product_b.id)
    assert result.is_active is True

    await db_session.refresh(project_x_tenant_a)
    await db_session.refresh(project_y_tenant_b)

    assert project_x_tenant_a.status == "active"
    assert project_y_tenant_b.status == "active"
