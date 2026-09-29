# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
import logging
import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.services.mission_assembly import assemble_mission_context, compute_protocol_etag
from giljo_mcp.services.mission_service import MissionService


@pytest.fixture(autouse=True)
def _solo_chain_lookup():
    with patch(
        "giljo_mcp.services.sequence_run_service.SequenceRunService.find_active_run_for_project",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield


_LOGGER = logging.getLogger("be9079-test")
_TENANT = "tenant-test"

_WRAPPER_PAYLOAD_KEYS = {"job_id", "protocol_etag", "preset_name", "detected_harness"}


def _make_orchestrator_fixtures() -> tuple[AgentJob, AgentExecution, Project]:
    job_id = str(uuid4())
    project_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=_TENANT,
        project_id=project_id,
        mission="Coordinate implementation",
        job_type="orchestrator",
        status="active",
        created_at=datetime.now(UTC),
    )
    execution = AgentExecution(
        job_id=job_id,
        agent_id=str(uuid4()),
        tenant_key=_TENANT,
        agent_display_name="orchestrator",
        agent_name="orchestrator-1",
        status="waiting",
    )
    project = Project(
        id=project_id,
        tenant_key=_TENANT,
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
    return job, execution, project


def _render_full_protocol(fixtures: tuple[AgentJob, AgentExecution, Project], detected_harness: str | None) -> str:
    job, execution, project = fixtures
    response = assemble_mission_context(
        _LOGGER,
        job=job,
        execution=execution,
        project=project,
        agent_identity="ORCHESTRATOR IDENTITY",
        all_project_executions=[execution],
        mission_lookup={job.job_id: job.mission},
        current_team_state=None,
        tenant_key=_TENANT,
        integrations={},
        chain_execution_mode=None,
        preset=None,
        comm_thread_id=None,
        detected_harness=detected_harness,
    )
    return response.full_protocol




def test_detected_claude_code_renders_native_tool():
    protocol = _render_full_protocol(_make_orchestrator_fixtures(), "claude-code")
    assert "YOUR TOOL: Claude Code" in protocol
    assert "YOUR TOOL: Multi-Terminal (generic)" not in protocol
    assert "That menu is irrelevant in this mode" in protocol


def test_detected_codex_renders_native_tool():
    protocol = _render_full_protocol(_make_orchestrator_fixtures(), "codex")
    assert "YOUR TOOL: Codex" in protocol
    assert "YOUR TOOL: Multi-Terminal (generic)" not in protocol


def test_detection_changes_the_render():
    fx = _make_orchestrator_fixtures()
    assert _render_full_protocol(fx, "claude-code") != _render_full_protocol(fx, None)
    assert _render_full_protocol(fx, "codex") != _render_full_protocol(fx, "claude-code")




def test_no_detection_is_generic_and_byte_identical():
    fx = _make_orchestrator_fixtures()
    none_render = _render_full_protocol(fx, None)
    generic_render = _render_full_protocol(fx, "generic")
    assert none_render == generic_render, "None and 'generic' must render identically"
    assert "YOUR TOOL: Multi-Terminal (generic)" in none_render
    assert _render_full_protocol(fx, "totally-made-up-harness") == none_render




def test_protocol_etag_covers_effective_harness():
    fx = _make_orchestrator_fixtures()
    identity = "ORCHESTRATOR IDENTITY"
    etag_claude = compute_protocol_etag(identity, _render_full_protocol(fx, "claude-code"))
    etag_codex = compute_protocol_etag(identity, _render_full_protocol(fx, "codex"))
    etag_none = compute_protocol_etag(identity, _render_full_protocol(fx, None))
    assert etag_claude != etag_none, "detected claude-code must not share the generic etag"
    assert etag_codex != etag_none
    assert etag_claude != etag_codex
    assert etag_none == compute_protocol_etag(identity, _render_full_protocol(fx, "generic"))




def test_get_agent_mission_signature_accepts_wrapper_payload():
    params = set(inspect.signature(MissionService.get_agent_mission).parameters)
    missing = _WRAPPER_PAYLOAD_KEYS - params
    assert not missing, f"get_agent_mission is missing wrapper payload params: {missing}"


@pytest.fixture
def mock_db_session():
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


@pytest.mark.asyncio
async def test_get_agent_mission_through_dispatch_does_not_raise_and_renders_native(mock_db_session):
    db_manager, session = mock_db_session
    job, execution, project = _make_orchestrator_fixtures()

    def _scalar(value):
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=value)
        return r

    all_exec = MagicMock()
    all_exec.all = MagicMock(return_value=[(execution, job)])

    session.execute = AsyncMock(
        side_effect=[
            _scalar(job),
            _scalar(execution),
            _scalar(project),
            RuntimeError("TSK-9459: no Hub thread in this mocked session"),
            all_exec,
            _scalar(project),
            _scalar(None),
        ]
    )

    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant = MagicMock(return_value=_TENANT)
    svc = MissionService(db_manager=db_manager, tenant_manager=tenant_manager)

    payload = {"job_id": job.job_id, "protocol_etag": None, "preset_name": None, "detected_harness": "claude-code"}
    response = await svc.get_agent_mission(tenant_key=_TENANT, **payload)

    assert response.full_protocol is not None
    assert "YOUR TOOL: Claude Code" in response.full_protocol
