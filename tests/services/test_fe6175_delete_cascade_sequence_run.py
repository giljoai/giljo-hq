# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from unittest.mock import Mock

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.project_deletion_service import ProjectDeletionService
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


def _deletion_svc(session: AsyncSession, tenant_key: str) -> ProjectDeletionService:
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return ProjectDeletionService(
        db_manager=Mock(),
        tenant_manager=tenant_manager,
        test_session=session,
    )


async def _create_project(session: AsyncSession, tenant_key: str, project_id: str, *, status: str = "inactive") -> None:
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
        name="Cascade Test Project",
        description="Delete-cascade regression",
        mission="Delete-cascade regression mission",
        status=status,
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.commit()


async def _create_run(
    session: AsyncSession, tenant_key: str, project_ids: list[str], *, status: str = "pending"
) -> dict:
    return await _seq_svc(session).create(
        project_ids=project_ids,
        resolved_order=project_ids,
        execution_mode=_MODE,
        status=status,
        project_statuses=dict.fromkeys(project_ids, "pending"),
        tenant_key=tenant_key,
    )


async def test_delete_member_of_pending_run_dissolves_it(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    member_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    await _create_project(db_session, tenant, member_id)
    run = await _create_run(db_session, tenant, [member_id, other_id], status="pending")

    before = await _seq_svc(db_session).list_active(tenant_key=tenant)
    assert run["id"] in {r["id"] for r in before}

    await _deletion_svc(db_session, tenant).delete_project(member_id)

    after = await _seq_svc(db_session).list_active(tenant_key=tenant)
    assert run["id"] not in {r["id"] for r in after}, "deleted member's run must not remain in list_active"


async def test_delete_member_of_running_run_cancels_it(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    member_id = str(uuid.uuid4())
    p2 = str(uuid.uuid4())
    p3 = str(uuid.uuid4())
    await _create_project(db_session, tenant, member_id)
    await _create_project(db_session, tenant, p2, status="active")
    await _create_project(db_session, tenant, p3, status="active")
    run = await _create_run(db_session, tenant, [member_id, p2, p3], status="running")

    await _deletion_svc(db_session, tenant).delete_project(member_id)

    active = await _seq_svc(db_session).list_active(tenant_key=tenant)
    assert run["id"] not in {r["id"] for r in active}
    row = await _seq_svc(db_session).get(run_id=run["id"], tenant_key=tenant)
    assert row["status"] == "cancelled"


async def test_delete_non_member_leaves_runs_untouched(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    lone_id = str(uuid.uuid4())
    await _create_project(db_session, tenant, lone_id)
    other_a = str(uuid.uuid4())
    other_b = str(uuid.uuid4())
    await _create_project(db_session, tenant, other_a, status="active")
    await _create_project(db_session, tenant, other_b, status="active")
    run = await _create_run(db_session, tenant, [other_a, other_b], status="pending")

    await _deletion_svc(db_session, tenant).delete_project(lone_id)

    active = await _seq_svc(db_session).list_active(tenant_key=tenant)
    assert run["id"] in {r["id"] for r in active}, "unrelated run must be byte-identical (untouched)"
