# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9085b -- durable ``ever_launched_at`` signal on ProjectStagingService.

Regression at the FAILING layer (ProjectStagingService): the shipped BE-9085
closeout detector accepted a known false-positive because ``restage`` clears
``implementation_launched_at`` back to NULL, making a launched-then-restaged
project indistinguishable from a never-launched one at closeout time. This
adds ``ever_launched_at``: stamped once at launch (never overwritten by a
re-launch), left untouched by ``restage``, and cleared only by
``reset_to_prestage`` (the discard-everything rewind).

Covers:
1. launch_implementation stamps ever_launched_at once.
2. A second launch call (already_launched path) does not overwrite it.
3. restage leaves ever_launched_at untouched (the false-positive fix).
4. reset_to_prestage clears ever_launched_at (genuine rewind to birth).

DB-touching: uses the db_session fixture (TransactionalTestContext, rollback
at teardown). No module-level mutable state. No ordering dependencies.

Edition Scope: Both. projects/staging are CE-general; no saas/ import.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed_project(
    session: AsyncSession,
    tenant_key: str,
    *,
    staging_status: str | None,
    launched: bool = False,
    ever_launched: bool = False,
) -> str:
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
        name=f"BE-9085b {uuid.uuid4().hex[:6]}",
        description="ever_launched_at signal test project.",
        mission="Test.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=1,
        execution_mode="claude_code_cli",
        staging_status=staging_status,
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC) if launched else None,
        ever_launched_at=datetime.now(UTC) if ever_launched else None,
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_orchestrator(session: AsyncSession, tenant_key: str, project_id: str, *, status: str) -> None:
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        mission="orchestrator mission",
        job_type="orchestrator",
        status="active",
        created_at=datetime.now(UTC),
    )
    execution = AgentExecution(
        job_id=job_id,
        tenant_key=tenant_key,
        agent_id=str(uuid.uuid4()),
        agent_name="orchestrator-1",
        agent_display_name="orchestrator",
        status=status,
    )
    session.add(job)
    session.add(execution)
    await session.flush()


def _staging_svc(session: AsyncSession, tenant_key: str | None = None) -> ProjectStagingService:
    tenant_manager = TenantManager()
    if tenant_key is not None:
        # restage()/reset_to_prestage() resolve the tenant via
        # tenant_manager.get_current_tenant() (contextvar), unlike
        # launch_implementation() which accepts an explicit tenant_key kwarg.
        tenant_manager.set_current_tenant(tenant_key)
    return ProjectStagingService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=tenant_manager,
        test_session=session,
    )


def _lifecycle_svc(session: AsyncSession, tenant_key: str) -> ProjectLifecycleService:
    """restage() needs ProjectLifecycleService's OrchestratorFixtureMixin
    (_ensure_orchestrator_fixture) -- ProjectStagingService alone only has it
    if handed a lifecycle_service, which is exactly what the facade wires up."""
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)
    return ProjectLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=tenant_manager,
        test_session=session,
    )


async def test_launch_stamps_ever_launched_at_once(db_session: AsyncSession) -> None:
    """A first launch stamps both implementation_launched_at and ever_launched_at."""
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging_complete")

    svc = _staging_svc(db_session)
    await svc.launch_implementation(project_id=pid, tenant_key=tenant)

    refreshed = await db_session.get(Project, pid)
    assert refreshed.implementation_launched_at is not None
    assert refreshed.ever_launched_at is not None


async def test_relaunch_does_not_overwrite_ever_launched_at(db_session: AsyncSession) -> None:
    """A subsequent launch call must never overwrite the original ever_launched_at
    stamp -- it's a set-once, first-crossing signal."""
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging_complete")

    svc = _staging_svc(db_session)
    await svc.launch_implementation(project_id=pid, tenant_key=tenant)
    first = (await db_session.get(Project, pid)).ever_launched_at

    # Re-entrant call on an already-launched project (already_launched path).
    result = await svc.launch_implementation(project_id=pid, tenant_key=tenant)
    assert result["already_launched"] is True

    second = (await db_session.get(Project, pid)).ever_launched_at
    assert second == first, "ever_launched_at must be set-once, never overwritten by a re-launch"


async def test_restage_preserves_ever_launched_at(db_session: AsyncSession) -> None:
    """THE BE-9085 false-positive fix: restage clears implementation_launched_at
    but must leave ever_launched_at untouched."""
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(
        db_session,
        tenant,
        staging_status="staging",
        launched=True,
        ever_launched=True,
    )
    await _seed_orchestrator(db_session, tenant, pid, status="waiting")

    svc = _lifecycle_svc(db_session, tenant)
    await svc.restage(pid)

    refreshed = await db_session.get(Project, pid)
    assert refreshed.implementation_launched_at is None
    assert refreshed.ever_launched_at is not None, (
        "restage must not clear ever_launched_at -- this is the durable signal "
        "the BE-9085 detector relies on to suppress the restage false-positive"
    )


async def test_reset_to_prestage_clears_ever_launched_at(db_session: AsyncSession) -> None:
    """reset_to_prestage is a genuine rewind to birth -- unlike restage, it DOES
    clear ever_launched_at."""
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(
        db_session,
        tenant,
        staging_status="staging_complete",
        launched=True,
        ever_launched=True,
    )

    svc = _staging_svc(db_session)
    await svc.reset_to_prestage(pid, tenant_key=tenant)

    refreshed = await db_session.get(Project, pid)
    assert refreshed.implementation_launched_at is None
    assert refreshed.ever_launched_at is None, (
        "reset_to_prestage must clear ever_launched_at -- it's the discard-"
        "everything rewind to the project's original pre-stage birth state"
    )
