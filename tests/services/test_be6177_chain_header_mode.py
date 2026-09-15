# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest

from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.protocol_sections.agent_lifecycle import (
    _generate_orchestrator_protocol,
)
from giljo_mcp.tenant import TenantManager


_HEADER_MULTI = "EXECUTION_MODE: multi_terminal"
_HEADER_USER_TERMINALS = "The USER opens each agent's new session"




def test_renderer_multi_terminal_renders_terminal_header():
    out = _generate_orchestrator_protocol(
        "job-1", "tenant-1", "exec-1", execution_mode="multi_terminal", tool="multi_terminal"
    )
    assert _HEADER_MULTI in out
    assert _HEADER_USER_TERMINALS in out


def test_renderer_claude_code_cli_omits_terminal_header():
    out = _generate_orchestrator_protocol(
        "job-1", "tenant-1", "exec-1", execution_mode="claude-code", tool="claude-code"
    )
    assert _HEADER_MULTI not in out
    assert "FORBIDDEN in this mode" not in out




def _svc(db_manager) -> MissionService:
    return MissionService(db_manager=db_manager, tenant_manager=TenantManager())


async def _seed_run(db_manager, *, project_ids, conductor_agent_id, execution_mode):
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        session.add(
            SequenceRun(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                project_ids=project_ids,
                resolved_order=project_ids,
                current_index=0,
                execution_mode=execution_mode,
                status="running",
                locked=True,
                conductor_agent_id=conductor_agent_id,
                project_statuses=dict.fromkeys(project_ids, "pending"),
            )
        )
        await session.commit()
    return tenant_key


class _FakeJob:
    def __init__(self, *, project_id, job_type="orchestrator", job_id="job-x"):
        self.project_id = project_id
        self.job_type = job_type
        self.job_id = job_id
        self.mission = ""
        self.created_at = None


class _FakeExec:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.agent_display_name = "orchestrator"
        self.agent_name = "orchestrator"
        self.spawned_by = None
        self.status = "working"
        self.started_at = None
        self.project_phase = None


@pytest.mark.asyncio
async def test_projectless_conductor_header_pinned_to_multi_terminal(db_manager):
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager, project_ids=[p1, p2], conductor_agent_id="cond-1", execution_mode="claude_code_cli"
    )
    svc = _svc(db_manager)
    async with svc._get_session(tenant_key) as session:
        mode = await svc._resolve_chain_execution_mode(
            session,
            _FakeJob(project_id=None),
            _FakeExec("cond-1"),
            tenant_key,
        )
    assert mode == "multi_terminal"


@pytest.mark.asyncio
async def test_sub_orchestrator_resolves_run_mode(db_manager):
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager, project_ids=[p1, p2], conductor_agent_id="cond-1", execution_mode="claude_code_cli"
    )
    svc = _svc(db_manager)
    async with svc._get_session(tenant_key) as session:
        mode = await svc._resolve_chain_execution_mode(
            session,
            _FakeJob(project_id=p2),
            _FakeExec("sub-1"),
            tenant_key,
        )
    assert mode == "claude_code_cli"


@pytest.mark.asyncio
async def test_solo_orchestrator_resolves_none(db_manager):
    svc = _svc(db_manager)
    tenant_key = TenantManager.generate_tenant_key()
    async with svc._get_session(tenant_key) as session:
        mode = await svc._resolve_chain_execution_mode(
            session,
            _FakeJob(project_id=str(uuid.uuid4())),
            _FakeExec("solo-1"),
            tenant_key,
        )
    assert mode is None


@pytest.mark.asyncio
async def test_conductor_header_is_terminal_based_agreeing_with_ch_capability(db_manager):
    p1 = str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager, project_ids=[p1], conductor_agent_id="cond-1", execution_mode="claude_code_cli"
    )
    svc = _svc(db_manager)

    job = _FakeJob(project_id=None, job_type="orchestrator", job_id="job-cond")
    execution = _FakeExec("cond-1")
    execution.agent_display_name = "orchestrator"
    execution.agent_name = "orchestrator"

    async with svc._get_session(tenant_key) as session:
        chain_mode = await svc._resolve_chain_execution_mode(session, job, execution, tenant_key)

    resp = svc._assemble_mission_context(
        job=job,
        execution=execution,
        project=None,
        agent_identity=None,
        all_project_executions=[execution],
        mission_lookup={job.job_id: ""},
        current_team_state=None,
        tenant_key=tenant_key,
        integrations={},
        chain_execution_mode=chain_mode,
    )

    assert _HEADER_MULTI not in resp.full_protocol
    assert "SUB-ORCH SPAWN: FRESH TERMINAL" in resp.full_protocol
    assert "you spawn each sub-orchestrator YOURSELF" in resp.full_protocol
    assert _HEADER_USER_TERMINALS not in resp.full_protocol


@pytest.mark.asyncio
async def test_multi_terminal_chain_still_renders_terminal_header(db_manager):
    p1 = str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager, project_ids=[p1], conductor_agent_id="cond-1", execution_mode="multi_terminal"
    )
    svc = _svc(db_manager)

    job = _FakeJob(project_id=None, job_type="orchestrator", job_id="job-cond")
    execution = _FakeExec("cond-1")
    execution.agent_display_name = "orchestrator"
    execution.agent_name = "orchestrator"

    async with svc._get_session(tenant_key) as session:
        chain_mode = await svc._resolve_chain_execution_mode(session, job, execution, tenant_key)

    resp = svc._assemble_mission_context(
        job=job,
        execution=execution,
        project=None,
        agent_identity=None,
        all_project_executions=[execution],
        mission_lookup={job.job_id: ""},
        current_team_state=None,
        tenant_key=tenant_key,
        integrations={},
        chain_execution_mode=chain_mode,
    )

    assert _HEADER_MULTI not in resp.full_protocol
    assert "SUB-ORCH SPAWN: FRESH TERMINAL" in resp.full_protocol
