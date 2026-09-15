# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.sequence_run_live_filter import filter_runs_with_live_members
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _project(session: AsyncSession, tenant: str, pid: str, *, status: str, deleted_at=None) -> None:
    _product_id = str(uuid.uuid4())
    session.add(
        Product(
            id=_product_id,
            tenant_key=tenant,
            name=f"Owning Product {_product_id[:8]}",
            description="seeded",
            is_active=False,
        )
    )
    session.add(
        Project(
            id=pid,
            product_id=_product_id,
            name="filter-test",
            description="BE-6200 live filter",
            mission="m",
            status=status,
            tenant_key=tenant,
            execution_mode="multi_terminal",
            series_number=random.randint(1, 9000),
            deleted_at=deleted_at,
        )
    )
    await session.commit()


def _run(pids: list[str]):
    return SimpleNamespace(id=str(uuid.uuid4()), resolved_order=pids, project_ids=pids)


async def test_keeps_run_with_a_live_member_drops_all_terminal(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    live, done, gone = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _project(db_session, tenant, live, status="active")
    await _project(db_session, tenant, done, status="completed")

    kept = _run([live, done])
    dropped_terminal = _run([done])
    dropped_missing = _run([gone])

    result = await filter_runs_with_live_members(
        session=db_session, runs=[kept, dropped_terminal, dropped_missing], tenant_key=tenant
    )
    ids = {r.id for r in result}
    assert kept.id in ids
    assert dropped_terminal.id not in ids
    assert dropped_missing.id not in ids


async def test_soft_deleted_member_is_terminal(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = str(uuid.uuid4())
    await _project(db_session, tenant, pid, status="active", deleted_at=datetime.now(UTC))

    result = await filter_runs_with_live_members(session=db_session, runs=[_run([pid])], tenant_key=tenant)
    assert result == []


async def test_empty_runs_returns_empty(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    result = await filter_runs_with_live_members(session=db_session, runs=[], tenant_key=tenant)
    assert result == []
