# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for ProjectStateError guards on completed/cancelled projects.

Verifies that update_project, update_project_mission, and spawn_job
all raise ProjectStateError when the target project has an immutable status
(completed or cancelled).
"""

import random
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.project_service import ProjectService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def project_service(project_service_with_session):
    """Alias for project_service_with_session from root conftest."""
    return project_service_with_session


@pytest_asyncio.fixture
async def job_lifecycle_service(db_session, db_manager, tenant_manager, test_tenant_key):
    """JobLifecycleService using shared test session."""
    tenant_manager.set_current_tenant(test_tenant_key)
    return JobLifecycleService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


@pytest_asyncio.fixture
async def completed_project(db_session, test_tenant_key):
    """Create a project with status='completed'."""
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid4()),
        name="Completed Project",
        mission="Done mission",
        description="A completed project",
        status="completed",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def cancelled_project(db_session, test_tenant_key):
    """Create a project with status='cancelled'."""
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid4()),
        name="Cancelled Project",
        mission="Cancelled mission",
        description="A cancelled project",
        status="cancelled",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def active_project(db_session, test_tenant_key):
    """Create a project with status='active'."""
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid4()),
        name="Active Project",
        mission="Active mission",
        description="An active project",
        status="active",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def inactive_project(db_session, test_tenant_key):
    """Create a project with status='inactive'."""
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid4()),
        name="Inactive Project",
        mission="Inactive mission",
        description="An inactive project",
        status="inactive",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


# ---------------------------------------------------------------------------
# update_project guards
# ---------------------------------------------------------------------------


class TestUpdateProjectStatusGuards:
    """Test that update_project blocks writes to completed/cancelled projects."""

    @pytest.mark.asyncio
    async def test_update_project_blocked_when_completed(
        self, project_service: ProjectService, completed_project: Project
    ):
        """update_project raises ProjectStateError for completed projects."""
        with pytest.raises(ProjectStateError) as exc_info:
            await project_service.update_project(
                project_id=completed_project.id,
                updates={"name": "Should Not Change"},
            )
        assert "completed" in exc_info.value.message
        assert "Cannot modify" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_update_project_blocked_when_cancelled(
        self, project_service: ProjectService, cancelled_project: Project
    ):
        """update_project raises ProjectStateError for cancelled projects."""
        with pytest.raises(ProjectStateError) as exc_info:
            await project_service.update_project(
                project_id=cancelled_project.id,
                updates={"name": "Should Not Change"},
            )
        assert "cancelled" in exc_info.value.message
        assert "Cannot modify" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_update_project_allowed_when_active(self, project_service: ProjectService, active_project: Project):
        """update_project succeeds for active projects (no ProjectStateError)."""
        result = await project_service.update_project(
            project_id=active_project.id,
            updates={"name": "Updated Active Name"},
        )
        assert result.name == "Updated Active Name"

    @pytest.mark.asyncio
    async def test_update_project_allowed_when_inactive(
        self, project_service: ProjectService, inactive_project: Project
    ):
        """update_project succeeds for inactive projects (no ProjectStateError)."""
        result = await project_service.update_project(
            project_id=inactive_project.id,
            updates={"name": "Updated Inactive Name"},
        )
        assert result.name == "Updated Inactive Name"


# ---------------------------------------------------------------------------
# update_project_mission guards
# ---------------------------------------------------------------------------


class TestUpdateProjectMissionStatusGuards:
    """Test that update_project_mission blocks writes to completed/cancelled projects."""

    @pytest.mark.asyncio
    async def test_update_project_mission_blocked_when_completed(
        self, project_service: ProjectService, completed_project: Project, test_tenant_key: str
    ):
        """update_project_mission raises ProjectStateError for completed projects."""
        with pytest.raises(ProjectStateError) as exc_info:
            await project_service.update_project_mission(
                project_id=completed_project.id,
                mission="Should not update",
                tenant_key=test_tenant_key,
            )
        assert "completed" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_update_project_mission_blocked_when_cancelled(
        self, project_service: ProjectService, cancelled_project: Project, test_tenant_key: str
    ):
        """update_project_mission raises ProjectStateError for cancelled projects."""
        with pytest.raises(ProjectStateError) as exc_info:
            await project_service.update_project_mission(
                project_id=cancelled_project.id,
                mission="Should not update",
                tenant_key=test_tenant_key,
            )
        assert "cancelled" in exc_info.value.message


# ---------------------------------------------------------------------------
# spawn_job guards
# ---------------------------------------------------------------------------


class TestSpawnAgentJobStatusGuards:
    """Test that spawn_job blocks spawning into completed/cancelled projects."""

    @pytest.mark.asyncio
    async def test_spawn_job_blocked_when_completed(
        self, job_lifecycle_service: JobLifecycleService, completed_project: Project, test_tenant_key: str
    ):
        """spawn_job raises ProjectStateError for completed projects."""
        with pytest.raises(ProjectStateError) as exc_info:
            await job_lifecycle_service.spawn_job(
                agent_display_name="Test Agent",
                agent_name="test-agent",
                mission="Should not spawn",
                project_id=completed_project.id,
                tenant_key=test_tenant_key,
            )
        assert "completed" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_spawn_job_blocked_when_cancelled(
        self, job_lifecycle_service: JobLifecycleService, cancelled_project: Project, test_tenant_key: str
    ):
        """spawn_job raises ProjectStateError for cancelled projects."""
        with pytest.raises(ProjectStateError) as exc_info:
            await job_lifecycle_service.spawn_job(
                agent_display_name="Test Agent",
                agent_name="test-agent",
                mission="Should not spawn",
                project_id=cancelled_project.id,
                tenant_key=test_tenant_key,
            )
        assert "cancelled" in exc_info.value.message


# ---------------------------------------------------------------------------
# Error message content
# ---------------------------------------------------------------------------


class TestErrorMessageContent:
    """Test that the error message includes the project status and guidance."""

    @pytest.mark.asyncio
    async def test_error_message_contains_status(self, project_service: ProjectService, completed_project: Project):
        """Error message includes the actual status and guidance about allowed statuses."""
        with pytest.raises(ProjectStateError) as exc_info:
            await project_service.update_project(
                project_id=completed_project.id,
                updates={"name": "Nope"},
            )
        msg = exc_info.value.message
        assert "completed" in msg
        assert "inactive" in msg.lower() or "active" in msg.lower()
