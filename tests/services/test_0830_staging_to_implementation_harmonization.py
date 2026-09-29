# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.schemas.service_responses import MissionResponse
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.protocol_builder import _generate_agent_protocol
from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator


@pytest.fixture(autouse=True)
def _solo_chain_lookup():
    with patch(
        "giljo_mcp.services.sequence_run_service.SequenceRunService.find_active_run_for_project",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield




@pytest.fixture
def mock_db_manager():
    db_manager = MagicMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock()
    session.info = {}
    db_manager.get_session_async = MagicMock(return_value=session)
    return db_manager, session


@pytest.fixture
def mock_tenant_manager():
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant = MagicMock(return_value="tenant-test")
    return tenant_manager


@pytest.fixture
def orchestration_service(mock_db_manager, mock_tenant_manager):
    db_manager, _ = mock_db_manager
    return OrchestrationService(db_manager=db_manager, tenant_manager=mock_tenant_manager)


@pytest.fixture
def sample_project():
    project = MagicMock()
    project.name = "Test Project"
    project.id = str(uuid4())
    return project




class TestThinPromptStrippedToFifteenLines:

    def _generate_prompt(self, project) -> str:
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




class TestOrchestratorIdentityPopulated:

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
        project_again_result = MagicMock()
        project_again_result.scalar_one_or_none = MagicMock(return_value=project)
        override_result = MagicMock()
        override_result.scalar_one_or_none = MagicMock(return_value=None)

        session.execute = AsyncMock(
            side_effect=[
                job_result,
                exec_result,
                project_result,
                RuntimeError("TSK-9459: no Hub thread in this mocked session"),
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

        project_again_result = MagicMock()
        project_again_result.scalar_one_or_none = MagicMock(return_value=project)
        override_result = MagicMock()
        override_result.scalar_one_or_none = MagicMock(return_value=None)

        session.execute = AsyncMock(
            side_effect=[
                job_result,
                exec_result,
                project_result,
                RuntimeError("TSK-9459: no Hub thread in this mocked session"),
                all_exec_result,
                project_again_result,
                override_result,
            ]
        )

        response = await orchestration_service.get_agent_mission(job_id=job_id, tenant_key="tenant-test")

        assert "ORCHESTRATOR" in response.agent_identity

    @pytest.mark.asyncio
    async def test_orchestrator_identity_contains_behavioral_phrases(self, orchestration_service, mock_db_manager):
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

        project_again_result = MagicMock()
        project_again_result.scalar_one_or_none = MagicMock(return_value=project)
        override_result = MagicMock()
        override_result.scalar_one_or_none = MagicMock(return_value=None)

        session.execute = AsyncMock(
            side_effect=[
                job_result,
                exec_result,
                project_result,
                RuntimeError("TSK-9459: no Hub thread in this mocked session"),
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




class TestOrchestratorProtocolFork:

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




class TestMissionResponseCurrentTeamState:

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




class TestOrchestratorPhaseGate:

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




class TestGetOrchestratorInstructionsRedirectBranches:

    def _make_fixtures(self, *, implementation_launched_at):
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
        exec_scalars = MagicMock()
        exec_scalars.first = MagicMock(return_value=execution)
        exec_result = MagicMock()
        exec_result.scalars = MagicMock(return_value=exec_scalars)

        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)

        session.execute = AsyncMock(side_effect=[exec_result, project_result])

    @pytest.mark.asyncio
    async def test_redirect_to_get_job_mission_when_launched(self, orchestration_service, mock_db_manager):
        _, session = mock_db_manager
        job_id, job, execution, project = self._make_fixtures(
            implementation_launched_at=datetime.now(UTC),
        )
        execution.job = job

        self._mock_session_for_get_staging_instructions(session, execution, project)

        result = await orchestration_service._mission.get_staging_instructions(job_id=job_id, tenant_key="tenant-test")

        assert result["staging_complete"] is True
        assert result["redirect"] == "get_job_mission"
        assert "already launched" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_no_redirect_when_not_launched(self, orchestration_service, mock_db_manager):
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




class TestImplementationPromptGateUsesProjectFlags:

    def _source(self) -> str:
        import inspect

        from giljo_mcp.services.project_staging_service import ProjectStagingService
        from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

        return inspect.getsource(ThinClientPromptGenerator.implement) + inspect.getsource(
            ProjectStagingService.check_implementation_allowed
        )

    def test_orchestrator_query_uses_terminal_status_exclusion_not_active_inclusion(self):
        from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES

        src = self._source()
        idx = src.find('agent_display_name == "orchestrator"')
        assert idx >= 0, "orchestrator query block missing"
        orchestrator_block = src[idx : idx + 400]
        assert 'status.in_(["waiting", "working"])' not in orchestrator_block
        assert "status.not_in" in orchestrator_block
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






class TestStagingLockProtocolRewrites:

    def test_orchestrator_template_unclear_reqs_uses_inline_ask(self):
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
        assert "get_thread_history" in section

    def test_ch4_error_handling_splits_staging_vs_implementation(self):
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch4_error_handling

        ch4 = _build_ch4_error_handling()

        assert "Staging phase" in ch4
        assert "Implementation phase" in ch4
        assert "STAGING_LOCK" in ch4

        staging_idx = ch4.find("Staging phase")
        implementation_idx = ch4.find("Implementation phase")
        assert staging_idx < implementation_idx, "staging phase should come first"
        staging_block = ch4[staging_idx:implementation_idx]
        assert 'set_agent_status("blocked")' not in staging_block
        assert 'set_agent_status("idle")' not in staging_block
        assert 'set_agent_status("sleeping")' not in staging_block

        implementation_block = ch4[implementation_idx:]
        assert 'set_agent_status("blocked")' in implementation_block
        assert 'set_agent_status("idle")' in implementation_block
        assert 'set_agent_status("sleeping")' in implementation_block

    def test_ch4_error_actions_no_longer_call_set_agent_status_during_staging(self):
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch4_error_handling

        ch4 = _build_ch4_error_handling()

        def _section(text: str, title: str) -> str:
            start = text.find(title)
            assert start >= 0, f"section {title!r} not found"
            end = text.find("\n── ", start + len(title))
            return text[start : end if end > 0 else len(text)]

        mcp_block = _section(ch4, "MCP Connection Lost")
        assert "Call set_agent_status(" not in mcp_block
        assert 'set_agent_status(job_id, status="blocked"' not in mcp_block
        assert "STAGING_LOCK" in mcp_block or "inline" in mcp_block.lower()

        spawn_block = _section(ch4, "Spawn Failure")
        assert 'set_agent_status(status="blocked")' not in spawn_block
        assert "Log via set_agent_status" not in spawn_block
        assert "inline" in spawn_block.lower() or "USER" in spawn_block

    def test_ch4_general_error_protocol_carves_out_staging(self):
        from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch4_error_handling

        ch4 = _build_ch4_error_handling()
        general_idx = ch4.find("GENERAL ERROR PROTOCOL")
        assert general_idx >= 0
        general_block = ch4[general_idx : general_idx + 800]
        assert "Staging phase" in general_block or "STAGING_LOCK" in general_block
        assert "Implementation phase" in general_block or "implementation" in general_block.lower()

    def test_mcp_tool_description_includes_staging_lock_note(self):
        from pathlib import Path

        src = Path("api/endpoints/mcp_tools/_job_tools.py").read_text(encoding="utf-8")
        def_idx = src.index("async def set_agent_status")
        block_start = src.rindex("@mcp.tool(", 0, def_idx)
        description = src[block_start:def_idx]
        assert "async def" not in description, "set_agent_status @mcp.tool block spanned another function"
        assert "STAGING_LOCK" in description
        assert "staging" in description.lower()
        assert "report_progress" in description
