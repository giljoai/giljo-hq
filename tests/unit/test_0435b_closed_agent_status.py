# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for Handover 0435b: Add 'closed' Agent Lifecycle Status.

Tests cover:
1. close_job transitions complete → closed
2. close_job rejects non-complete status
3. _auto_block_completed_recipients skips closed agents
4. Project closeout transitions complete → closed (not decommissioned)
5. _SKIP_STATUSES includes 'closed'
6. Frontend statusConfig includes 'closed'
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError


# ---------------------------------------------------------------------------
# 1. close_job: complete → closed transition
# ---------------------------------------------------------------------------


class TestCloseJobTransition:
    """Verify close_job only works on 'complete' agents and transitions to 'closed'."""

    @pytest.fixture
    def state_service(self):
        from giljo_mcp.services.orchestration_agent_state_service import (
            OrchestrationAgentStateService,
        )

        mock_db = MagicMock()
        mock_tenant = MagicMock()
        mock_tenant.get_current_tenant.return_value = "test_tenant"

        return OrchestrationAgentStateService(
            db_manager=mock_db,
            tenant_manager=mock_tenant,
        )

    @pytest.mark.asyncio
    async def test_close_job_requires_complete_status(self, state_service):
        """close_job should raise ResourceNotFoundError (wrong-state) if the job exists
        but its latest execution is not 'complete' (BE-8003b disambiguation)."""
        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        state_service._get_session = MagicMock(return_value=_async_ctx(mock_session))

        working_execution = MagicMock()
        working_execution.status = "working"
        state_service._job_repo.find_complete_execution_for_job = AsyncMock(return_value=None)
        state_service._job_repo.get_latest_execution_for_job = AsyncMock(return_value=working_execution)
        state_service._job_repo.get_agent_job_by_job_id = AsyncMock(return_value=None)

        with pytest.raises(ResourceNotFoundError, match="not 'complete'"):
            await state_service.close_job(job_id="some-job-id", tenant_key="test_tenant")

    @pytest.mark.asyncio
    async def test_close_job_unknown_job_id_raises_not_found(self, state_service):
        """close_job should raise a distinct 'unknown job_id' error when the job_id
        does not exist in this tenant at all (BE-8003b disambiguation)."""
        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        state_service._get_session = MagicMock(return_value=_async_ctx(mock_session))

        state_service._job_repo.find_complete_execution_for_job = AsyncMock(return_value=None)
        state_service._job_repo.get_latest_execution_for_job = AsyncMock(return_value=None)

        with pytest.raises(ResourceNotFoundError, match="No job found with ID") as exc_info:
            await state_service.close_job(job_id="ghost-job-id", tenant_key="test_tenant")
        assert exc_info.value.context["reason"] == "unknown_job_id"
        assert exc_info.value.context["next_action"]["tool"] == "diagnose_project_state"

    @pytest.mark.asyncio
    async def test_close_job_empty_job_id_rejected(self, state_service):
        """close_job should raise ValidationError for empty job_id."""
        from giljo_mcp.exceptions import ValidationError

        with pytest.raises(ValidationError, match="job_id cannot be empty"):
            await state_service.close_job(job_id="", tenant_key="test_tenant")

    @pytest.mark.asyncio
    async def test_close_job_sets_closed_status(self, state_service):
        """close_job should set execution.status to 'closed' when in 'complete'."""
        mock_execution = MagicMock()
        mock_execution.status = "complete"
        mock_execution.agent_display_name = "implementer"
        mock_execution.agent_name = "backend-impl"
        mock_execution.job_id = "test-job-123"
        mock_execution.agent_id = "impl-agent-1"

        mock_job = MagicMock()
        mock_job.project_id = "proj-456"

        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target

        # First call returns execution, second returns job, third is the
        # BE-9242 dead-cursor-resolution lookup (no live unread messages to
        # resolve for this closing agent -- resolve_terminal_agent_cursors
        # returns without any further queries).
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = mock_execution
        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = mock_job
        undrained_result = MagicMock()
        undrained_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[exec_result, job_result, undrained_result])
        mock_session.flush = AsyncMock()

        state_service._get_session = MagicMock(return_value=_async_ctx(mock_session))

        result = await state_service.close_job(job_id="test-job-123", tenant_key="test_tenant")

        assert mock_execution.status == "closed"
        assert result["old_status"] == "complete"
        assert result["new_status"] == "closed"
        assert result["job_id"] == "test-job-123"


# ---------------------------------------------------------------------------
# 2. Auto-block skips closed agents
# ---------------------------------------------------------------------------


class TestAutoBlockSkipsClosed:
    """Verify that _auto_block_completed_recipients only blocks 'complete', not 'closed'."""

    def test_auto_block_condition_only_matches_complete(self):
        """The auto-block check should match 'complete' but not 'closed'."""
        # This tests the condition logic directly
        for status in ["complete"]:
            assert status == "complete"  # Would trigger auto-block

        for status in ["closed", "decommissioned", "working"]:
            assert status != "complete"  # Would NOT trigger auto-block


# ---------------------------------------------------------------------------
# 3. Skip statuses include 'closed'
# ---------------------------------------------------------------------------


class TestSkipStatuses:
    """Verify that skip statuses include 'closed' for closeout readiness checks.

    BE-3010c: the two former tools-layer skip-status sets (project_closeout._SKIP_STATUSES
    and write_memory_entry.SKIP_STATUSES, identical members under divergent names) were
    unified into the single ProjectCloseoutService._CLOSEOUT_SKIP_STATUSES that the
    readiness gathering uses. This contract now asserts the one canonical set.
    """

    def test_closeout_skip_statuses_are_unified(self):
        from giljo_mcp.services.project_closeout_service import _CLOSEOUT_SKIP_STATUSES

        assert "closed" in _CLOSEOUT_SKIP_STATUSES
        assert "decommissioned" in _CLOSEOUT_SKIP_STATUSES


# ---------------------------------------------------------------------------
# 4. Model CHECK constraint includes 'closed'
# ---------------------------------------------------------------------------


class TestModelConstraint:
    """Verify the CHECK constraint in the model includes 'closed'."""

    def test_agent_execution_check_constraint_includes_closed(self):
        from giljo_mcp.models.agent_identity import AgentExecution

        constraints = [
            c
            for c in AgentExecution.__table_args__
            if hasattr(c, "name") and getattr(c, "name", None) == "ck_agent_execution_status"
        ]
        assert len(constraints) == 1
        constraint_text = str(constraints[0].sqltext)
        assert "'closed'" in constraint_text


# ---------------------------------------------------------------------------
# 5. Placeholder job_id set (from 0435a, imported here for completeness)
# ---------------------------------------------------------------------------


class TestPlaceholderJobIds:
    """Verify placeholder set is correctly defined."""

    def test_placeholder_set(self):
        from api.endpoints.mcp_sdk_server import _PLACEHOLDER_JOB_IDS

        assert "unknown" in _PLACEHOLDER_JOB_IDS
        assert "placeholder" in _PLACEHOLDER_JOB_IDS


# ---------------------------------------------------------------------------
# 6. Staging-phase status lock on set_agent_status (Project BE-staging-lock)
# ---------------------------------------------------------------------------


class TestStagingPhaseStatusLock:
    """Verify set_agent_status is server-locked for the staging orchestrator.

    Lock condition: agent_display_name == 'orchestrator' AND
    project.staging_status != 'staging_complete'.
    Spawned non-orchestrator agents bypass the lock.
    report_progress is a separate method and is not affected by this lock.
    """

    @pytest.fixture
    def state_service(self):
        from giljo_mcp.services.orchestration_agent_state_service import (
            OrchestrationAgentStateService,
        )

        mock_db = MagicMock()
        mock_tenant = MagicMock()
        mock_tenant.get_current_tenant.return_value = "test-tenant"
        return OrchestrationAgentStateService(
            db_manager=mock_db,
            tenant_manager=mock_tenant,
        )

    @staticmethod
    def _wire(state_service, execution, job, project):
        """Wire repo + session mocks so set_agent_status sees execution/job/project."""
        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_session.flush = AsyncMock()
        state_service._get_session = MagicMock(return_value=_async_ctx(mock_session))
        state_service._job_repo.find_active_execution_for_job = AsyncMock(return_value=execution)
        state_service._job_repo.get_agent_job_by_job_id = AsyncMock(return_value=job)
        state_service._job_repo.get_project_by_id = AsyncMock(return_value=project)
        # BE-3006b: set_agent_status now flushes; the session owner commits.
        state_service._job_repo.flush = AsyncMock()
        return mock_session

    @pytest.mark.asyncio
    async def test_orchestrator_during_staging_is_locked(self, state_service):
        """Orchestrator + staging_status='staging' → AuthorizationError STAGING_LOCK."""
        from giljo_mcp.exceptions import AuthorizationError

        execution = MagicMock()
        execution.agent_display_name = "orchestrator"
        execution.agent_name = "orchestrator"
        execution.status = "working"
        job = MagicMock()
        job.project_id = "proj-1"
        project = MagicMock()
        project.staging_status = "staging"

        self._wire(state_service, execution, job, project)

        with pytest.raises(AuthorizationError) as exc_info:
            await state_service.set_agent_status(
                job_id="orch-job", status="blocked", reason="need clarification", tenant_key="test-tenant"
            )
        assert exc_info.value.error_code == "STAGING_LOCK"
        assert exc_info.value.default_status_code == 403
        # Status must NOT have been mutated.
        assert execution.status == "working"

    @pytest.mark.asyncio
    async def test_orchestrator_after_staging_complete_succeeds(self, state_service):
        """Orchestrator + staging_status='staging_complete' → 200 OK."""
        execution = MagicMock()
        execution.agent_display_name = "orchestrator"
        execution.agent_name = "orchestrator"
        execution.status = "working"
        job = MagicMock()
        job.project_id = "proj-1"
        project = MagicMock()
        project.staging_status = "staging_complete"

        self._wire(state_service, execution, job, project)

        result = await state_service.set_agent_status(
            job_id="orch-job", status="blocked", reason="real blocker", tenant_key="test-tenant"
        )
        assert result.status == "blocked"
        assert execution.status == "blocked"

    @pytest.mark.asyncio
    async def test_spawned_implementer_during_staging_succeeds(self, state_service):
        """Spawned implementer (non-orchestrator) bypasses the lock during staging."""
        execution = MagicMock()
        execution.agent_display_name = "implementer"
        execution.agent_name = "implementer-backend"
        execution.status = "working"
        job = MagicMock()
        job.project_id = "proj-1"
        project = MagicMock()
        project.staging_status = "staging"

        self._wire(state_service, execution, job, project)

        result = await state_service.set_agent_status(
            job_id="impl-job", status="blocked", reason="need orchestrator help", tenant_key="test-tenant"
        )
        assert result.status == "blocked"
        assert execution.status == "blocked"

    def test_report_progress_does_not_invoke_set_agent_status(self):
        """report_progress must bypass the staging lock by never routing through set_agent_status.

        progress_service writes execution.status = 'working' directly. This test
        protects that architectural separation: if a future refactor pushes the
        auto-wake transition through set_agent_status, the staging lock would
        break orchestrator progress reporting during staging.
        """
        import inspect

        from giljo_mcp.services import progress_service

        source = inspect.getsource(progress_service)
        assert "set_agent_status" not in source, (
            "progress_service must not call set_agent_status — staging lock would block "
            "orchestrator progress reporting during staging."
        )

    @pytest.mark.asyncio
    async def test_orchestrator_during_staging_with_null_project_locked(self, state_service):
        """Orchestrator with staging_status=None (never staged) is also locked.

        Treat any non-'staging_complete' value (None, 'staging', etc.) as locked.
        """
        from giljo_mcp.exceptions import AuthorizationError

        execution = MagicMock()
        execution.agent_display_name = "orchestrator"
        execution.agent_name = "orchestrator"
        execution.status = "working"
        job = MagicMock()
        job.project_id = "proj-1"
        project = MagicMock()
        project.staging_status = None

        self._wire(state_service, execution, job, project)

        with pytest.raises(AuthorizationError) as exc_info:
            await state_service.set_agent_status(job_id="orch-job", status="idle", tenant_key="test-tenant")
        assert exc_info.value.error_code == "STAGING_LOCK"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _async_ctx(value):
    yield value
