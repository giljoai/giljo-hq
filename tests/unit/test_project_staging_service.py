# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for ProjectStagingService (Sprint 002e extraction).

Previously only the guard/not-found error paths were covered, so the actual
state mutations performed by restage/unstage/cancel_staging were untested. These
seed real projects and assert the resulting state transitions. restage's success
path calls lifecycle._ensure_orchestrator_fixture, so that test injects a stub
lifecycle service (the default fixture leaves it None).
"""

import random
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ProjectStateError, ResourceNotFoundError
from giljo_mcp.models import Product, Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.project_staging_service import ProjectStagingService


@pytest.fixture
def staging_service(db_session, test_tenant_key):
    """Create a ProjectStagingService with a test session (no lifecycle service)."""
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return ProjectStagingService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_project(session, tenant_key, *, staging_status=None, status=ProjectStatus.INACTIVE):
    """Seed a project under a product of its OWN.

    BE-9437 made ``product_id`` NOT NULL, so the old note here -- "product_id
    NULL to avoid the single-active-per-product index" -- describes a state that
    no longer exists. Giving each seeded project a fresh product achieves the
    same thing honestly: ``idx_project_single_active_per_product`` allows one
    active project PER PRODUCT, so one product per project can never collide,
    however many a test seeds.
    """
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Staging Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    await session.flush()

    project = Project(
        tenant_key=tenant_key,
        product_id=product.id,
        name="Staging Project",
        description="seeded",
        mission="seeded mission",
        status=status,
        staging_status=staging_status,
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()
    return project


# ---- check_staging_allowed (pure, retained) ----


def test_check_staging_allowed_raises_when_staging():
    """check_staging_allowed raises ProjectStateError when staging_status is 'staging'."""
    project = MagicMock()
    project.staging_status = "staging"
    project.id = "test-id"

    service = ProjectStagingService(MagicMock(), MagicMock())
    with pytest.raises(ProjectStateError):
        service.check_staging_allowed(project)


def test_check_staging_allowed_passes_when_not_staging():
    """check_staging_allowed does not raise when staging_status is None."""
    project = MagicMock()
    project.staging_status = None
    project.id = "test-id"

    service = ProjectStagingService(MagicMock(), MagicMock())
    service.check_staging_allowed(project)


# ---- not-found paths (retained) ----


@pytest.mark.asyncio
async def test_restage_raises_for_missing_project(staging_service, test_tenant_key):
    """restage raises ResourceNotFoundError for non-existent project."""
    with pytest.raises(ResourceNotFoundError):
        await staging_service.restage("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_unstage_raises_for_missing_project(staging_service, test_tenant_key):
    """unstage raises ResourceNotFoundError for non-existent project."""
    with pytest.raises(ResourceNotFoundError):
        await staging_service.unstage("00000000-0000-0000-0000-000000000000")


# ---- restage success + guard ----


@pytest.mark.asyncio
async def test_restage_success_resets_state(db_session, test_tenant_key):
    """restage clears staging_status + mission, preserves the chosen execution_mode,
    clears impl-launched, and builds a fresh orchestrator.

    BE-6047: restage no longer force-resets execution_mode to 'multi_terminal'
    (that was the lock trap — a user who staged in 'claude_code_cli' had their
    mode silently flipped). It now preserves the project's chosen mode and
    clears mission (releasing the Handover-0343 execution_mode lock).
    The CE-0032 'staging' + impl_launched_at success path is unchanged.
    """
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    lifecycle = MagicMock()
    lifecycle._ensure_orchestrator_fixture = AsyncMock(return_value={"job_id": "J", "agent_id": "A"})
    service = ProjectStagingService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
        lifecycle_service=lifecycle,
    )

    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staging")
        project.execution_mode = "claude_code_cli"  # non-default chosen mode must survive
        project.implementation_launched_at = datetime.now(UTC)  # should be cleared by restage (CE-0032)
        await db_session.flush()

    result = await service.restage(str(project.id))

    assert result["message"] == "Project restaged successfully"
    assert result["new_orchestrator"] == {"job_id": "J", "agent_id": "A"}
    assert project.staging_status is None
    assert project.execution_mode == "claude_code_cli"  # BE-6047: chosen mode preserved, not forced
    assert project.mission == ""  # BE-6047: mission cleared ("" — projects.mission is NOT NULL), lock released
    assert project.implementation_launched_at is None
    lifecycle._ensure_orchestrator_fixture.assert_awaited_once()


@pytest.mark.asyncio
async def test_restage_raises_when_not_staged(staging_service, db_session, test_tenant_key):
    """restage rejects a project whose staging_status is neither 'staging' nor 'staging_complete'."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status=None)

    with pytest.raises(ProjectStateError):
        await staging_service.restage(str(project.id))


@pytest.mark.asyncio
async def test_restage_from_staging_complete_succeeds(db_session, test_tenant_key):
    """BE-6047: restage recovers a project from 'staging_complete' (handoff window,
    implementation not yet launched) — rebuilds the orchestrator fixture and clears mission.
    """
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    lifecycle = MagicMock()
    lifecycle._ensure_orchestrator_fixture = AsyncMock(return_value={"job_id": "J2", "agent_id": "A2"})
    service = ProjectStagingService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
        lifecycle_service=lifecycle,
    )

    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staging_complete")
        project.execution_mode = "claude_code_cli"
        await db_session.flush()

    result = await service.restage(str(project.id))

    assert result["message"] == "Project restaged successfully"
    assert project.staging_status is None
    assert project.mission == ""
    assert project.execution_mode == "claude_code_cli"
    lifecycle._ensure_orchestrator_fixture.assert_awaited_once()


@pytest.mark.asyncio
async def test_restage_blocked_when_implementation_launched(db_session, test_tenant_key):
    """BE-6047: recovery from 'staging_complete' is rejected once implementation
    has been launched (implementation_launched_at set) — restaging then would
    strand already-spawned implementation jobs.
    """
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    lifecycle = MagicMock()
    lifecycle._ensure_orchestrator_fixture = AsyncMock(return_value={"job_id": "J3", "agent_id": "A3"})
    service = ProjectStagingService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
        lifecycle_service=lifecycle,
    )

    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staging_complete")
        project.implementation_launched_at = datetime.now(UTC)
        await db_session.flush()

    with pytest.raises(ProjectStateError):
        await service.restage(str(project.id))

    lifecycle._ensure_orchestrator_fixture.assert_not_awaited()


# ---- unstage success + guard ----


@pytest.mark.asyncio
async def test_unstage_success_clears_staging_status_and_mission(staging_service, db_session, test_tenant_key):
    """unstage clears staging_status from 'staged' back to None AND clears mission.

    BE-6047: clearing mission is THE central unlock. The Handover-0343 lock in
    ProjectService._apply_project_updates keys on a truthy project.mission, so
    while a mission lingers the user cannot change execution_mode. After unstage
    the lock must be released.
    """
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staged")

    assert project.mission  # precondition: lock is currently active

    result = await staging_service.unstage(str(project.id))

    assert result["message"] == "Project unstaged successfully"
    assert project.staging_status is None
    assert project.mission == ""  # BE-6047: mission cleared ("" — projects.mission is NOT NULL)

    # Lock released: changing execution_mode must no longer raise.
    project_service = ProjectService(MagicMock(), MagicMock())
    project_service._apply_project_updates(project, {"execution_mode": "claude_code_cli"})
    assert project.execution_mode == "claude_code_cli"


@pytest.mark.asyncio
async def test_unstage_raises_when_not_in_staged_state(staging_service, db_session, test_tenant_key):
    """unstage rejects a project that is in 'staging' (not 'staged')."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status="staging")

    with pytest.raises(ProjectStateError):
        await staging_service.unstage(str(project.id))


# ---- cancel_staging success + guard ----


@pytest.mark.asyncio
async def test_cancel_staging_success_sets_cancelled(staging_service, db_session, test_tenant_key):
    """cancel_staging transitions an inactive+staging project to CANCELLED."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(
            db_session, test_tenant_key, staging_status="staging", status=ProjectStatus.INACTIVE
        )

    result = await staging_service.cancel_staging(str(project.id))

    assert result.status == ProjectStatus.CANCELLED
    assert project.status == ProjectStatus.CANCELLED
    assert project.completed_at is not None


@pytest.mark.asyncio
async def test_cancel_staging_raises_when_not_inactive_staging(staging_service, db_session, test_tenant_key):
    """cancel_staging rejects a project that is not both INACTIVE and in 'staging'."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, staging_status=None, status=ProjectStatus.INACTIVE)

    with pytest.raises(ProjectStateError):
        await staging_service.cancel_staging(str(project.id))
