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
from giljo_mcp.schemas.responses.orchestration import WorkflowStatus
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
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
        name=f"BE-6188 {uuid.uuid4().hex[:6]}",
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


def _staging_svc(session: AsyncSession) -> ProjectStagingService:
    return ProjectStagingService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


def _workflow_svc(session: AsyncSession) -> WorkflowStatusService:
    return WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=session)




@pytest.mark.asyncio
async def test_advance_blocked_without_closeout(db_session: AsyncSession) -> None:
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

    await _staging_svc(db_session)._advance_chain_on_launch(p2, tenant)

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p2, tenant_key=tenant)
    assert refreshed["current_index"] == 0, "advance must be BLOCKED while p1 has no closeout"
    assert refreshed["project_statuses"].get(p2) == "planning", (
        "the per-project status update applies even when the advance is blocked"
    )




@pytest.mark.asyncio
async def test_advance_succeeds_with_closeout(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, closed_out=True)
    p2 = await _seed_project(db_session, tenant)

    await _run_svc(db_session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
        current_index=0,
    )

    await _staging_svc(db_session)._advance_chain_on_launch(p2, tenant)

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p2, tenant_key=tenant)
    assert refreshed["current_index"] == 1, "advance must succeed once p1 has closed out"
    assert refreshed["project_statuses"].get(p2) == "planning"




def test_workflow_status_includes_closeout_at() -> None:
    iso = "2026-01-01T00:00:00+00:00"
    ws = WorkflowStatus(project_closeout_at=iso)
    assert ws.project_closeout_at == iso
    assert ws.model_dump()["project_closeout_at"] == iso




def test_workflow_status_closeout_at_none_for_solo() -> None:
    ws = WorkflowStatus()
    assert ws.project_closeout_at is None




@pytest.mark.asyncio
async def test_workflow_status_service_returns_closeout_at(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, closed_out=True)

    result = await _workflow_svc(db_session).get_workflow_status(pid, tenant)

    assert result.project_closeout_at is not None, "a closed-out project must surface its closeout timestamp"
