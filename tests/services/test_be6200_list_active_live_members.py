# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_MODE = "claude_code_cli"


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        await session.commit()


def _seq_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=None, session=session)


async def _create_project(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    status: str = "active",
    deleted_at: datetime | None = None,
) -> None:
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=project_id,
        name="Live-member Test Project",
        description="BE-6200 list_active live-member filter",
        mission="BE-6200 regression mission",
        status=status,
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        deleted_at=deleted_at,
    )
    session.add(project)
    await session.commit()


async def _create_run(
    session: AsyncSession,
    tenant_key: str,
    project_ids: list[str],
    *,
    status: str = "pending",
    project_statuses: dict | None = None,
) -> dict:
    return await _seq_svc(session).create(
        project_ids=project_ids,
        resolved_order=project_ids,
        execution_mode=_MODE,
        status=status,
        project_statuses=project_statuses if project_statuses is not None else dict.fromkeys(project_ids, "pending"),
        tenant_key=tenant_key,
    )


async def test_all_terminal_members_excluded_even_when_status_pending_and_statuses_stale(
    db_session: AsyncSession,
) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = str(uuid.uuid4())
    p2 = str(uuid.uuid4())
    await _create_project(db_session, tenant, p1, status="completed")
    await _create_project(db_session, tenant, p2, status="terminated")
    run = await _create_run(db_session, tenant, [p1, p2], status="pending", project_statuses={})

    active = await _seq_svc(db_session).list_active(tenant_key=tenant)
    assert run["id"] not in {r["id"] for r in active}, "all-terminal run must not surface as active"


async def test_run_with_one_live_member_still_returned(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    live = str(uuid.uuid4())
    done = str(uuid.uuid4())
    await _create_project(db_session, tenant, live, status="active")
    await _create_project(db_session, tenant, done, status="completed")
    run = await _create_run(db_session, tenant, [live, done], status="pending")

    active = await _seq_svc(db_session).list_active(tenant_key=tenant)
    assert run["id"] in {r["id"] for r in active}, "run with a live member must remain active"


async def test_soft_deleted_member_counts_as_terminal(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = str(uuid.uuid4())
    p2 = str(uuid.uuid4())
    await _create_project(db_session, tenant, p1, status="active", deleted_at=datetime.now(UTC))
    await _create_project(db_session, tenant, p2, status="cancelled")
    run = await _create_run(db_session, tenant, [p1, p2], status="pending")

    active = await _seq_svc(db_session).list_active(tenant_key=tenant)
    assert run["id"] not in {r["id"] for r in active}, "soft-deleted member must count as terminal"


async def test_missing_member_rows_count_as_terminal(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _create_run(db_session, tenant, [str(uuid.uuid4()), str(uuid.uuid4())], status="pending")

    active = await _seq_svc(db_session).list_active(tenant_key=tenant)
    assert run["id"] not in {r["id"] for r in active}, "run with no live member rows must not surface"
