# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for "cancelled" status in the project lifecycle.

Covers:
- Transition rules: active/inactive -> cancelled (allowed), completed -> cancelled (blocked)
- Immutability: cancelled projects cannot be modified
- list_projects filtering: cancelled excluded by default, shown with explicit filter or "all"
- Tool accessor: "cancelled" accepted in status filter and update status constants
"""

import random
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import IMMUTABLE_PROJECT_STATUSES, ProjectService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def project_service(project_service_with_session):
    """Alias for project_service_with_session from root conftest."""
    return project_service_with_session


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
        mission="Completed mission",
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
async def list_service(db_session, db_manager, tenant_manager, test_tenant_key):
    """ProjectService that routes get_tenant_session_async through the shared test session.

    list_projects() uses db_manager.get_tenant_session_async() directly, not _get_session().
    We patch it so the test transaction's data is visible.
    """
    tenant_manager.set_current_tenant(test_tenant_key)

    @asynccontextmanager
    async def _tenant_session(tenant_key):
        yield db_session

    db_manager.get_tenant_session_async = _tenant_session

    return ProjectService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


# ===========================================================================
# Transition rules: update_project status changes
# ===========================================================================


class TestCancelledTransitionRules:
    """Verify which status transitions to/from cancelled are allowed."""

    @pytest.mark.asyncio
    async def test_update_project_to_cancelled_from_active(self, project_service, active_project):
        """Active -> cancelled should be allowed (active is not immutable)."""
        result = await project_service.update_project(
            project_id=active_project.id,
            updates={"status": "cancelled"},
        )
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_update_project_to_cancelled_from_inactive(self, project_service, inactive_project):
        """Inactive -> cancelled should be allowed (inactive is not immutable)."""
        result = await project_service.update_project(
            project_id=inactive_project.id,
            updates={"status": "cancelled"},
        )
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_update_project_to_cancelled_from_completed(self, project_service, completed_project):
        """Completed -> cancelled should be blocked (completed is immutable)."""
        with pytest.raises(ProjectStateError, match="completed"):
            await project_service.update_project(
                project_id=completed_project.id,
                updates={"status": "cancelled"},
            )

    @pytest.mark.asyncio
    async def test_update_project_from_cancelled_blocked(self, project_service, cancelled_project):
        """Cancelled -> any status should be blocked (cancelled is immutable)."""
        with pytest.raises(ProjectStateError, match="cancelled"):
            await project_service.update_project(
                project_id=cancelled_project.id,
                updates={"status": "active"},
            )

    @pytest.mark.asyncio
    async def test_cancelled_project_name_update_blocked(self, project_service, cancelled_project):
        """Even non-status updates on cancelled projects should be blocked."""
        with pytest.raises(ProjectStateError, match="cancelled"):
            await project_service.update_project(
                project_id=cancelled_project.id,
                updates={"name": "New Name"},
            )


# ===========================================================================
# list_projects filtering for cancelled status
# ===========================================================================


class TestCancelledListFiltering:
    """Verify list_projects handles cancelled projects correctly."""

    @pytest.mark.asyncio
    async def test_list_projects_excludes_cancelled_by_default(
        self, list_service, active_project, cancelled_project, test_tenant_key
    ):
        """Default listing (status=None) should exclude cancelled projects."""
        projects = await list_service.list_projects(
            status=None,
            tenant_key=test_tenant_key,
        )
        project_ids = [p.id for p in projects]
        assert active_project.id in project_ids
        assert cancelled_project.id not in project_ids

    @pytest.mark.asyncio
    async def test_list_projects_shows_cancelled_with_explicit_filter(
        self, list_service, active_project, cancelled_project, test_tenant_key
    ):
        """Explicit status='cancelled' should return only cancelled projects."""
        projects = await list_service.list_projects(
            status="cancelled",
            tenant_key=test_tenant_key,
        )
        project_ids = [p.id for p in projects]
        assert cancelled_project.id in project_ids
        assert active_project.id not in project_ids

    @pytest.mark.asyncio
    async def test_list_projects_shows_cancelled_with_all_filter(
        self, list_service, active_project, cancelled_project, test_tenant_key
    ):
        """status=None with include_cancelled=True (used by tool accessor for 'all')
        should include cancelled projects."""
        projects = await list_service.list_projects(
            status=None,
            tenant_key=test_tenant_key,
            include_cancelled=True,
        )
        project_ids = [p.id for p in projects]
        assert active_project.id in project_ids
        assert cancelled_project.id in project_ids


# ===========================================================================
# Tool accessor constants
# ===========================================================================


class TestToolAccessorCancelledConstants:
    """Verify tool accessor accepts 'cancelled' in status constants."""

    def test_cancelled_in_valid_status_filters(self):
        """'cancelled' should be in _VALID_STATUS_FILTERS (sprint 002f: moved to ProjectService)."""
        from giljo_mcp.services.project_service import ProjectService

        assert "cancelled" in ProjectService._VALID_STATUS_FILTERS

    def test_cancelled_in_valid_update_statuses(self):
        """'cancelled' should be in _VALID_UPDATE_STATUSES (sprint 002f: moved to ProjectService)."""
        from giljo_mcp.services.project_service import ProjectService

        assert "cancelled" in ProjectService._VALID_UPDATE_STATUSES

    def test_immutable_statuses_includes_cancelled(self):
        """'cancelled' should be in IMMUTABLE_PROJECT_STATUSES."""
        assert "cancelled" in IMMUTABLE_PROJECT_STATUSES
