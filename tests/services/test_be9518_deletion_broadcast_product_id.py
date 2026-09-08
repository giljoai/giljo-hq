# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9518 — ProjectDeletionService's project_update broadcasts must carry product_id.

Both deletion paths build their own inline ``project_data`` dict (they don't route
through ``project_helpers._build_ws_project_data``), so each needed its own one-line
fix and its own regression test:

- ``delete_project`` (soft delete): the project row is still attached post-commit,
  so ``project.product_id`` is read directly at the broadcast call site.
- ``nuclear_delete_project`` (hard delete): the row is gone from the DB by the time
  the broadcast fires, so ``product_id`` MUST be captured into a local BEFORE the
  delete + commit (mirrors the existing ``project_name`` capture) -- reading
  ``project.product_id`` after commit on a deleted row is exactly the kind of bug
  this test exists to catch.

DB-touching: ``db_session`` (TransactionalTestContext, rolled back). No module-level
mutable state, no ordering dependencies. Parallel-safe (pytest-xdist -n auto).
Edition Scope: CE.
"""

from __future__ import annotations

import random
import uuid
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_deletion_service import ProjectDeletionService


pytestmark = pytest.mark.asyncio


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_project_update = AsyncMock()
    return ws


def _deletion_svc(session: AsyncSession, tenant_key: str, websocket_manager=None) -> ProjectDeletionService:
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return ProjectDeletionService(
        db_manager=Mock(),
        tenant_manager=tenant_manager,
        test_session=session,
        websocket_manager=websocket_manager,
    )


async def _seed_project(session: AsyncSession, tenant_key: str, *, status: str = "inactive") -> tuple[str, str]:
    """Seed a project under its own product. Returns (project_id, product_id)."""
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9518 deletion product {uuid.uuid4().hex[:8]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    await session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9518 deletion broadcast regression",
        description="seeded",
        mission="seeded",
        status=status,
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.commit()
    return project.id, product.id


async def test_delete_project_broadcasts_product_id(db_session: AsyncSession) -> None:
    """Soft delete: project row is still attached, product_id read directly."""
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    project_id, product_id = await _seed_project(db_session, tenant_key)

    mock_ws = _mock_ws()
    svc = _deletion_svc(db_session, tenant_key, websocket_manager=mock_ws)

    await svc.delete_project(project_id)

    mock_ws.broadcast_project_update.assert_awaited_once()
    call_kwargs = mock_ws.broadcast_project_update.await_args.kwargs
    assert call_kwargs["project_data"]["product_id"] == product_id


async def test_nuclear_delete_project_broadcasts_product_id(db_session: AsyncSession) -> None:
    """Hard delete: the project row is GONE by broadcast time -- product_id must
    have been captured into a local before the delete, not read off the row after.
    """
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    project_id, product_id = await _seed_project(db_session, tenant_key, status="inactive")

    mock_ws = _mock_ws()
    svc = _deletion_svc(db_session, tenant_key)

    await svc.nuclear_delete_project(project_id, websocket_manager=mock_ws)

    mock_ws.broadcast_project_update.assert_awaited_once()
    call_kwargs = mock_ws.broadcast_project_update.await_args.kwargs
    assert call_kwargs["project_data"]["product_id"] == product_id
