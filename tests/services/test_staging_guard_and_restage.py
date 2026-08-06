# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for staging guard on generate_staging_prompt and POST restage endpoint.

Covers:
1. Staging guard: 409 when project.staging_status == "staging"
2. Restage when staging + orchestrator waiting -> 200, status reset
3. Restage when orchestrator active -> 409
4. Restage when not staging -> 409
5. Restage creates fresh orchestrator fixture
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_manager():
    """Mock database manager with async session support."""
    db_manager = MagicMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    db_manager.get_session_async = MagicMock(return_value=session)
    return db_manager, session


@pytest.fixture
def mock_tenant_manager():
    """Mock tenant manager."""
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant = MagicMock(return_value="tenant-test")
    return tenant_manager


@pytest.fixture
def lifecycle_service(mock_db_manager, mock_tenant_manager):
    """Create ProjectLifecycleService with mocked dependencies."""
    db_manager, _ = mock_db_manager
    return ProjectLifecycleService(db_manager=db_manager, tenant_manager=mock_tenant_manager)


def _make_project(staging_status=None, execution_mode="multi_terminal", status="active"):
    """Create a mock Project with configurable staging_status."""
    project = MagicMock(spec=Project)
    project.id = str(uuid4())
    project.name = "Test Project"
    project.status = status
    project.staging_status = staging_status
    project.execution_mode = execution_mode
    project.tenant_key = "tenant-test"
    project.mission = "Test mission"
    project.description = "Test description"
    project.cancellation_reason = None
    project.early_termination = None
    project.created_at = datetime.now(UTC)
    project.updated_at = datetime.now(UTC)
    project.completed_at = None
    project.product_id = str(uuid4())
    return project


def _make_orchestrator_execution(status="waiting"):
    """Create a mock AgentExecution for an orchestrator."""
    execution = MagicMock(spec=AgentExecution)
    execution.agent_id = str(uuid4())
    execution.job_id = str(uuid4())
    execution.status = status
    execution.agent_display_name = "orchestrator"
    execution.agent_name = "orchestrator"
    execution.tenant_key = "tenant-test"
    return execution


# ---------------------------------------------------------------------------
# Test 1: Staging guard — 409 when staging_status == "staging"
# ---------------------------------------------------------------------------


class TestStagingGuard:
    """Test the staging guard that prevents re-staging when already staging."""

    @pytest.mark.asyncio
    async def test_staging_guard_rejects_when_already_staging(self, lifecycle_service, mock_db_manager):
        """generate_staging_prompt should be blocked when staging_status is 'staging'."""
        # This test validates the guard logic at the endpoint level.
        # The endpoint reads project.staging_status and raises HTTPException(409).
        # We test the service-level check_staging_allowed method.
        project = _make_project(staging_status="staging")

        from giljo_mcp.exceptions import ProjectStateError

        with pytest.raises(ProjectStateError, match="Staging already in progress"):
            lifecycle_service.check_staging_allowed(project)

    def test_staging_guard_allows_when_not_staging(self, lifecycle_service):
        """Should allow staging when staging_status is None."""
        project = _make_project(staging_status=None)
        # Should not raise
        lifecycle_service.check_staging_allowed(project)

    def test_staging_guard_allows_when_staging_complete(self, lifecycle_service):
        """Should allow staging when staging_status is 'staging_complete'."""
        project = _make_project(staging_status="staging_complete")
        # Should not raise
        lifecycle_service.check_staging_allowed(project)


# ---------------------------------------------------------------------------
# Test 2-5: Restage endpoint
# ---------------------------------------------------------------------------


class TestRestage:
    """Test the restage service method."""

    @pytest.mark.asyncio
    async def test_restage_success_when_staging_and_orchestrator_waiting(self, lifecycle_service, mock_db_manager):
        """Restage should succeed when staging_status='staging' and orchestrator is waiting."""
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        orchestrator = _make_orchestrator_execution(status="waiting")

        # First execute: fetch project
        # Second execute: fetch orchestrator
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        # Patch _ensure_orchestrator_fixture to return fixture data
        fixture_result = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = fixture_result
            result = await lifecycle_service.restage(project.id)

        # Verify project state was reset
        assert project.staging_status is None
        assert project.execution_mode == "multi_terminal"

        # Verify orchestrator was decommissioned
        assert orchestrator.status == "decommissioned"

        # Verify session commit was called
        session.commit.assert_called()

        # Verify _ensure_orchestrator_fixture was called
        mock_fixture.assert_called_once()

        # Verify result
        assert result["message"] == "Project restaged successfully"
        assert result["project_id"] == project.id

    @pytest.mark.asyncio
    async def test_restage_rejects_when_not_staging(self, lifecycle_service, mock_db_manager):
        """Restage should fail with ProjectStateError when staging_status != 'staging'."""
        _, session = mock_db_manager
        project = _make_project(staging_status=None)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=project)
        session.execute = AsyncMock(return_value=mock_result)

        from giljo_mcp.exceptions import ProjectStateError

        with pytest.raises(ProjectStateError, match="not currently staged"):
            await lifecycle_service.restage(project.id)

    @pytest.mark.asyncio
    async def test_restage_recovers_from_staging_complete_before_implementation(
        self, lifecycle_service, mock_db_manager
    ):
        """BE-6047: restage recovers a 'staging_complete' project (handoff window,
        implementation not yet launched) — staging_status reset, fresh orchestrator built.
        """
        _, session = mock_db_manager
        project = _make_project(staging_status="staging_complete")
        project.implementation_launched_at = None  # handoff window: Implement not yet clicked
        orchestrator = _make_orchestrator_execution(status="waiting")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        fixture_result = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = fixture_result
            result = await lifecycle_service.restage(project.id)

        assert project.staging_status is None
        assert orchestrator.status == "decommissioned"
        assert result["message"] == "Project restaged successfully"

    @pytest.mark.asyncio
    async def test_restage_rejects_staging_complete_after_implementation_launched(
        self, lifecycle_service, mock_db_manager
    ):
        """BE-6047: restage rejects a 'staging_complete' project once implementation
        has been launched — recovering then would strand spawned implementation jobs.
        """
        _, session = mock_db_manager
        project = _make_project(staging_status="staging_complete")
        project.implementation_launched_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=project)
        session.execute = AsyncMock(return_value=mock_result)

        from giljo_mcp.exceptions import ProjectStateError

        with pytest.raises(ProjectStateError, match="implementation already launched"):
            await lifecycle_service.restage(project.id)

    @pytest.mark.asyncio
    async def test_restage_rejects_when_orchestrator_active(self, lifecycle_service, mock_db_manager):
        """Restage should fail when orchestrator status != 'waiting'."""
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        orchestrator = _make_orchestrator_execution(status="working")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        from giljo_mcp.exceptions import ProjectStateError

        with pytest.raises(ProjectStateError, match="orchestrator agent is already active"):
            await lifecycle_service.restage(project.id)

    @pytest.mark.asyncio
    async def test_restage_rejects_when_project_not_found(self, lifecycle_service, mock_db_manager):
        """Restage should fail with ResourceNotFoundError for unknown project."""
        _, session = mock_db_manager

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_result)

        from giljo_mcp.exceptions import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError, match="Project not found"):
            await lifecycle_service.restage(str(uuid4()))

    @pytest.mark.asyncio
    async def test_restage_clears_implementation_launched_at_ce_0032(self, lifecycle_service, mock_db_manager):
        """CE-0032: restage MUST clear project.implementation_launched_at.

        Scenario the fix prevents:
          1. User completes a project (impl_launched_at = <v1 timestamp>).
          2. User restores + restages for v2.
          3. Without the clear, the new staging-end complete_job sees
             impl_launched_at non-null and the CE-0032 TODOs-bypass key
             evaluates False — regressing the CE-0027 fix on restage-after-
             completion.
        """
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        # Simulate a stale v1 impl timestamp surviving from a prior completed cycle.
        project.implementation_launched_at = datetime.now(UTC)
        orchestrator = _make_orchestrator_execution(status="waiting")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
            await lifecycle_service.restage(project.id)

        assert project.implementation_launched_at is None, (
            "CE-0032: restage must clear project.implementation_launched_at to None — "
            "stale v1 timestamps would regress the CE-0027 TODOs-bypass on restage-after-completion"
        )
        # Sibling invariants still hold.
        assert project.staging_status is None
        assert project.execution_mode == "multi_terminal"

    @pytest.mark.asyncio
    async def test_restage_does_not_clear_ever_launched_at(self, lifecycle_service, mock_db_manager):
        """BE-9085b: restage clears implementation_launched_at (clean-slate cycle)
        but MUST leave the durable ever_launched_at signal untouched -- this is
        THE fix for the BE-9085 detector's restage false-positive.
        """
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        project.implementation_launched_at = datetime.now(UTC)
        project.ever_launched_at = datetime.now(UTC)
        orchestrator = _make_orchestrator_execution(status="waiting")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
            await lifecycle_service.restage(project.id)

        assert project.implementation_launched_at is None
        assert project.ever_launched_at is not None, (
            "BE-9085b: restage must NOT clear ever_launched_at -- it's the durable "
            "'was ever launched' fact the BE-9085 detector relies on"
        )

    @pytest.mark.asyncio
    async def test_restage_creates_fresh_orchestrator_fixture(self, lifecycle_service, mock_db_manager):
        """Restage should call _ensure_orchestrator_fixture to create a new one."""
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        orchestrator = _make_orchestrator_execution(status="waiting")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        new_fixture = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = new_fixture
            result = await lifecycle_service.restage(project.id)

        # _ensure_orchestrator_fixture must be called with (session, project)
        mock_fixture.assert_called_once_with(session, project)
        assert result["new_orchestrator"] == new_fixture
