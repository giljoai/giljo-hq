# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ImplementationNotReadyError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


async def _seed_project(
    session: AsyncSession,
    tenant_key: str,
    *,
    staging_status: str | None,
    launched: bool = False,
    closed_out: bool = False,
) -> str:
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
        name=f"BE-6181 {uuid.uuid4().hex[:6]}",
        description="Launch-gate test project.",
        mission="Launch test.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        staging_status=staging_status,
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC) if launched else None,
        closeout_executed_at=datetime.now(UTC) if closed_out else None,
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_run(
    session: AsyncSession,
    tenant_key: str,
    *,
    resolved_order: list[str],
    current_index: int = 0,
    project_statuses: dict[str, str] | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    run = SequenceRun(
        id=run_id,
        tenant_key=tenant_key,
        project_ids=resolved_order,
        resolved_order=resolved_order,
        current_index=current_index,
        execution_mode="claude_code_cli",
        status="running",
        review_policy="per_card",
        project_statuses=project_statuses or {},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    return run_id


def _staging_svc(session: AsyncSession) -> ProjectStagingService:
    return ProjectStagingService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=session,
    )




async def test_launch_refuses_when_staging_not_complete(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging")

    svc = _staging_svc(db_session)
    with pytest.raises(ImplementationNotReadyError) as exc:
        await svc.launch_implementation(project_id=pid, tenant_key=tenant)

    assert exc.value.reason == "staging_incomplete"

    refreshed = await db_session.get(Project, pid)
    assert refreshed.implementation_launched_at is None


async def test_launch_succeeds_when_staging_complete(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging_complete")

    svc = _staging_svc(db_session)
    result = await svc.launch_implementation(project_id=pid, tenant_key=tenant)

    assert result["success"] is True
    assert result["already_launched"] is False
    refreshed = await db_session.get(Project, pid)
    assert refreshed.implementation_launched_at is not None


async def test_relaunch_skips_guard_and_is_idempotent(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging", launched=True)

    svc = _staging_svc(db_session)
    result = await svc.launch_implementation(project_id=pid, tenant_key=tenant)

    assert result["already_launched"] is True




async def test_launch_advances_chain_member_forward(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p0 = await _seed_project(db_session, tenant, staging_status="staging_complete", closed_out=True)
    p1 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    run_id = await _seed_run(
        db_session,
        tenant,
        resolved_order=[p0, p1],
        current_index=0,
        project_statuses={p0: "completed"},
    )

    svc = _staging_svc(db_session)
    await svc.launch_implementation(project_id=p1, tenant_key=tenant)

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 1
    assert run["project_statuses"][p1] == "planning"
    assert run["project_statuses"][p0] == "completed"


async def test_launch_refused_without_prior_closeout(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p0 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    p1 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    run_id = await _seed_run(
        db_session,
        tenant,
        resolved_order=[p0, p1],
        current_index=0,
    )

    svc = _staging_svc(db_session)
    with pytest.raises(ImplementationNotReadyError) as exc_info:
        await svc.launch_implementation(project_id=p1, tenant_key=tenant)
    assert exc_info.value.reason == "chain_predecessor_open"
    assert exc_info.value.context["predecessor_project_id"] == p0

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 0


async def test_launch_advance_is_forward_only(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p0 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    p1 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    run_id = await _seed_run(
        db_session,
        tenant,
        resolved_order=[p0, p1],
        current_index=1,
    )

    svc = _staging_svc(db_session)
    await svc.launch_implementation(project_id=p0, tenant_key=tenant)

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 1
    assert run["project_statuses"][p0] == "planning"


async def test_solo_launch_leaves_no_run_trace(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging_complete")

    svc = _staging_svc(db_session)
    result = await svc.launch_implementation(project_id=pid, tenant_key=tenant)

    assert result["success"] is True
    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    assert await run_svc.find_active_run_for_project(project_id=pid, tenant_key=tenant) is None
