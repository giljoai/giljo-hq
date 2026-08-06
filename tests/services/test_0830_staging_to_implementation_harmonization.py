# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Test suite for Handover 0830: Orchestrator Staging-to-Implementation Harmonization.

Covers 6 changes:
1. Thin prompt stripped to <=15 lines
2. agent_identity populated for orchestrator
3. Orchestrator protocol fork (3-phase vs 5-phase)
4. current_team_state in MissionResponse
5. implementation_launched_at phase gate for orchestrator
6. get_staging_instructions redirect branches on implementation_launched_at
"""

import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.schemas.service_responses import MissionResponse
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.protocol_builder import _generate_agent_protocol
from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator


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
def orchestration_service(mock_db_manager, mock_tenant_manager):
    """Create OrchestrationService with mocked dependencies."""
    db_manager, _ = mock_db_manager
    return OrchestrationService(db_manager=db_manager, tenant_manager=mock_tenant_manager)


@pytest.fixture
def sample_project():
    """Create a mock project for prompt testing."""
    project = MagicMock()
    project.name = "Test Project"
    project.id = str(uuid4())
    return project


# ---------------------------------------------------------------------------
# Change 1: Thin prompt stripped to <=15 lines
# ---------------------------------------------------------------------------


class TestThinPromptStrippedToFifteenLines:
    """Verify _build_multi_terminal_orchestrator_prompt is genuinely thin."""

    def _generate_prompt(self, project) -> str:
        """Helper to generate orchestrator prompt via ThinClientPromptGenerator."""
        mock_session = AsyncMock()
        gen = ThinClientPromptGenerator(db=mock_session, tenant_key="tenant-test")
        orchestrator_id = str(uuid4())
        return gen.generate_implementation_prompt(
            prompt_type="multi_terminal_orchestrator",
            orchestrator_id=orchestrator_id,
            project=project,
            agent_jobs=[],
        )

    def test_output_is_at_most_15_lines(self, sample_project):
        prompt = self._generate_prompt(sample_project)
        line_count = len(prompt.strip().splitlines())
        assert line_count <= 15, f"Prompt has {line_count} lines, expected <=15"

    def test_contains_health_check(self, sample_project):
        prompt = self._generate_prompt(sample_project)
        assert "health_check" in prompt

    def test_contains_job_id_and_project_id(self, sample_project):
        prompt = self._generate_prompt(sample_project)
        assert str(sample_project.id) in prompt, "Prompt must contain project_id"
        # job_id is the orchestrator_id passed in — it appears as Job ID in the prompt
        assert "Job ID:" in prompt

    def test_contains_get_job_mission_call(self, sample_project):
        prompt = self._generate_prompt(sample_project)
        assert "get_job_mission" in prompt

    def test_does_not_contain_team_roster(self, sample_project):
        prompt = self._generate_prompt(sample_project)
        assert "YOUR TEAM" not in prompt
        assert "Agent |" not in prompt

    def test_does_not_contain_behavioral_protocol(self, sample_project):
        prompt = self._generate_prompt(sample_project)
        assert "Phase 1: STARTUP" not in prompt
        assert "Phase 2: EXECUTION" not in prompt
        assert "lifecycle" not in prompt.lower()

    def test_does_not_contain_tool_catalog(self, sample_project):
        prompt = self._generate_prompt(sample_project)
        assert "report_progress" not in prompt
        assert "complete_job" not in prompt
        assert "send_message" not in prompt

    def test_does_not_contain_closeout_instructions(self, sample_project):
        prompt = self._generate_prompt(sample_project)
        assert "write_360_memory" not in prompt
        assert "CLOSEOUT" not in prompt


# ---------------------------------------------------------------------------
# Change 2: agent_identity populated for orchestrator
# ---------------------------------------------------------------------------


class TestOrchestratorIdentityPopulated:
    """Verify get_job_mission sets hardcoded identity for orchestrator."""

    @pytest.mark.asyncio
    async def test_orchestrator_identity_is_non_null(self, orchestration_service, mock_db_manager):
        _db_manager, session = mock_db_manager
        job_id = str(uuid4())
        project_id = str(uuid4())

        job = AgentJob(
            job_id=job_id,
            tenant_key="tenant-test",
            project_id=project_id,
            mission="Coordinate implementation",
            job_type="orchestrator",
            status="active",
            created_at=datetime.now(UTC),
        )

        execution = AgentExecution(
            job_id=job_id,
            agent_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_display_name="orchestrator",
            agent_name="orchestrator-1",
            status="waiting",
        )

        project = Project(
            id=project_id,
            tenant_key="tenant-test",
            name="Test Project",
            description="Test desc",
            mission="Test mission",
            status="active",
            execution_mode="multi_terminal",
            auto_checkin_enabled=True,
            auto_checkin_interval=10,
            implementation_launched_at=datetime.now(UTC),
            series_number=random.randint(1, 9000),
        )

        job_result = MagicMock()
        job_result.scalar_one_or_none = MagicMock(return_value=job)
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=execution)
        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)
        all_exec_result = MagicMock()
        all_exec_result.all = MagicMock(return_value=[(execution, job)])
        # HO1027: extra reads for orchestrator identity composition —
        # _resolve_mission_template fetches project (5th) + orchestrator
        # prompt override row (6th).
        project_again_result = MagicMock()
        project_again_result.scalar_one_or_none = MagicMock(return_value=project)
        override_result = MagicMock()
        override_result.scalar_one_or_none = MagicMock(return_value=None)

        session.execute = AsyncMock(
            side_effect=[
                job_result,
                exec_result,
                project_result,
                all_exec_result,
                project_again_result,
                override_result,
            ]
        )

        response = await orchestration_service.get_agent_mission(job_id=job_id, tenant_key="tenant-test")

        assert response.agent_identity is not None, "Orchestrator identity must be set"

    @pytest.mark.asyncio
    async def test_orchestrator_identity_contains_orchestrator_keyword(self, orchestration_service, mock_db_manager):
        _db_manager, session = mock_db_manager
        job_id = str(uuid4())
        project_id = str(uuid4())

        job = AgentJob(
            job_id=job_id,
            tenant_key="tenant-test",
            project_id=project_id,
            mission="Coordinate implementation",
            job_type="orchestrator",
            status="active",
            created_at=datetime.now(UTC),
        )

        execution = AgentExecution(
            job_id=job_id,
            agent_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_display_name="orchestrator",
            agent_name="orchestrator-1",
            status="waiting",
        )

        project = Project(
            id=project_id,
            tenant_key="tenant-test",
            name="Test Project",
            description="Test desc",
            mission="Test mission",
            status="active",
            execution_mode="multi_terminal",
            auto_checkin_enabled=True,
            auto_checkin_interval=10,
            implementation_launched_at=datetime.now(UTC),
            series_number=random.randint(1, 9000),
        )

        job_result = MagicMock()
        job_result.scalar_one_or_none = MagicMock(return_value=job)
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=execution)
        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)
        all_exec_result = MagicMock()
        all_exec_result.all = MagicMock(return_value=[(execution, job)])

        # HO1027: extra mocks for project+override re-reads in identity composition.
        project_again_result = MagicMock()
        project_again_result.scalar_one_or_none = MagicMock(return_value=project)
        override_result = MagicMock()
        override_result.scalar_one_or_none = MagicMock(return_value=None)

        session.execute = AsyncMock(
            side_effect=[
                job_result,
                exec_result,
                project_result,
                all_exec_result,
                project_again_result,
                override_result,
            ]
        )

        response = await orchestration_service.get_agent_mission(job_id=job_id, tenant_key="tenant-test")

        assert "ORCHESTRATOR" in response.agent_identity

    @pytest.mark.asyncio
    async def test_orchestrator_identity_contains_behavioral_phrases(self, orchestration_service, mock_db_manager):
        """Handover 0966: Identity now comes from get_orchestrator_identity_content()
        instead of a 6-line hardcoded fallback. Verify it contains the key behavioral
        concepts: coordination role, mission breakdown, and agent coordination."""
        _db_manager, session = mock_db_manager
        job_id = str(uuid4())
        project_id = str(uuid4())

        job = AgentJob(
            job_id=job_id,
            tenant_key="tenant-test",
            project_id=project_id,
            mission="Coordinate implementation",
            job_type="orchestrator",
            status="active",
            created_at=datetime.now(UTC),
        )

        execution = AgentExecution(
            job_id=job_id,
            agent_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_display_name="orchestrator",
            agent_name="orchestrator-1",
            status="waiting",
        )

        project = Project(
            id=project_id,
            tenant_key="tenant-test",
            name="Test Project",
            description="Test desc",
            mission="Test mission",
            status="active",
            execution_mode="multi_terminal",
            auto_checkin_enabled=True,
            auto_checkin_interval=10,
            implementation_launched_at=datetime.now(UTC),
            series_number=random.randint(1, 9000),
        )

        job_result = MagicMock()
        job_result.scalar_one_or_none = MagicMock(return_value=job)
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=execution)
        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)
        all_exec_result = MagicMock()
        all_exec_result.all = MagicMock(return_value=[(execution, job)])

        # HO1027: extra mocks for project+override re-reads in identity composition.
        project_again_result = MagicMock()
        project_again_result.scalar_one_or_none = MagicMock(return_value=project)
        override_result = MagicMock()
        override_result.scalar_one_or_none = MagicMock(return_value=None)

        session.execute = AsyncMock(
            side_effect=[
                job_result,
                exec_result,
                project_result,
                all_exec_result,
                project_again_result,
                override_result,
            ]
        )

        response = await orchestration_service.get_agent_mission(job_id=job_id, tenant_key="tenant-test")

        identity = response.agent_identity
        assert "coordinate" in identity.lower(), "Identity must mention coordination"
        assert "mission breakdown" in identity.lower() or "agent coordination" in identity.lower(), (
            "Identity must describe orchestrator responsibilities"
        )


# ---------------------------------------------------------------------------
# Change 3: Orchestrator protocol fork
# ---------------------------------------------------------------------------


class TestOrchestratorProtocolFork:
    """Verify _generate_agent_protocol returns 3-phase for orchestrator, 5-phase for worker."""

    def test_orchestrator_returns_three_phase_protocol(self):
        protocol = _generate_agent_protocol(
            job_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_name="orchestrator-1",
            agent_id=str(uuid4()),
            job_type="orchestrator",
        )
        assert "PHASE 1" in protocol
        assert "PHASE 2" in protocol
        assert "PHASE 3" in protocol

    def test_orchestrator_protocol_does_not_contain_worker_phases(self):
        protocol = _generate_agent_protocol(
            job_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_name="orchestrator-1",
            agent_id=str(uuid4()),
            job_type="orchestrator",
        )
        assert "Phase 4: COMPLETION" not in protocol
        assert "Phase 5: ERROR HANDLING" not in protocol

    def test_orchestrator_protocol_contains_todo_append(self):
        protocol = _generate_agent_protocol(
            job_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_name="orchestrator-1",
            agent_id=str(uuid4()),
            job_type="orchestrator",
        )
        assert "todo_append" in protocol

    def test_orchestrator_protocol_contains_never_todo_items_warning(self):
        protocol = _generate_agent_protocol(
            job_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_name="orchestrator-1",
            agent_id=str(uuid4()),
            job_type="orchestrator",
        )
        assert "NEVER" in protocol
        assert "todo_items" in protocol

    def test_worker_returns_five_phase_protocol(self):
        """Regression check: worker agents still get the 5-phase lifecycle."""
        protocol = _generate_agent_protocol(
            job_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_name="implementer-1",
            agent_id=str(uuid4()),
            job_type="agent",
        )
        assert "Phase 1: STARTUP" in protocol
        assert "Phase 2: EXECUTION" in protocol
        assert "Phase 3: PROGRESS REPORTING" in protocol
        assert "Phase 4: COMPLETION" in protocol
        assert "Phase 5: ERROR HANDLING" in protocol

    def test_orchestrator_protocol_has_startup_reactive_closeout_labels(self):
        protocol = _generate_agent_protocol(
            job_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_name="orchestrator-1",
            agent_id=str(uuid4()),
            job_type="orchestrator",
        )
        assert "STARTUP" in protocol
        assert "ACTIVE COORDINATION" in protocol
        assert "CLOSEOUT" in protocol


# ---------------------------------------------------------------------------
# Change 4: current_team_state in MissionResponse
# ---------------------------------------------------------------------------


class TestMissionResponseCurrentTeamState:
    """Verify MissionResponse schema accepts and serializes current_team_state."""

    def test_accepts_current_team_state_field(self):
        team_state = [
            {"agent_id": "abc", "status": "active", "role": "implementer"},
            {"agent_id": "def", "status": "waiting", "role": "tester"},
        ]
        response = MissionResponse(job_id="j1", current_team_state=team_state)
        assert response.current_team_state == team_state

    def test_current_team_state_defaults_to_none(self):
        response = MissionResponse(job_id="j1")
        assert response.current_team_state is None

    def test_current_team_state_serializes_with_model_dump(self):
        team_state = [{"agent_id": "abc", "status": "active"}]
        response = MissionResponse(job_id="j1", current_team_state=team_state)
        dumped = response.model_dump()
        assert "current_team_state" in dumped
        assert dumped["current_team_state"] == team_state

    def test_current_team_state_none_serializes_correctly(self):
        response = MissionResponse(job_id="j1")
        dumped = response.model_dump()
        assert dumped["current_team_state"] is None


# ---------------------------------------------------------------------------
# Change 5: implementation_launched_at phase gate for orchestrator
# ---------------------------------------------------------------------------


class TestOrchestratorPhaseGate:
    """Verify orchestrator-specific blocked message when implementation not launched."""

    @pytest.mark.asyncio
    async def test_orchestrator_blocked_when_implementation_not_launched(self, orchestration_service, mock_db_manager):
        _db_manager, session = mock_db_manager
        job_id = str(uuid4())
        project_id = str(uuid4())

        job = AgentJob(
            job_id=job_id,
            tenant_key="tenant-test",
            project_id=project_id,
            mission="Coordinate",
            job_type="orchestrator",
            status="active",
            created_at=datetime.now(UTC),
        )

        execution = AgentExecution(
            job_id=job_id,
            agent_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_display_name="orchestrator",
            agent_name="orchestrator-1",
            status="waiting",
        )

        project = Project(
            id=project_id,
            tenant_key="tenant-test",
            name="Test Project",
            description="Test desc",
            mission="Test mission",
            status="active",
            execution_mode="multi_terminal",
            implementation_launched_at=None,
            series_number=random.randint(1, 9000),
        )

        job_result = MagicMock()
        job_result.scalar_one_or_none = MagicMock(return_value=job)
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=execution)
        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)

        session.execute = AsyncMock(side_effect=[job_result, exec_result, project_result])

        response = await orchestration_service.get_agent_mission(job_id=job_id, tenant_key="tenant-test")

        assert response.blocked is True
        assert response.mission is None
        assert response.full_protocol is None
        assert "BLOCKED" in (response.error or "")

    @pytest.mark.asyncio
    async def test_orchestrator_blocked_message_mentions_dashboard_and_implement(
        self, orchestration_service, mock_db_manager
    ):
        _db_manager, session = mock_db_manager
        job_id = str(uuid4())
        project_id = str(uuid4())

        job = AgentJob(
            job_id=job_id,
            tenant_key="tenant-test",
            project_id=project_id,
            mission="Coordinate",
            job_type="orchestrator",
            status="active",
            created_at=datetime.now(UTC),
        )

        execution = AgentExecution(
            job_id=job_id,
            agent_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_display_name="orchestrator",
            agent_name="orchestrator-1",
            status="waiting",
        )

        project = Project(
            id=project_id,
            tenant_key="tenant-test",
            name="Test Project",
            description="Test desc",
            mission="Test mission",
            status="active",
            execution_mode="multi_terminal",
            implementation_launched_at=None,
            series_number=random.randint(1, 9000),
        )

        job_result = MagicMock()
        job_result.scalar_one_or_none = MagicMock(return_value=job)
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=execution)
        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)

        session.execute = AsyncMock(side_effect=[job_result, exec_result, project_result])

        response = await orchestration_service.get_agent_mission(job_id=job_id, tenant_key="tenant-test")

        assert "dashboard" in response.user_instruction.lower()
        assert "Implement" in response.user_instruction


# ---------------------------------------------------------------------------
# Change 6: get_staging_instructions redirect branches
# ---------------------------------------------------------------------------


class TestGetOrchestratorInstructionsRedirectBranches:
    """Verify redirect logic based on implementation_launched_at."""

    def _make_fixtures(self, *, implementation_launched_at):
        """Build job, execution, and project with given launch timestamp."""
        job_id = str(uuid4())
        project_id = str(uuid4())

        job = AgentJob(
            job_id=job_id,
            tenant_key="tenant-test",
            project_id=project_id,
            mission="Orchestrate",
            job_type="orchestrator",
            status="active",
            created_at=datetime.now(UTC),
        )

        execution = AgentExecution(
            job_id=job_id,
            agent_id=str(uuid4()),
            tenant_key="tenant-test",
            agent_display_name="orchestrator",
            agent_name="orchestrator-1",
            status="active",
        )

        project = Project(
            id=project_id,
            tenant_key="tenant-test",
            name="Redirect Test Project",
            description="Test desc",
            mission="Test mission",
            status="active",
            execution_mode="multi_terminal",
            staging_status="staging_complete",
            implementation_launched_at=implementation_launched_at,
            series_number=random.randint(1, 9000),
        )

        return job_id, job, execution, project

    def _mock_session_for_get_staging_instructions(self, session, execution, project):
        """Wire session.execute for the get_staging_instructions query pattern."""
        # First query: AgentExecution with joined AgentJob
        exec_scalars = MagicMock()
        exec_scalars.first = MagicMock(return_value=execution)
        exec_result = MagicMock()
        exec_result.scalars = MagicMock(return_value=exec_scalars)

        # Second query: Project lookup
        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)

        session.execute = AsyncMock(side_effect=[exec_result, project_result])

    @pytest.mark.asyncio
    async def test_redirect_to_get_job_mission_when_launched(self, orchestration_service, mock_db_manager):
        """When implementation_launched_at IS NOT NULL, returns redirect=get_job_mission."""
        _, session = mock_db_manager
        job_id, job, execution, project = self._make_fixtures(
            implementation_launched_at=datetime.now(UTC),
        )
        # Wire execution.job to return the AgentJob
        execution.job = job

        self._mock_session_for_get_staging_instructions(session, execution, project)

        result = await orchestration_service._mission.get_staging_instructions(job_id=job_id, tenant_key="tenant-test")

        assert result["staging_complete"] is True
        assert result["redirect"] == "get_job_mission"
        assert "already launched" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_no_redirect_when_not_launched(self, orchestration_service, mock_db_manager):
        """When implementation_launched_at IS NULL, returns redirect=None."""
        _, session = mock_db_manager
        job_id, job, execution, project = self._make_fixtures(
            implementation_launched_at=None,
        )
        execution.job = job

        self._mock_session_for_get_staging_instructions(session, execution, project)

        result = await orchestration_service._mission.get_staging_instructions(job_id=job_id, tenant_key="tenant-test")

        assert result["staging_complete"] is True
        assert result["redirect"] is None
        assert "click Implement" in result["message"]

    @pytest.mark.asyncio
    async def test_launched_response_contains_identity_fields(self, orchestration_service, mock_db_manager):
        """Redirect response includes job_id, project_id, project_name."""
        _, session = mock_db_manager
        job_id, job, execution, project = self._make_fixtures(
            implementation_launched_at=datetime.now(UTC),
        )
        execution.job = job

        self._mock_session_for_get_staging_instructions(session, execution, project)

        result = await orchestration_service._mission.get_staging_instructions(job_id=job_id, tenant_key="tenant-test")

        identity = result["identity"]
        assert identity["job_id"] == job_id
        assert identity["project_id"] == str(project.id)
        assert identity["project_name"] == project.name

    @pytest.mark.asyncio
    async def test_not_launched_response_contains_identity_fields(self, orchestration_service, mock_db_manager):
        """Not-launched response also includes identity fields."""
        _, session = mock_db_manager
        job_id, job, execution, project = self._make_fixtures(
            implementation_launched_at=None,
        )
        execution.job = job

        self._mock_session_for_get_staging_instructions(session, execution, project)

        result = await orchestration_service._mission.get_staging_instructions(job_id=job_id, tenant_key="tenant-test")

        identity = result["identity"]
        assert identity["job_id"] == job_id
        assert identity["project_id"] == str(project.id)
        assert identity["project_name"] == project.name


# ---------------------------------------------------------------------------
# BE-staging-lock Layer 2: Decouple downstream consumers from AgentExecution.status
# ---------------------------------------------------------------------------


class TestImplementationPromptGateUsesProjectFlags:
    """get_implementation_prompt is gated on durable project flags, not transient
    AgentExecution.status (BE-staging-lock Layer 2).
    """

    def _source(self) -> str:
        # INF-6049b: the orchestrator/agent query + the human gate were extracted
        # from the REST endpoint into the shared core (ThinClientPromptGenerator.
        # implement) + the shared gate fn (ProjectStagingService.
        # check_implementation_allowed), both called by the REST endpoint AND the
        # implement_project MCP tool. Inspect those — that is where the logic lives.
        import inspect

        from giljo_mcp.services.project_staging_service import ProjectStagingService
        from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

        return inspect.getsource(ThinClientPromptGenerator.implement) + inspect.getsource(
            ProjectStagingService.check_implementation_allowed
        )

    def test_orchestrator_query_uses_terminal_status_exclusion_not_active_inclusion(self):
        """Orchestrator selection no longer gates on active status — it only excludes
        terminal statuses. The spawned-agent fallback may still use status.in_ separately;
        this test is scoped to the orchestrator query block.
        """
        from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES

        src = self._source()
        idx = src.find('agent_display_name == "orchestrator"')
        assert idx >= 0, "orchestrator query block missing"
        orchestrator_block = src[idx : idx + 400]
        assert 'status.in_(["waiting", "working"])' not in orchestrator_block
        assert "status.not_in" in orchestrator_block
        # BE-9304 (changed deliberately): this block used to hand-write the three
        # statuses, and the next three assertions matched that literal text. It now
        # binds to the ONE shared constant. Pinning the constant BY NAME plus its
        # VALUE is strictly stronger than the old substring checks, which also passed
        # for a literal that dropped a status or carried an extra one — this very
        # query carried a fourth element ("failed") that no other site did, which is
        # the drift BE-9304 removed.
        assert "TERMINAL_EXECUTION_STATUSES" in orchestrator_block
        assert set(TERMINAL_EXECUTION_STATUSES) == {"complete", "closed", "decommissioned"}

    def test_gate_checks_staging_complete_flag(self):
        src = self._source()
        assert "staging_status" in src
        assert "staging_complete" in src

    def test_gate_checks_implementation_launched_at(self):
        src = self._source()
        assert "implementation_launched_at" in src

    @pytest.mark.asyncio
    async def test_gate_returns_404_when_staging_incomplete(self):
        from fastapi import HTTPException

        from api.endpoints import prompts

        project = MagicMock()
        project.staging_status = "staging"
        project.implementation_launched_at = None
        project.execution_mode = "claude_code_cli"

        result = MagicMock()
        result.scalar_one_or_none.return_value = project
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        user = MagicMock()
        user.tenant_key = "tenant-test"

        with pytest.raises(HTTPException) as exc_info:
            await prompts.get_implementation_prompt(project_id="proj-1", current_user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_gate_returns_404_when_implementation_not_launched(self):
        from fastapi import HTTPException

        from api.endpoints import prompts

        project = MagicMock()
        project.staging_status = "staging_complete"
        project.implementation_launched_at = None
        project.execution_mode = "claude_code_cli"

        result = MagicMock()
        result.scalar_one_or_none.return_value = project
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        user = MagicMock()
        user.tenant_key = "tenant-test"

        with pytest.raises(HTTPException) as exc_info:
            await prompts.get_implementation_prompt(project_id="proj-1", current_user=user, db=db)
        assert exc_info.value.status_code == 404


# CE-0026: TestStagingDirectiveUsesProjectFlag and TestStagingDirectiveDiagnosticStatuses
# were deleted here — the _check_staging_broadcast_directive method they exercised was
# removed alongside the broadcast magic. Coverage of the staging-end signal is now in
# tests/services/test_complete_job_state_machine.py (which tests the new complete_job
# path that replaces the broadcast).


# ---------------------------------------------------------------------------
# BE-staging-lock Layer 3: Protocol injection rewrites (snapshot tests)
# ---------------------------------------------------------------------------


class TestStagingLockProtocolRewrites:
    """Snapshot/contains assertions on the rewritten protocol text.

    See docs/protocol_injection_audit_2026_05_05.md for the full audit and the
    REWRITE / REFRAME / ADD-LOCK-NOTE classification.
    """

    def test_orchestrator_template_unclear_reqs_uses_inline_ask(self):
        """orchestrator template's 'If Requirements Are Unclear' replaces the
        set_agent_status call with inline-ask + report_progress."""
        from giljo_mcp.template_seeder import _get_default_templates_v103

        orch = next(t for t in _get_default_templates_v103() if t["role"] == "orchestrator")
        body = orch["user_instructions"]

        unclear_idx = body.find("## If Requirements Are Unclear")
        assert unclear_idx >= 0, "missing 'If Requirements Are Unclear' section"
        next_section_idx = body.find("##", unclear_idx + 5)
        section = body[unclear_idx:next_section_idx] if next_section_idx > 0 else body[unclear_idx:]

        assert 'set_agent_status(job_id, status="blocked"' not in section, (
            "old set_agent_status instruction must be removed from orchestrator staging section"
        )
        assert "inline" in section.lower()
        assert "STAGING_LOCK" in section
        assert "report_progress" in section
        assert "get_thread_history" in section  # BE-9012d: bus retired, Hub replaces it

    def test_ch4_error_handling_splits_staging_vs_implementation(self):
        """CH4 ERROR HANDLING status diagram splits into staging vs implementation
        and removes the working→blocked arrow from the staging variant."""
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch4_error_handling

        ch4 = _build_ch4_error_handling()

        assert "Staging phase" in ch4
        assert "Implementation phase" in ch4
        assert "STAGING_LOCK" in ch4

        staging_idx = ch4.find("Staging phase")
        implementation_idx = ch4.find("Implementation phase")
        assert staging_idx < implementation_idx, "staging phase should come first"
        staging_block = ch4[staging_idx:implementation_idx]
        # The forbidden working→blocked arrow MUST NOT appear in the staging block.
        assert 'set_agent_status("blocked")' not in staging_block
        assert 'set_agent_status("idle")' not in staging_block
        assert 'set_agent_status("sleeping")' not in staging_block

        implementation_block = ch4[implementation_idx:]
        # The full transition set is only in the implementation variant.
        assert 'set_agent_status("blocked")' in implementation_block
        assert 'set_agent_status("idle")' in implementation_block
        assert 'set_agent_status("sleeping")' in implementation_block

    def test_ch4_error_actions_no_longer_call_set_agent_status_during_staging(self):
        """The 'MCP Connection Lost' and 'Spawn Failure' actions no longer instruct
        the orchestrator to call set_agent_status during staging."""
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch4_error_handling

        ch4 = _build_ch4_error_handling()

        # Bracket each section by the next "──" line that opens a NEW section.
        # The opening dashes after the section title aren't followed by another title,
        # so search for the next " ── " preceded by a newline.
        def _section(text: str, title: str) -> str:
            start = text.find(title)
            assert start >= 0, f"section {title!r} not found"
            end = text.find("\n── ", start + len(title))
            return text[start : end if end > 0 else len(text)]

        mcp_block = _section(ch4, "MCP Connection Lost")
        # No instruction to CALL set_agent_status — the tool may still be
        # mentioned (to explain the lock).
        assert "Call set_agent_status(" not in mcp_block
        assert 'set_agent_status(job_id, status="blocked"' not in mcp_block
        assert "STAGING_LOCK" in mcp_block or "inline" in mcp_block.lower()

        spawn_block = _section(ch4, "Spawn Failure")
        assert 'set_agent_status(status="blocked")' not in spawn_block
        assert "Log via set_agent_status" not in spawn_block
        assert "inline" in spawn_block.lower() or "USER" in spawn_block

    def test_ch4_general_error_protocol_carves_out_staging(self):
        """GENERAL ERROR PROTOCOL step 2 must carve out the staging-orchestrator path."""
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch4_error_handling

        ch4 = _build_ch4_error_handling()
        general_idx = ch4.find("GENERAL ERROR PROTOCOL")
        assert general_idx >= 0
        general_block = ch4[general_idx : general_idx + 800]
        assert "Staging phase" in general_block or "STAGING_LOCK" in general_block
        assert "Implementation phase" in general_block or "implementation" in general_block.lower()

    def test_mcp_tool_description_includes_staging_lock_note(self):
        """mcp_tools_available description for set_agent_status mentions the lock."""
        from pathlib import Path

        # BE-6042d: the set_agent_status @mcp.tool wrapper moved into the
        # mcp_tools subpackage (_job_tools.py).
        src = Path("api/endpoints/mcp_tools/_job_tools.py").read_text(encoding="utf-8")
        # Isolate set_agent_status's @mcp.tool(...) decorator: the nearest
        # @mcp.tool( immediately preceding `async def set_agent_status`. Slicing
        # (rather than a spanning regex) is robust to decorator-kwarg ordering
        # (BE-9251 added title= before and annotations= after description=).
        def_idx = src.index("async def set_agent_status")
        block_start = src.rindex("@mcp.tool(", 0, def_idx)
        description = src[block_start:def_idx]
        assert "async def" not in description, "set_agent_status @mcp.tool block spanned another function"
        assert "STAGING_LOCK" in description
        assert "staging" in description.lower()
        assert "report_progress" in description
