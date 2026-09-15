# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.exceptions import AuthorizationError
from giljo_mcp.services.orchestration_agent_state_service import (
    OrchestrationAgentStateService,
)




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
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.info = {}
    svc._get_session = MagicMock(return_value=_ctx(mock_session))
    svc._job_repo.find_active_execution_for_job = AsyncMock(return_value=execution)
    svc._job_repo.get_agent_job_by_job_id = AsyncMock(return_value=job)
    svc._job_repo.get_project_by_id = AsyncMock(return_value=project)
    svc._job_repo.flush = AsyncMock()
    return mock_session




class TestStagingToImplementationFlow:


    @pytest.mark.asyncio
    async def test_layer1_set_agent_status_blocked_raises_staging_lock(self):
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
        assert execution.status == "working"

    @pytest.mark.asyncio
    async def test_layer1_set_agent_status_idle_raises_staging_lock(self):
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


    def test_layer1_bypass_report_progress_does_not_call_set_agent_status(self):
        import inspect

        from giljo_mcp.services import progress_service

        source = inspect.getsource(progress_service)
        assert "set_agent_status" not in source, (
            "progress_service must not call set_agent_status — "
            "staging lock would block orchestrator progress reporting during staging."
        )


    @pytest.mark.asyncio
    async def test_layer2_prompt_endpoint_returns_200_when_staging_complete_and_launched(self):
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

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        orch_result = MagicMock()
        orch_result.scalar_one_or_none.return_value = orchestrator_exec

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = [child_exec]

        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        templates_result = MagicMock()
        templates_result.all.return_value = []

        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}
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
            project_id="proj-impl-ready",
            current_user=user,
            db=db,
        )

        assert response is not None
        assert hasattr(response, "prompt")
        assert response.prompt

    @pytest.mark.asyncio
    async def test_layer2_prompt_endpoint_returns_200_with_blocked_orchestrator(self):
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
        orchestrator_exec.job_id = str(uuid4())
        orchestrator_exec.agent_display_name = "orchestrator"
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

        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        templates_result = MagicMock()
        templates_result.all.return_value = []

        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}
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
        from fastapi import HTTPException

        from api.endpoints import prompts

        project = MagicMock()
        project.staging_status = "staging"
        project.implementation_launched_at = None
        project.execution_mode = "claude_code_cli"

        result = MagicMock()
        result.scalar_one_or_none.return_value = project
        db = AsyncMock()
        db.info = {}
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



    @pytest.mark.asyncio
    async def test_layer2_prompt_still_200_when_orchestrator_history_was_blocked(self):
        from api.endpoints import prompts

        project = MagicMock()
        project.staging_status = "staging_complete"
        project.implementation_launched_at = datetime.now(UTC)
        project.execution_mode = "multi_terminal"
        project.id = "proj-blocked-history"
        project.tenant_key = "tenant-test"
        project.product = None

        orchestrator_exec = MagicMock()
        orchestrator_exec.agent_id = str(uuid4())
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

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        orch_result = MagicMock()
        orch_result.scalar_one_or_none.return_value = orchestrator_exec

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = [child_exec]

        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        templates_result = MagicMock()
        templates_result.all.return_value = []

        role_defaults_result = MagicMock()
        role_defaults_result.all.return_value = []

        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}
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




class TestSmokeReplay4b57c639:

    @pytest.mark.asyncio
    async def test_4b57c639_state_returns_200_not_404_idle_orchestrator(self):
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
        orchestrator_exec.job_id = "941fd26e-1111-1111-1111-111111111111"
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

        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        templates_result = MagicMock()
        templates_result.all.return_value = []

        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}
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
        assert hasattr(response, "prompt")
        assert response.prompt, "Implementation prompt must be non-empty"

    @pytest.mark.asyncio
    async def test_4b57c639_state_returns_200_not_404_blocked_orchestrator(self):
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
        orchestrator_exec.job_id = "941fd26e-1111-1111-1111-111111111111"
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

        settings_result = MagicMock()
        settings_result.scalar_one_or_none.return_value = None

        templates_result = MagicMock()
        templates_result.all.return_value = []

        chain_run_result = MagicMock()
        chain_run_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.info = {}
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
        import inspect

        from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

        src = inspect.getsource(ThinClientPromptGenerator.implement)
        orchestrator_block_start = src.find('agent_display_name == "orchestrator"')
        assert orchestrator_block_start >= 0, "orchestrator query block must exist"

        orchestrator_block = src[orchestrator_block_start : orchestrator_block_start + 400]
        assert 'status.in_(["waiting", "working"])' not in orchestrator_block, (
            "orchestrator query must no longer filter by active status — "
            "this was the root cause of the 4b57c639 broken flow"
        )
        assert "not_in" in orchestrator_block, "orchestrator query must use not_in for terminal statuses"
