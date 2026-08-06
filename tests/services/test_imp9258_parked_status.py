# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""IMP-9258 -- ``parked`` project status: set a project aside without cancelling.

Coverage:
  * ``ProjectService.update_project`` parks a project (status='parked') and
    persists it -- through the SAME generic write path cancel/complete use,
    no parallel write path.
  * UNPARK: a parked project can be restored to active/inactive via the same
    generic ``update_project`` -- two-sided, mirroring cancel's dedicated
    restore endpoint but WITHOUT needing one (parked is not immutable).
  * A COMPLETED (immutable) project cannot be parked -- source-state
    validation is inherited for free from the existing IMMUTABLE_PROJECT_STATUSES
    guard, matching cancel's own immutability contract.
  * ``parked`` is NOT ``cancelled`` -- distinct status values, distinct
    membership in the derived sets (see also
    tests/unit/domain/test_project_status_enum.py).

Parallel-safe: fresh tenant_key per test; DB-backed tests use the rolled-back
db_session (TransactionalTestContext); no module-level mutable state.
"""

from __future__ import annotations

import random
import uuid

import pytest
import pytest_asyncio

from giljo_mcp.domain.project_status import (
    IMMUTABLE_PROJECT_STATUSES,
    LIFECYCLE_FINISHED_STATUSES,
    ProjectStatus,
)
from giljo_mcp.exceptions import ProjectStateError


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def parked_setup(db_manager, db_session):
    """One committed-in-transaction project under a fresh tenant, plus a
    ProjectService bound to the rolled-back session with tenant context set."""
    from giljo_mcp.models.products import Product
    from giljo_mcp.models.projects import Project
    from giljo_mcp.services.project_service import ProjectService
    from giljo_mcp.tenant import TenantManager, current_tenant

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid.uuid4().hex[:8]

    product = Product(
        id=f"imp9258-prod-{suffix}",
        name=f"IMP-9258 Product {suffix}",
        description="IMP-9258",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=f"imp9258-proj-{suffix}",
        tenant_key=tenant_key,
        product_id=product.id,
        name="Parkable Project",
        description="d",
        mission="m",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    manager = TenantManager()
    manager.set_current_tenant(tenant_key)
    token = current_tenant.set(tenant_key)
    svc = ProjectService(db_manager=db_manager, tenant_manager=manager, test_session=db_session)
    try:
        yield svc, project, tenant_key
    finally:
        current_tenant.reset(token)


async def test_update_project_parks_an_active_project(parked_setup):
    svc, project, _tk = parked_setup

    result = await svc.update_project(project_id=project.id, updates={"status": "parked"})

    assert result.status == ProjectStatus.PARKED


async def test_parked_project_can_be_unparked_to_active(parked_setup):
    """Two-sided: park, then unpark straight back to active via the SAME
    generic update_project path -- no dedicated restore endpoint required
    (parked is not immutable, unlike cancelled)."""
    svc, project, _tk = parked_setup

    await svc.update_project(project_id=project.id, updates={"status": "parked"})
    result = await svc.update_project(project_id=project.id, updates={"status": "active"})

    assert result.status == ProjectStatus.ACTIVE


async def test_parked_project_can_be_unparked_to_inactive(parked_setup):
    svc, project, _tk = parked_setup

    await svc.update_project(project_id=project.id, updates={"status": "parked"})
    result = await svc.update_project(project_id=project.id, updates={"status": "inactive"})

    assert result.status == ProjectStatus.INACTIVE


async def test_parked_project_still_mutable_for_other_fields(parked_setup):
    """A parked project is NOT immutable -- ordinary metadata edits (e.g. name)
    keep working while parked, unlike a cancelled/completed project."""
    svc, project, _tk = parked_setup

    await svc.update_project(project_id=project.id, updates={"status": "parked"})
    result = await svc.update_project(project_id=project.id, updates={"name": "Renamed while parked"})

    assert result.name == "Renamed while parked"
    assert result.status == ProjectStatus.PARKED


async def test_completed_project_cannot_be_parked(parked_setup):
    """Source-state validation: an immutable (completed) project rejects the
    park transition -- inherited for free from the existing
    IMMUTABLE_PROJECT_STATUSES guard, matching cancel's own contract (you
    cannot cancel-or-park already-shipped work)."""
    svc, project, _tk = parked_setup
    project.status = ProjectStatus.COMPLETED
    await svc._test_session.flush()

    with pytest.raises(ProjectStateError):
        await svc.update_project(project_id=project.id, updates={"status": "parked"})


async def test_parked_is_not_cancelled() -> None:
    """Distinct status values -- parking a project must never be confused with
    (or silently coerced into) cancelling it."""

    assert ProjectStatus.PARKED != ProjectStatus.CANCELLED
    assert ProjectStatus.PARKED.value != ProjectStatus.CANCELLED.value


async def test_parked_is_resumable_not_lifecycle_finished_or_immutable() -> None:
    """Unlike cancelled, parked is a two-way door: resumable (not
    lifecycle-finished) and not immutable."""

    assert ProjectStatus.PARKED not in LIFECYCLE_FINISHED_STATUSES
    assert ProjectStatus.PARKED not in IMMUTABLE_PROJECT_STATUSES
    # Cancelled, for contrast, is both.
    assert ProjectStatus.CANCELLED in LIFECYCLE_FINISHED_STATUSES
    assert ProjectStatus.CANCELLED in IMMUTABLE_PROJECT_STATUSES
