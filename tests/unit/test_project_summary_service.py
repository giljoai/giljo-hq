# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for ProjectSummaryService (Sprint 002f -- P2 core).

Covers:
- get_project_summary happy path
- Project not found error path
- Job count aggregation
- Completion percentage calculation
- Product context resolution
- Tenant isolation on every query
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.services.project_summary_service import ProjectSummaryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TENANT_KEY = "test-tenant"
PROJECT_ID = "proj-001"


def _make_session():
    """Create a mock async session configured as a context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    return session


def _make_project(
    project_id=PROJECT_ID,
    status="active",
    tenant_key=TENANT_KEY,
    product_id="prod-1",
    name="Test Project",
    mission="Test mission",
):
    """Create a mock Project model."""
    project = MagicMock()
    project.id = project_id
    project.name = name
    project.status = status
    project.tenant_key = tenant_key
    project.product_id = product_id
    project.mission = mission
    project.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return project


def _make_service(session, tenant_key=TENANT_KEY):
    """Create a ProjectSummaryService with injected test session."""
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return ProjectSummaryService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=session,
    )


# ---------------------------------------------------------------------------
# get_project_summary tests
# ---------------------------------------------------------------------------


class TestGetProjectSummary:
    """Tests for ProjectSummaryService.get_project_summary."""

    @pytest.mark.asyncio
    async def test_project_not_found_raises(self):
        """Raises ResourceNotFoundError when project does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="Project not found"):
            await service.get_project_summary("nonexistent")

    @pytest.mark.asyncio
    async def test_summary_with_no_jobs(self):
        """Returns zero counts when project has no agent jobs."""
        project = _make_project()
        session = _make_session()

        call_count = 0

        # Mock job_counts query returning empty
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_job_counts = MagicMock()
        mock_job_counts.all.return_value = []
        mock_last_activity = MagicMock()
        mock_last_activity.scalar.return_value = None
        mock_product_result = MagicMock()
        mock_product_obj = MagicMock()
        mock_product_obj.name = "Test Product"
        mock_product_result.scalar_one_or_none.return_value = mock_product_obj

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_project_result  # project lookup
            if call_count == 2:
                return mock_job_counts  # job counts
            if call_count == 3:
                return mock_last_activity  # last activity
            return mock_product_result  # product lookup

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        result = await service.get_project_summary(PROJECT_ID)

        assert result.id == PROJECT_ID
        assert result.total_jobs == 0
        assert result.completed_jobs == 0
        assert result.completion_percentage == 0.0
        assert result.product_name == "Test Product"

    @pytest.mark.asyncio
    async def test_summary_calculates_completion_percentage(self):
        """Correctly calculates completion percentage from job counts."""
        project = _make_project()
        session = _make_session()

        call_count = 0

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        # 2 complete + 1 working + 1 waiting = 4 total, 50% complete
        mock_job_counts = MagicMock()
        mock_job_counts.all.return_value = [("complete", 2), ("working", 1), ("waiting", 1)]
        mock_last_activity = MagicMock()
        mock_last_activity.scalar.return_value = None
        mock_product_result = MagicMock()
        mock_product_result.scalar_one_or_none.return_value = None

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_project_result
            if call_count == 2:
                return mock_job_counts
            if call_count == 3:
                return mock_last_activity
            return mock_product_result

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        result = await service.get_project_summary(PROJECT_ID)

        assert result.total_jobs == 4
        assert result.completed_jobs == 2
        assert result.active_jobs == 1
        assert result.pending_jobs == 1
        assert result.completion_percentage == 50.0

    @pytest.mark.asyncio
    async def test_summary_no_product_returns_empty_name(self):
        """Returns empty product_name when project has no product."""
        project = _make_project(product_id=None)
        session = _make_session()

        call_count = 0

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_job_counts = MagicMock()
        mock_job_counts.all.return_value = []
        mock_last_activity = MagicMock()
        mock_last_activity.scalar.return_value = None

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_project_result
            if call_count == 2:
                return mock_job_counts
            return mock_last_activity

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        result = await service.get_project_summary(PROJECT_ID)

        assert result.product_name == ""
        assert result.product_id == ""

    @pytest.mark.asyncio
    async def test_summary_includes_timestamps(self):
        """Summary includes properly formatted timestamps."""
        project = _make_project()
        session = _make_session()

        call_count = 0
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_job_counts = MagicMock()
        mock_job_counts.all.return_value = []
        last_activity = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
        mock_last_activity = MagicMock()
        mock_last_activity.scalar.return_value = last_activity
        mock_product_result = MagicMock()
        mock_product_result.scalar_one_or_none.return_value = None

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_project_result
            if call_count == 2:
                return mock_job_counts
            if call_count == 3:
                return mock_last_activity
            return mock_product_result

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        result = await service.get_project_summary(PROJECT_ID)

        assert result.created_at is not None
        assert result.last_activity_at is not None
        assert "2026" in result.created_at
