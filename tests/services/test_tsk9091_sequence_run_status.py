# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.services.project_helpers import advance_chain_member_to_implementing
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


async def _seed_project(session: AsyncSession, tenant_key: str, *, closed_out: bool = False) -> str:
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"TSK-9091 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
        closeout_executed_at=datetime.now(UTC) if closed_out else None,
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


@pytest.mark.asyncio
async def test_head_project_entering_implementation_flips_run_to_running(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    run = await _run_svc(db_session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    assert run["status"] == "pending"

    advanced = await advance_chain_member_to_implementing(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        session=db_session,
    )
    assert advanced is True

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["status"] == "running", "run must leave 'pending' once its head member starts implementing"


@pytest.mark.asyncio
async def test_downstream_member_flips_run_to_running_even_when_advance_blocked(
    db_session: AsyncSession,
) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, closed_out=False)
    p2 = await _seed_project(db_session, tenant)

    await _run_svc(db_session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
        current_index=0,
    )

    advanced = await advance_chain_member_to_implementing(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p2,
        tenant_key=tenant,
        session=db_session,
    )
    assert advanced is False, "index must stay held while p1 has no closeout"

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p2, tenant_key=tenant)
    assert refreshed["current_index"] == 0
    assert refreshed["status"] == "running", "status must flip even when the index advance is held"


@pytest.mark.asyncio
async def test_stalled_run_resumes_to_running_on_member_advance(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)

    run = await _run_svc(db_session).create(
        project_ids=[p1],
        resolved_order=[p1],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    await _run_svc(db_session).update(run_id=run["id"], tenant_key=tenant, status="stalled")

    advanced = await advance_chain_member_to_implementing(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        session=db_session,
    )
    assert advanced is True

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["status"] == "running"


@pytest.mark.asyncio
async def test_active_run_filters_still_include_running(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)

    run = await _run_svc(db_session).create(
        project_ids=[p1],
        resolved_order=[p1],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    conductor_agent_id = run["conductor_agent_id"]

    await advance_chain_member_to_implementing(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        session=db_session,
    )

    svc = _run_svc(db_session)
    assert (await svc.find_active_run_for_project(project_id=p1, tenant_key=tenant))["status"] == "running"
    assert (
        await svc.find_active_run_for_conductor(conductor_agent_id=conductor_agent_id, tenant_key=tenant)
    ) is not None
    active = await svc.list_active(tenant_key=tenant)
    assert any(r["id"] == run["id"] for r in active), "a running chain must not drop out of list_active"
