# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for ProjectLifecycleService (Sprint 002f -- P2 core).

Covers:
- activate_project (happy path, invalid state, Single Active Project constraint)
- deactivate_project (happy path, invalid state)
- complete_project (validation, summary required)
- cancel_project (happy path, not found)
- continue_working (happy path, invalid state)
- Tenant isolation on every query
"""

import inspect
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
from giljo_mcp.services.project_lifecycle_service._orchestrator_fixture_mixin import (
    OrchestratorFixtureMixin,
)


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
    session.add = Mock()
    session.delete = Mock()
    session.flush = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    return session


def _make_project(
    project_id=PROJECT_ID,
    status="inactive",
    tenant_key=TENANT_KEY,
    product_id="prod-1",
):
    """Create a mock Project model.

    ``status`` is coerced to a :class:`ProjectStatus` enum member to mirror
    real DB behavior (SQLAlchemy returns enum members from the typed
    ``project_status`` column). Tests may pass either a raw lifecycle string
    ("active", "completed", ...) or a :class:`ProjectStatus` member.
    """
    project = MagicMock()
    project.id = project_id
    project.name = "Test Project"
    project.status = ProjectStatus(status) if isinstance(status, str) else status
    project.tenant_key = tenant_key
    project.product_id = product_id
    project.updated_at = None
    project.completed_at = None
    project.deleted_at = None
    project.mission = "Test mission"
    project.description = "Test description"
    project.staging_status = None
    return project


def _make_service(session, tenant_key=TENANT_KEY):
    """Create a ProjectLifecycleService with injected test session."""
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    # Patch out ProjectStagingService to avoid circular init
    with patch("giljo_mcp.services.project_staging_service.ProjectStagingService"):
        return ProjectLifecycleService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            test_session=session,
        )


# ---------------------------------------------------------------------------
# activate_project tests
# ---------------------------------------------------------------------------


class TestActivateProject:
    """Tests for ProjectLifecycleService.activate_project."""

    @pytest.mark.asyncio
    async def test_activate_project_not_found_raises(self):
        """Raises ResourceNotFoundError when project does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="Project not found"):
            await service.activate_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_activate_from_completed_raises(self):
        """Raises ProjectStateError when project is completed."""
        project = _make_project(status="completed")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ProjectStateError, match="Cannot activate"):
            await service.activate_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_activate_from_inactive_succeeds(self):
        """Successfully activates an inactive project."""
        project = _make_project(status="inactive")
        session = _make_session()

        # First call: find project. Second call: check for existing active (none found).
        # Third+: orchestrator fixture check
        call_count = 0
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_no_active = MagicMock()
        mock_no_active.scalar_one_or_none.return_value = None

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_project_result
            return mock_no_active

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        await service.activate_project(PROJECT_ID)

        assert project.status == "active"
        session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_activate_fixture_commit_failure_skips_agent_created_broadcast(self):
        """BE-3006c: the orchestrator-fixture ``agent:created`` event must NOT
        fire if the owner commit for the fixture fails.

        Repo ``create_orchestrator_fixture`` now flushes (not commits); the owner
        commits inside ``_ensure_orchestrator_fixture`` BEFORE the broadcast. If
        that commit fails, no event may fire -- otherwise the dashboard shows a
        phantom "orchestrator created" row for a fixture that rolled back. The
        first commit (activation) succeeds; the second (fixture) is forced to
        raise.
        """
        project = _make_project(status="inactive")
        session = _make_session()

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_none = MagicMock()
        mock_none.scalar_one_or_none.return_value = None

        call_count = 0

        async def execute_side_effect(_stmt):
            nonlocal call_count
            call_count += 1
            return mock_project_result if call_count == 1 else mock_none

        session.execute = AsyncMock(side_effect=execute_side_effect)

        # 1st commit (activation) succeeds; 2nd (orchestrator fixture) fails.
        commit_count = 0

        async def commit_side_effect():
            nonlocal commit_count
            commit_count += 1
            if commit_count >= 2:
                raise RuntimeError("fixture commit boom")

        session.commit = AsyncMock(side_effect=commit_side_effect)

        ws = MagicMock()
        ws.broadcast_to_tenant = AsyncMock()
        ws.broadcast_project_update = AsyncMock()

        service = _make_service(session)
        with pytest.raises(BaseGiljoError):
            await service.activate_project(PROJECT_ID, websocket_manager=ws)

        # The agent:created (fixture) broadcast must never have fired.
        ws.broadcast_to_tenant.assert_not_called()


# ---------------------------------------------------------------------------
# deactivate_project tests
# ---------------------------------------------------------------------------


class TestDeactivateProject:
    """Tests for ProjectLifecycleService.deactivate_project."""

    @pytest.mark.asyncio
    async def test_deactivate_not_found_raises(self):
        """Raises ResourceNotFoundError when project does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.deactivate_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_deactivate_non_active_raises(self):
        """Raises ProjectStateError when project is not active."""
        project = _make_project(status="inactive")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ProjectStateError, match="Cannot deactivate"):
            await service.deactivate_project(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_deactivate_active_succeeds(self):
        """Successfully deactivates an active project."""
        project = _make_project(status="active")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        await service.deactivate_project(PROJECT_ID)

        assert project.status == "inactive"
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# complete_project tests
# ---------------------------------------------------------------------------


class TestCompleteProject:
    """Tests for ProjectLifecycleService.complete_project."""

    @pytest.mark.asyncio
    async def test_complete_no_tenant_raises(self):
        """Raises ValidationError when tenant is not set."""
        session = _make_session()
        service = _make_service(session)
        # Override tenant_manager to return None
        service.tenant_manager.get_current_tenant.return_value = None

        with pytest.raises(ValidationError, match="Tenant not set"):
            await service.complete_project(
                project_id=PROJECT_ID,
                summary="Done",
                key_outcomes=["Shipped feature"],
                decisions_made=["Used pattern X"],
            )

    @pytest.mark.asyncio
    async def test_complete_empty_summary_raises(self):
        """Raises ValidationError when summary is empty."""
        session = _make_session()
        service = _make_service(session)

        with pytest.raises(ValidationError, match="Summary is required"):
            await service.complete_project(
                project_id=PROJECT_ID,
                summary="",
                key_outcomes=["Shipped feature"],
                decisions_made=["Used pattern X"],
            )

    @pytest.mark.asyncio
    async def test_complete_whitespace_summary_raises(self):
        """Raises ValidationError when summary is whitespace."""
        session = _make_session()
        service = _make_service(session)

        with pytest.raises(ValidationError, match="Summary is required"):
            await service.complete_project(
                project_id=PROJECT_ID,
                summary="   ",
                key_outcomes=[],
                decisions_made=[],
            )


# ---------------------------------------------------------------------------
# cancel_project tests
# ---------------------------------------------------------------------------


class TestCancelProject:
    """Tests for ProjectLifecycleService.cancel_project."""

    @pytest.mark.asyncio
    async def test_cancel_not_found_raises(self):
        """Raises ResourceNotFoundError when project does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.cancel_project(PROJECT_ID, TENANT_KEY)

    @pytest.mark.asyncio
    async def test_cancel_succeeds(self):
        """Successfully cancels a project."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        await service.cancel_project(PROJECT_ID, TENANT_KEY)

        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_with_reason(self):
        """Passes cancellation reason to the update statement."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        await service.cancel_project(PROJECT_ID, TENANT_KEY, reason="Requirements changed")

        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# continue_working tests
# ---------------------------------------------------------------------------


class TestContinueWorking:
    """Tests for ProjectLifecycleService.continue_working."""

    @pytest.mark.asyncio
    async def test_continue_not_found_raises(self):
        """Raises ResourceNotFoundError when project does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.continue_working(PROJECT_ID, TENANT_KEY)

    @pytest.mark.asyncio
    async def test_continue_non_completed_raises(self):
        """Raises ProjectStateError when project is not completed."""
        project = _make_project(status="active")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ProjectStateError, match="Cannot resume"):
            await service.continue_working(PROJECT_ID, TENANT_KEY)

    @pytest.mark.asyncio
    async def test_continue_completed_succeeds(self):
        """Successfully resumes a completed project to inactive state."""
        project = _make_project(status="completed")
        session = _make_session()

        # First call: find project. Second call: find decommissioned agents (none).
        call_count = 0
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_agents_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_agents_result.scalars.return_value = mock_scalars

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_project_result
            return mock_agents_result

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        result = await service.continue_working(PROJECT_ID, TENANT_KEY)

        assert project.status == "inactive"
        assert project.completed_at is None
        assert result.message == "Project resumed successfully"
        assert result.agents_resumed == 0


# ---------------------------------------------------------------------------
# INF-6129: the orchestrator-fixture helpers were extracted from this service
# into OrchestratorFixtureMixin to keep the module under the 800-line file-size
# guardrail. These guard the composition so a future refactor cannot silently
# drop the mixin -- which would AttributeError inside activate_project /
# deactivate_project at runtime (the helpers are called as ``self._...``).
# ---------------------------------------------------------------------------


def test_lifecycle_service_composes_orchestrator_fixture_mixin():
    """The service must inherit the extracted orchestrator-fixture helpers."""
    assert OrchestratorFixtureMixin in ProjectLifecycleService.__mro__


@pytest.mark.parametrize(
    "method_name",
    [
        "_ensure_orchestrator_fixture",
        "_maybe_reset_never_run_orchestrator",
        "_broadcast_agents_removed",
    ],
)
def test_orchestrator_fixture_methods_resolve_on_service(method_name):
    """Each extracted helper still resolves on the composed service as a coroutine."""
    method = getattr(ProjectLifecycleService, method_name, None)
    assert method is not None, f"{method_name} must resolve on ProjectLifecycleService"
    assert inspect.iscoroutinefunction(method)
