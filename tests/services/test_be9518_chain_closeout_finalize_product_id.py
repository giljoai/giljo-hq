# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools._closeout_finalize import _finalize_chain_member_closeout


pytestmark = pytest.mark.asyncio


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_project_update = AsyncMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    ws.broadcast_to_tenant = AsyncMock()
    return ws


async def _seed_chain_member(session: AsyncSession, tenant_key: str) -> tuple[Project, str]:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9518 chain closeout product {uuid.uuid4().hex[:8]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    await session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9518 chain closeout regression",
        description="seeded",
        mission="seeded",
        status="active",
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()

    run = SequenceRun(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_ids=[project.id],
        resolved_order=[project.id],
        project_statuses={project.id: "implementing"},
        status="running",
        current_index=0,
        execution_mode="claude_code_cli",
        review_policy="per_card",
        created_at=datetime.now(UTC),
    )
    session.add(run)
    await session.commit()
    return project, product.id


async def test_finalize_chain_member_closeout_broadcasts_product_id(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    project, product_id = await _seed_chain_member(db_session, tenant_key)

    mock_ws = _mock_ws()
    _ws, is_chain_member = await _finalize_chain_member_closeout(
        session=db_session,
        project=project,
        project_id=project.id,
        tenant_key=tenant_key,
        db_manager=None,
        websocket_manager=mock_ws,
    )

    assert is_chain_member is True, "fixture must actually be a chain member for this to prove anything"
    mock_ws.broadcast_project_update.assert_awaited_once()
    call_kwargs = mock_ws.broadcast_project_update.await_args.kwargs
    assert call_kwargs["project_data"]["product_id"] == product_id
