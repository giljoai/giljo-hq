# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.schemas.service_responses import MissionResponse
from giljo_mcp.services.orchestration_service import OrchestrationService


@pytest.fixture(autouse=True)
def _mock_comm_thread_resolution():
    with patch(
        "giljo_mcp.services.comm_thread_service.CommThreadService.resolve_or_create_bound_thread",
        new_callable=AsyncMock,
        return_value={"thread_id": "CHT-test-thread"},
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
    session.info = {}
    db_manager.get_session_async = MagicMock(return_value=session)
    return db_manager, session


@pytest.fixture
def mock_tenant_manager():
    return MagicMock()


@pytest.fixture
def orchestration_service(mock_db_manager, mock_tenant_manager):
    db_manager, _ = mock_db_manager
    return OrchestrationService(db_manager=db_manager, tenant_manager=mock_tenant_manager)


@pytest.fixture
def mock_agent_job():
    job_id = str(uuid4())

    job = AgentJob(
        job_id=job_id,
        tenant_key="tenant-test",
        project_id=str(uuid4()),
        mission="Test mission for implementation",
        job_type="agent",
        status="active",
    )

    execution = AgentExecution(
        job_id=job_id,
        tenant_key="tenant-test",
        agent_display_name="implementer",
        agent_name="implementer-1",
        status="waiting",
        mission_acknowledged_at=None,
        started_at=None,
    )

    return job, execution


def setup_get_agent_mission_mocks(session, job, execution):
    from datetime import datetime
    from types import SimpleNamespace

    job_result = MagicMock()
    job_result.scalar_one_or_none = MagicMock(return_value=job)

    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=execution)

    mock_project = SimpleNamespace(
        id=job.project_id,
        tenant_key=job.tenant_key,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
    )
    project_result = MagicMock()
    project_result.scalar_one_or_none = MagicMock(return_value=mock_project)

    all_exec_result = MagicMock()
    all_exec_result.all = MagicMock(return_value=[(execution, job)])

    session.execute = AsyncMock(side_effect=[job_result, exec_result, project_result, all_exec_result])


def setup_get_agent_mission_mocks_with_project(session, job, execution, project_attrs):
    from datetime import datetime
    from types import SimpleNamespace

    job_result = MagicMock()
    job_result.scalar_one_or_none = MagicMock(return_value=job)

    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=execution)

    base_attrs = {
        "id": job.project_id,
        "tenant_key": job.tenant_key,
        "implementation_launched_at": datetime.now(UTC),
    }
    base_attrs.update(project_attrs)
    mock_project = SimpleNamespace(**base_attrs)
    project_result = MagicMock()
    project_result.scalar_one_or_none = MagicMock(return_value=mock_project)

    all_exec_result = MagicMock()
    all_exec_result.all = MagicMock(return_value=[(execution, job)])

    ordered = [job_result, exec_result, project_result, all_exec_result]
    call_index = {"n": 0}

    def _next_result(*_args, **_kwargs):
        i = call_index["n"]
        call_index["n"] += 1
        if i < len(ordered):
            return ordered[i]
        empty = MagicMock()
        empty.scalar_one_or_none = MagicMock(return_value=None)
        empty.all = MagicMock(return_value=[])
        empty.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return empty

    session.execute = AsyncMock(side_effect=_next_result)


CH6_MARKER = "CH6: CHECK-IN"


class TestGetAgentMissionCh6Injection:

    def _orchestrator_job_execution(self):
        job_id = str(uuid4())
        job = AgentJob(
            job_id=job_id,
            tenant_key="tenant-test",
            project_id=str(uuid4()),
            mission="Coordinate the swarm",
            job_type="orchestrator",
            status="active",
        )
        execution = AgentExecution(
            job_id=job_id,
            tenant_key="tenant-test",
            agent_display_name="orchestrator",
            agent_name="orchestrator-1",
            status="working",
            mission_acknowledged_at=None,
            started_at=None,
        )
        return job, execution

    @pytest.mark.asyncio
    @pytest.mark.parametrize("enabled", [True, False])
    async def test_ch6_present_for_multi_terminal_orchestrator_regardless_of_enabled(
        self, orchestration_service, mock_db_manager, enabled
    ):
        _db_manager, session = mock_db_manager
        job, execution = self._orchestrator_job_execution()
        setup_get_agent_mission_mocks_with_project(
            session,
            job,
            execution,
            {
                "execution_mode": "multi_terminal",
                "auto_checkin_enabled": enabled,
                "auto_checkin_interval": 15,
            },
        )

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        assert CH6_MARKER in (response.full_protocol or ""), (
            f"CH6 scaffold must be present for a multi-terminal orchestrator even when "
            f"auto_checkin_enabled={enabled} (on/off now lives inside the protocol)"
        )

    @pytest.mark.asyncio
    async def test_ch6_absent_for_non_multi_terminal_mode(self, orchestration_service, mock_db_manager):
        _db_manager, session = mock_db_manager
        job, execution = self._orchestrator_job_execution()
        setup_get_agent_mission_mocks_with_project(
            session,
            job,
            execution,
            {
                "execution_mode": "claude_code_cli",
                "auto_checkin_enabled": True,
                "auto_checkin_interval": 15,
            },
        )

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        assert CH6_MARKER not in (response.full_protocol or ""), (
            "CH6 scaffold must NOT be injected for CLI/Codex/Gemini execution modes"
        )

    @pytest.mark.asyncio
    async def test_ch6_absent_for_non_orchestrator_agent(self, orchestration_service, mock_db_manager):
        _db_manager, session = mock_db_manager
        job_id = str(uuid4())
        job = AgentJob(
            job_id=job_id,
            tenant_key="tenant-test",
            project_id=str(uuid4()),
            mission="Implement the thing",
            job_type="agent",
            status="active",
        )
        execution = AgentExecution(
            job_id=job_id,
            tenant_key="tenant-test",
            agent_display_name="implementer",
            agent_name="implementer-1",
            status="working",
            mission_acknowledged_at=None,
            started_at=None,
        )
        setup_get_agent_mission_mocks_with_project(
            session,
            job,
            execution,
            {
                "execution_mode": "multi_terminal",
                "auto_checkin_enabled": True,
                "auto_checkin_interval": 15,
            },
        )

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        assert CH6_MARKER not in (response.full_protocol or ""), (
            "CH6 scaffold must NOT be injected for non-orchestrator agents"
        )


class TestGetAgentMissionFullProtocol:

    @pytest.mark.asyncio
    async def test_get_agent_mission_returns_full_protocol_by_default(
        self, orchestration_service, mock_db_manager, mock_agent_job
    ):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        assert isinstance(response, MissionResponse)
        assert response.full_protocol is not None, "Response must include full_protocol field"
        assert isinstance(response.full_protocol, str)
        assert len(response.full_protocol) > 0

    @pytest.mark.asyncio
    async def test_full_protocol_contains_five_phases(self, orchestration_service, mock_db_manager, mock_agent_job):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        protocol = response.full_protocol

        assert "Phase 1" in protocol or "STARTUP" in protocol.upper(), "Protocol must include Phase 1 (Startup)"
        assert "Phase 2" in protocol or "EXECUTION" in protocol.upper(), "Protocol must include Phase 2 (Execution)"
        assert "Phase 3" in protocol or "PROGRESS" in protocol.upper(), "Protocol must include Phase 3 (Progress)"
        assert "Phase 4" in protocol or "COMPLETION" in protocol.upper(), "Protocol must include Phase 4 (Completion)"
        assert "Phase 5" in protocol or "ERROR" in protocol.upper(), "Protocol must include Phase 5 (Error Handling)"

    @pytest.mark.asyncio
    async def test_full_protocol_references_mcp_tools(self, orchestration_service, mock_db_manager, mock_agent_job):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        protocol = response.full_protocol

        assert "report_progress" in protocol.lower(), "Protocol must reference report_progress tool"
        assert "complete_job" in protocol.lower(), "Protocol must reference complete_job tool"

    @pytest.mark.asyncio
    async def test_full_protocol_includes_job_context(self, orchestration_service, mock_db_manager, mock_agent_job):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job
        job.job_id = "unique-job-id-12345"

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        protocol = response.full_protocol

        assert job.job_id in protocol, "Protocol must include job_id for MCP tool calls"

    @pytest.mark.asyncio
    async def test_response_backward_compatible_with_existing_fields(
        self, orchestration_service, mock_db_manager, mock_agent_job
    ):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        assert isinstance(response, MissionResponse)
        assert response.job_id is not None
        assert response.agent_name is not None
        assert response.agent_display_name is not None
        assert response.mission is not None
        assert response.project_id is not None
        assert response.thin_client is True
        assert response.status is not None
        assert response.full_protocol is not None
        assert "agent_identity" in MissionResponse.model_fields

    @pytest.mark.asyncio
    async def test_protocol_includes_message_handling_instructions(
        self, orchestration_service, mock_db_manager, mock_agent_job
    ):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        assert isinstance(response, MissionResponse)
        protocol = response.full_protocol or ""

        assert "MESSAGE HANDLING" in protocol
        assert "get_thread_history(..., mark_read=true)" in protocol
        assert "read-only inspection" in protocol


class TestBe6211cProtocolEtagAlwaysEmitted:

    @pytest.mark.asyncio
    async def test_first_no_etag_call_returns_protocol_etag(
        self, orchestration_service, mock_db_manager, mock_agent_job
    ):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job
        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        assert response.protocol_etag is not None, "first no-etag call must still learn the etag (S-4a)"
        assert not response.protocol_unchanged, "no match -> static block is NOT omitted"
        assert response.full_protocol is not None, "full protocol must be present when not omitted"

    @pytest.mark.asyncio
    async def test_matching_etag_omits_static_block(self, orchestration_service, mock_db_manager, mock_agent_job):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)
        first = await orchestration_service._mission.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")
        etag = first.protocol_etag
        assert etag is not None

        setup_get_agent_mission_mocks(session, job, execution)
        second = await orchestration_service._mission.get_agent_mission(
            job_id=job.job_id, tenant_key="tenant-test", protocol_etag=etag
        )

        assert second.protocol_unchanged is True
        assert second.full_protocol is None
        assert second.agent_identity is None
        assert second.protocol_etag == etag


class TestAgentProtocolMessageHandlingEnhancements:

    @pytest.mark.asyncio
    async def test_agent_protocol_phase2_includes_message_check_after_tasks(
        self, orchestration_service, mock_db_manager, mock_agent_job
    ):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        protocol = response.full_protocol or ""

        phase2_start = protocol.find("### Phase 2")
        phase2_end = protocol.find("### Phase 3")
        phase2_section = protocol[phase2_start:phase2_end] if phase2_start != -1 and phase2_end != -1 else ""

        assert "get_thread_history()" in phase2_section, (
            "Phase 2 EXECUTION must instruct agents to check messages after each task"
        )

        assert "after" in phase2_section.lower() or "completing" in phase2_section.lower(), (
            "Phase 2 must specify WHEN to check messages (after each task)"
        )

    @pytest.mark.asyncio
    async def test_agent_protocol_phase3_checks_messages_before_reporting(
        self, orchestration_service, mock_db_manager, mock_agent_job
    ):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        protocol = response.full_protocol or ""

        phase3_start = protocol.find("### Phase 3")
        phase3_end = protocol.find("### Phase 4")
        phase3_section = protocol[phase3_start:phase3_end] if phase3_start != -1 and phase3_end != -1 else ""

        receive_pos = phase3_section.find("get_thread_history()")
        report_pos = phase3_section.find("report_progress(")

        assert receive_pos != -1, "Phase 3 must include get_thread_history() call"
        assert report_pos != -1, "Phase 3 must include report_progress() call"
        assert receive_pos < report_pos, (
            "Phase 3 must check messages BEFORE reporting progress (get_thread_history before report_progress)"
        )

        assert "before" in phase3_section.lower() or "mandatory" in phase3_section.lower(), (
            "Phase 3 must clearly state messages should be checked BEFORE reporting"
        )

    @pytest.mark.asyncio
    async def test_agent_protocol_phase4_requires_empty_queue_before_completion(
        self, orchestration_service, mock_db_manager, mock_agent_job
    ):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        protocol = response.full_protocol or ""

        phase4_start = protocol.find("### Phase 4")
        phase4_end = protocol.find("### Phase 5")
        phase4_section = protocol[phase4_start:phase4_end] if phase4_start != -1 and phase4_end != -1 else ""

        assert "get_thread_history()" in phase4_section, (
            "Phase 4 COMPLETION must instruct agents to check messages before completing"
        )

        queue_gate_indicators = ["queue", "empty", "no pending", "clear", "before completing"]
        has_gate_language = any(indicator in phase4_section.lower() for indicator in queue_gate_indicators)

        assert has_gate_language, "Phase 4 must include gate language requiring empty queue before completion"

    @pytest.mark.asyncio
    async def test_agent_protocol_includes_when_to_check_messages_guidance(
        self, orchestration_service, mock_db_manager, mock_agent_job
    ):
        _db_manager, session = mock_db_manager
        job, execution = mock_agent_job

        setup_get_agent_mission_mocks(session, job, execution)

        response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key="tenant-test")

        protocol = response.full_protocol or ""

        guidance_indicators = ["when to check", "message checking", "check messages in each phase", "across phases"]

        has_guidance = any(indicator in protocol.lower() for indicator in guidance_indicators)

        assert has_guidance, "Protocol must include clear guidance on WHEN to check messages across phases"

        phases_mentioned = sum(
            [
                "phase 1" in protocol.lower() and "message" in protocol.lower(),
                "phase 2" in protocol.lower() and "message" in protocol.lower(),
                "phase 3" in protocol.lower() and "message" in protocol.lower(),
                "phase 4" in protocol.lower() and "message" in protocol.lower(),
            ]
        )

        assert phases_mentioned >= 3, (
            "Message handling guidance should reference at least 3 phases (startup, execution, completion)"
        )
