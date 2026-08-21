# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Integration tests: BE-staging-lock — staging→implementation cross-layer flow.

Edition Scope: Both

Covers two scenarios:
  T2 — Full staging→implementation flow with orchestrator status churn.
       Tests Layer 1 (STAGING_LOCK guard), Layer 1 bypass (report_progress),
       and Layer 2 (prompt endpoint gate). CE-0026: Layer 5.5 staging_directive
       tests removed alongside the broadcast magic — coverage moved to
       tests/services/test_complete_job_state_machine.py.
  T3 — Test-install smoke replay for project 4b57c639 (2026-05-05 00:14:50
       broken flow). Asserts that the prompt endpoint returns 200 when
       staging_complete=True AND implementation_launched_at is set,
       regardless of orchestrator AgentExecution.status.

Live-server validation of T3 is explicitly deferred to the operator's server
restart (the test-install server runs pre-commit code in memory).
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.exceptions import AuthorizationError
from giljo_mcp.services.orchestration_agent_state_service import (
    OrchestrationAgentStateService,
)


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _ctx(value):
    yield value


def _make_state_service() -> OrchestrationAgentStateService:
    mock_db = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.get_current_tenant.return_value = "tenant-test"
    return OrchestrationAgentStateService(
        db_manager=mock_db,
        tenant_manager=mock_tenant,
    )


def _wire_state_service(svc, execution, job, project):
    """Wire the repo mocks on a state-service instance."""
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.info = {}  # tenant_session_context save/restore target
    svc._get_session = MagicMock(return_value=_ctx(mock_session))
    svc._job_repo.find_active_execution_for_job = AsyncMock(return_value=execution)
    svc._job_repo.get_agent_job_by_job_id = AsyncMock(return_value=job)
    svc._job_repo.get_project_by_id = AsyncMock(return_value=project)
    # BE-3006b: set_agent_status now flushes; the session owner commits.
    svc._job_repo.flush = AsyncMock()
    return mock_session


# ---------------------------------------------------------------------------
# T2 — Full staging→implementation flow with orchestrator status churn
# ---------------------------------------------------------------------------


class TestStagingToImplementationFlow:
    """Cross-layer integration: Layer 1 (set_agent_status lock) + Layer 2
    (prompt endpoint gate). CE-0026 removed the broadcast-magic staging
    directive; coverage moved to test_complete_job_state_machine.py.

    Scenario:
        Orchestrator waiting→working→idle→working→idle during staging.
        Each step through the state machine is verified in isolation to
        confirm cross-layer interactions hold.
    """

    # ------------------------------------------------------------------
    # Step 2: set_agent_status during staging → 403 STAGING_LOCK
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_layer1_set_agent_status_blocked_raises_staging_lock(self):
        """Layer 1 guard: orchestrator + staging_status='staging' → AuthorizationError STAGING_LOCK."""
        svc = _make_state_service()

        execution = MagicMock()
        execution.agent_display_name = "orchestrator"
        execution.agent_name = "orchestrator"
        execution.status = "working"

        job = MagicMock()
        job.project_id = "proj-staging"

        project = MagicMock()
        project.staging_status = "staging"

        _wire_state_service(svc, execution, job, project)

        with pytest.raises(AuthorizationError) as exc:
            await svc.set_agent_status(
                job_id="orch-job",
                status="blocked",
                reason="need user clarification",
                tenant_key="tenant-test",
            )

        assert exc.value.error_code == "STAGING_LOCK"
        assert exc.value.default_status_code == 403
        # Layer 1: execution.status must NOT have been mutated.
        assert execution.status == "working"

    @pytest.mark.asyncio
    async def test_layer1_set_agent_status_idle_raises_staging_lock(self):
        """Layer 1: idle transition also locked during staging."""
        svc = _make_state_service()

        execution = MagicMock()
        execution.agent_display_name = "orchestrator"
        execution.agent_name = "orchestrator"
        execution.status = "working"

        job = MagicMock()
        job.project_id = "proj-staging"

        project = MagicMock()
        project.staging_status = "staging"

        _wire_state_service(svc, execution, job, project)

        with pytest.raises(AuthorizationError) as exc:
            await svc.set_agent_status(
                job_id="orch-job",
                status="idle",
                tenant_key="tenant-test",
            )

        assert exc.value.error_code == "STAGING_LOCK"

    # ------------------------------------------------------------------
    # Step 3: report_progress bypasses the lock (Layer 1 bypass)
    # ------------------------------------------------------------------

    def test_layer1_bypass_report_progress_does_not_call_set_agent_status(self):
        """report_progress must not route through set_agent_status (staging bypass)."""
        import inspect

        from giljo_mcp.services import progress_service

        source = inspect.getsource(progress_service)
        assert "set_agent_status" not in source, (
            "progress_service must not call set_agent_status — "
            "staging lock would block orchestrator progress reporting during staging."
        )

    # ------------------------------------------------------------------
    # Step 5: GET /prompts/implementation/{project_id} after staging_complete
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_layer2_prompt_endpoint_returns_200_when_staging_complete_and_launched(self):
        """Layer 2: prompt endpoint returns 200 when staging_complete + implementation_launched_at set."""
        from api.endpoints import prompts

        project = MagicMock()
        project.staging_status = "staging_complete"
        project.implementation_launched_at = datetime.now(UTC)
        project.execution_mode = "claude_code_cli"
        project.id = "proj-impl-ready"
        project.tenant_key = "tenant-test"
        project.product = None

        orchestrator_exec = MagicMock()
        orchestrator_exec.agent_id = str(uuid4())
        # BE-6182: the endpoint now returns orchestrator_job_id = execution.job_id
        # (a real str), so the mock must set a distinct job_id (not just agent_id).
        orchestrator_exec.job_id = str(uuid4())
        orchestrator_exec.agent_display_name = "orchestrator"
        orchestrator_exec.status = "idle"
        orchestrator_exec.started_at = datetime.now(UTC)
        orchestrator_exec.job = MagicMock()

        child_exec = MagicMock()
        child_exec.agent_id = str(uuid4())
        child_exec.agent_display_name = "implementer"
        child_exec.status = "waiting"
        child_exec.started_at = datetime.now(UTC)
        child_exec.job = MagicMock()

        # DB call sequence:
        # 1. project lookup (joinedload)
        # 2. orchestrator execution lookup
        # 3. agent_executions by spawned_by (returns child)
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        orch_result = MagicMock()
        orch_result.scalar_one_or_none.return_value = orchestrator_exec

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = [child_exec]

        # 4th query: BE-9103 git toggle read (SettingsService.git_integration_enabled;
        # no settings row -> disabled)
        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        # 5th query: INF-6049c cli_tool resolution (empty -> agents default to "claude")
        templates_result = MagicMock()
        templates_result.all.return_value = []

        # BE-9335: implement() resolves the chain's execution mode right after loading
        # the project (a member runs in the CHAIN's mode). These are SOLO fixtures, so
        # the lookup must find no active run and fall back to the project column.
        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}  # tenant_session_context save/restore target
        db.execute = AsyncMock(
            side_effect=[
                project_result,
                chain_run_result,
                orch_result,
                agents_result,
                settings_result,
                templates_result,
            ]
        )

        user = MagicMock()
        user.tenant_key = "tenant-test"

        # Should not raise; returns an ImplementationPromptResponse
        response = await prompts.get_implementation_prompt(
            project_id="proj-impl-ready",
            current_user=user,
            db=db,
        )

        assert response is not None
        # The prompt body should be non-empty
        assert hasattr(response, "prompt")
        assert response.prompt

    @pytest.mark.asyncio
    async def test_layer2_prompt_endpoint_returns_200_with_blocked_orchestrator(self):
        """Layer 2: orchestrator in 'blocked' status still returns 200 (project-flag gate)."""
        from api.endpoints import prompts

        project = MagicMock()
        project.staging_status = "staging_complete"
        project.implementation_launched_at = datetime.now(UTC)
        project.execution_mode = "claude_code_cli"
        project.id = "proj-impl-blocked-orch"
        project.tenant_key = "tenant-test"
        project.product = None

        orchestrator_exec = MagicMock()
        orchestrator_exec.agent_id = str(uuid4())
        orchestrator_exec.job_id = str(uuid4())  # BE-6182: endpoint returns job_id, not agent_id
        orchestrator_exec.agent_display_name = "orchestrator"
        # Key: orchestrator is 'blocked' — old code would have returned 404
        orchestrator_exec.status = "blocked"
        orchestrator_exec.started_at = datetime.now(UTC)
        orchestrator_exec.job = MagicMock()

        child_exec = MagicMock()
        child_exec.agent_id = str(uuid4())
        child_exec.agent_display_name = "implementer"
        child_exec.status = "waiting"
        child_exec.started_at = datetime.now(UTC)
        child_exec.job = MagicMock()

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        orch_result = MagicMock()
        orch_result.scalar_one_or_none.return_value = orchestrator_exec

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = [child_exec]

        # 4th query: BE-9103 git toggle read (SettingsService.git_integration_enabled;
        # no settings row -> disabled)
        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        # 5th query: INF-6049c cli_tool resolution (empty -> agents default to "claude")
        templates_result = MagicMock()
        templates_result.all.return_value = []

        # BE-9335: implement() resolves the chain's execution mode right after loading
        # the project (a member runs in the CHAIN's mode). These are SOLO fixtures, so
        # the lookup must find no active run and fall back to the project column.
        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}  # tenant_session_context save/restore target
        db.execute = AsyncMock(
            side_effect=[
                project_result,
                chain_run_result,
                orch_result,
                agents_result,
                settings_result,
                templates_result,
            ]
        )

        user = MagicMock()
        user.tenant_key = "tenant-test"

        response = await prompts.get_implementation_prompt(
            project_id="proj-impl-blocked-orch",
            current_user=user,
            db=db,
        )

        assert response is not None
        assert hasattr(response, "prompt")
        assert response.prompt

    @pytest.mark.asyncio
    async def test_layer2_prompt_endpoint_returns_404_when_staging_incomplete(self):
        """Layer 2: staging_status != staging_complete → 404 (project-flag gate)."""
        from fastapi import HTTPException

        from api.endpoints import prompts

        project = MagicMock()
        project.staging_status = "staging"
        project.implementation_launched_at = None
        project.execution_mode = "claude_code_cli"

        result = MagicMock()
        result.scalar_one_or_none.return_value = project
        db = AsyncMock()
        db.info = {}  # tenant_session_context save/restore target
        db.execute = AsyncMock(return_value=result)

        user = MagicMock()
        user.tenant_key = "tenant-test"

        with pytest.raises(HTTPException) as exc:
            await prompts.get_implementation_prompt(
                project_id="proj-still-staging",
                current_user=user,
                db=db,
            )

        assert exc.value.status_code == 404

    # ------------------------------------------------------------------
    # CE-0026: Step 6 (broadcast STAGING_COMPLETE → staging_directive) DELETED.
    # The broadcast magic was removed; the staging-end signal moved to
    # complete_job. Coverage is now in tests/services/test_complete_job_state_machine.py
    # and tests/integration/test_complete_job_mcp_boundary.py.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Step 7: orchestrator still 'blocked' → prompt still 200 (regression guard)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_layer2_prompt_still_200_when_orchestrator_history_was_blocked(self):
        """Regression: prompt endpoint must return 200 even when orchestrator was blocked
        during staging (blocked-history scenario from project description)."""
        from api.endpoints import prompts

        project = MagicMock()
        project.staging_status = "staging_complete"
        project.implementation_launched_at = datetime.now(UTC)
        project.execution_mode = "multi_terminal"
        project.id = "proj-blocked-history"
        project.tenant_key = "tenant-test"
        project.product = None

        # Orchestrator was blocked during staging but is now 'idle' in implementation
        orchestrator_exec = MagicMock()
        orchestrator_exec.agent_id = str(uuid4())
        orchestrator_exec.job_id = str(uuid4())  # BE-6182: endpoint returns job_id, not agent_id
        orchestrator_exec.agent_display_name = "orchestrator"
        orchestrator_exec.status = "idle"
        orchestrator_exec.started_at = datetime.now(UTC)
        orchestrator_exec.job = MagicMock()

        child_exec = MagicMock()
        child_exec.agent_id = str(uuid4())
        child_exec.agent_display_name = "implementer"
        child_exec.status = "waiting"
        child_exec.started_at = datetime.now(UTC)
        child_exec.job = MagicMock()

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        orch_result = MagicMock()
        orch_result.scalar_one_or_none.return_value = orchestrator_exec

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = [child_exec]

        # 4th query: BE-9103 git toggle read (SettingsService.git_integration_enabled;
        # no settings row -> disabled)
        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        # 5th query: INF-6049c cli_tool resolution (empty -> agents unresolved by template_id)
        templates_result = MagicMock()
        templates_result.all.return_value = []

        # 6th query (BE-6204, multi_terminal only): role-default harness fallback for the
        # unresolved implementer. Empty -> the agent still defaults to "claude".
        role_defaults_result = MagicMock()
        role_defaults_result.all.return_value = []

        # BE-9335: implement() resolves the chain's execution mode right after loading
        # the project (a member runs in the CHAIN's mode). These are SOLO fixtures, so
        # the lookup must find no active run and fall back to the project column.
        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}  # tenant_session_context save/restore target
        db.execute = AsyncMock(
            side_effect=[
                project_result,
                chain_run_result,
                orch_result,
                agents_result,
                settings_result,
                templates_result,
                role_defaults_result,
            ]
        )

        user = MagicMock()
        user.tenant_key = "tenant-test"

        response = await prompts.get_implementation_prompt(
            project_id="proj-blocked-history",
            current_user=user,
            db=db,
        )

        assert response is not None
        assert response.prompt


# ---------------------------------------------------------------------------
# T3 — Test-install smoke replay: project 4b57c639 broken flow (2026-05-05 00:14:50)
#
# Live-server validation deferred to the operator's server restart.
# pytest validates code-state correctness only.
# ---------------------------------------------------------------------------


class TestSmokeReplay4b57c639:
    """Smoke replay for the real broken flow on 2026-05-05.

    Project 4b57c639-16b2-4bd5-86cf-b213c953c025 had:
    - staging_complete=True (staging_status='staging_complete')
    - implementation_launched_at set
    - orchestrator agent_id=941fd26e... with status 'idle' (or 'blocked')
    - prompt endpoint returned 404

    After BE-staging-lock Layer 2, the endpoint gate is on durable project flags,
    not transient AgentExecution.status, so 404 is impossible in this state.

    NOTE: Live-server validation requires the operator to restart the
    test-install server so the in-memory code is replaced with the committed
    Layer 2 code.
    """

    @pytest.mark.asyncio
    async def test_4b57c639_state_returns_200_not_404_idle_orchestrator(self):
        """Mirroring 4b57c639 state at 00:14:50: staging_complete=True,
        implementation_launched_at set, orchestrator status='idle' → 200."""
        from api.endpoints import prompts

        project = MagicMock()
        project.id = "4b57c639-16b2-4bd5-86cf-b213c953c025"
        project.tenant_key = "tenant-test-install"
        project.staging_status = "staging_complete"
        project.implementation_launched_at = datetime(2026, 5, 5, 0, 10, 0, tzinfo=UTC)
        project.execution_mode = "claude_code_cli"
        project.product = None

        # Mirroring the real orchestrator state
        orchestrator_exec = MagicMock()
        orchestrator_exec.agent_id = "941fd26e-0000-0000-0000-000000000000"
        orchestrator_exec.job_id = "941fd26e-1111-1111-1111-111111111111"  # BE-6182: distinct job_id
        orchestrator_exec.agent_display_name = "orchestrator"
        orchestrator_exec.status = "idle"
        orchestrator_exec.started_at = datetime(2026, 5, 5, 0, 5, 0, tzinfo=UTC)
        orchestrator_exec.job = MagicMock()

        child_exec = MagicMock()
        child_exec.agent_id = str(uuid4())
        child_exec.agent_display_name = "implementer"
        child_exec.status = "waiting"
        child_exec.started_at = datetime(2026, 5, 5, 0, 9, 0, tzinfo=UTC)
        child_exec.job = MagicMock()

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        orch_result = MagicMock()
        orch_result.scalar_one_or_none.return_value = orchestrator_exec

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = [child_exec]

        # 4th query: BE-9103 git toggle read (SettingsService.git_integration_enabled;
        # no settings row -> disabled)
        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        # 5th query: INF-6049c cli_tool resolution (empty -> agents default to "claude")
        templates_result = MagicMock()
        templates_result.all.return_value = []

        # BE-9335: implement() resolves the chain's execution mode right after loading
        # the project (a member runs in the CHAIN's mode). These are SOLO fixtures, so
        # the lookup must find no active run and fall back to the project column.
        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}  # tenant_session_context save/restore target
        db.execute = AsyncMock(
            side_effect=[
                project_result,
                chain_run_result,
                orch_result,
                agents_result,
                settings_result,
                templates_result,
            ]
        )

        user = MagicMock()
        user.tenant_key = "tenant-test-install"

        # Must return 200 — NOT raise HTTPException 404
        response = await prompts.get_implementation_prompt(
            project_id="4b57c639-16b2-4bd5-86cf-b213c953c025",
            current_user=user,
            db=db,
        )

        assert response is not None
        assert hasattr(response, "prompt")
        assert response.prompt, "Implementation prompt must be non-empty"

    @pytest.mark.asyncio
    async def test_4b57c639_state_returns_200_not_404_blocked_orchestrator(self):
        """Variant: orchestrator status='blocked' (also present in broken flow)."""
        from api.endpoints import prompts

        project = MagicMock()
        project.id = "4b57c639-16b2-4bd5-86cf-b213c953c025"
        project.tenant_key = "tenant-test-install"
        project.staging_status = "staging_complete"
        project.implementation_launched_at = datetime(2026, 5, 5, 0, 10, 0, tzinfo=UTC)
        project.execution_mode = "claude_code_cli"
        project.product = None

        orchestrator_exec = MagicMock()
        orchestrator_exec.agent_id = "941fd26e-0000-0000-0000-000000000000"
        orchestrator_exec.job_id = "941fd26e-1111-1111-1111-111111111111"  # BE-6182: distinct job_id
        orchestrator_exec.agent_display_name = "orchestrator"
        orchestrator_exec.status = "blocked"
        orchestrator_exec.started_at = datetime(2026, 5, 5, 0, 5, 0, tzinfo=UTC)
        orchestrator_exec.job = MagicMock()

        child_exec = MagicMock()
        child_exec.agent_id = str(uuid4())
        child_exec.agent_display_name = "implementer"
        child_exec.status = "waiting"
        child_exec.started_at = datetime(2026, 5, 5, 0, 9, 0, tzinfo=UTC)
        child_exec.job = MagicMock()

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        orch_result = MagicMock()
        orch_result.scalar_one_or_none.return_value = orchestrator_exec

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = [child_exec]

        # 4th query: BE-9103 git toggle read (SettingsService.git_integration_enabled;
        # no settings row -> disabled)
        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        # 5th query: INF-6049c cli_tool resolution (empty -> agents default to "claude")
        templates_result = MagicMock()
        templates_result.all.return_value = []

        # BE-9335: implement() resolves the chain's execution mode right after loading
        # the project (a member runs in the CHAIN's mode). These are SOLO fixtures, so
        # the lookup must find no active run and fall back to the project column.
        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}  # tenant_session_context save/restore target
        db.execute = AsyncMock(
            side_effect=[
                project_result,
                chain_run_result,
                orch_result,
                agents_result,
                settings_result,
                templates_result,
            ]
        )

        user = MagicMock()
        user.tenant_key = "tenant-test-install"

        response = await prompts.get_implementation_prompt(
            project_id="4b57c639-16b2-4bd5-86cf-b213c953c025",
            current_user=user,
            db=db,
        )

        assert response is not None
        assert response.prompt, "Implementation prompt must be non-empty"

    def test_4b57c639_old_query_pattern_would_have_returned_empty(self):
        """Documents why the old query returned 404: it filtered by status='working'
        and the orchestrator was 'idle'. This test verifies the old pattern is gone.

        INF-6049b: the orchestrator query moved from the REST endpoint into the
        shared core ThinClientPromptGenerator.implement (driven by both the REST
        endpoint and the implement_project MCP tool); inspect it there."""
        import inspect

        from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

        src = inspect.getsource(ThinClientPromptGenerator.implement)
        orchestrator_block_start = src.find('agent_display_name == "orchestrator"')
        assert orchestrator_block_start >= 0, "orchestrator query block must exist"

        orchestrator_block = src[orchestrator_block_start : orchestrator_block_start + 400]
        # The old status.in_(["waiting", "working"]) filter must be gone
        assert 'status.in_(["waiting", "working"])' not in orchestrator_block, (
            "orchestrator query must no longer filter by active status — "
            "this was the root cause of the 4b57c639 broken flow"
        )
        # New pattern: exclude terminal statuses instead
        assert "not_in" in orchestrator_block, "orchestrator query must use not_in for terminal statuses"
