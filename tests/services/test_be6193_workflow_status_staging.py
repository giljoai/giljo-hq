# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6193: WorkflowStatus.staging_status — additive read-through field.

The chain orchestrator's drive loop needs to detect when a spawned sub-orch
reached "staging_complete". get_workflow_status already exposes project_closeout_at
(BE-6188); this mirrors that pattern for staging_status.

1. test_workflow_status_has_staging_status_field (unit)
   WorkflowStatus carries staging_status when supplied; defaults None for solo.

2. test_workflow_status_service_surfaces_staging_status (DB-touching)
   get_workflow_status populates staging_status from the loaded project.

Parallel-safe: DB-touching tests use db_session (TransactionalTestContext). No
module-level mutable state. Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.schemas.responses.orchestration import WorkflowStatus
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager


async def _seed_project(session: AsyncSession, tenant_key: str, *, staging_status: str | None = None) -> str:
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
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
        name=f"BE-6193 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=1,
        execution_mode="claude_code_cli",
        staging_status=staging_status,
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def _workflow_svc(session: AsyncSession) -> WorkflowStatusService:
    return WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


# ---------------------------------------------------------------------------
# 1. WorkflowStatus carries staging_status; defaults None for solo
# ---------------------------------------------------------------------------


def test_workflow_status_has_staging_status_field() -> None:
    ws = WorkflowStatus(staging_status="staging_complete")
    assert ws.staging_status == "staging_complete"
    assert ws.model_dump()["staging_status"] == "staging_complete"

    assert WorkflowStatus().staging_status is None


# ---------------------------------------------------------------------------
# 2. get_workflow_status surfaces the project's staging_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_status_service_surfaces_staging_status(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging_complete")

    result = await _workflow_svc(db_session).get_workflow_status(pid, tenant)

    assert result.staging_status == "staging_complete"
