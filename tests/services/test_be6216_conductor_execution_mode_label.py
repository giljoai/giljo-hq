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
from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_capability
from giljo_mcp.tenant import TenantManager


_NEW_HEADER = "SUB-ORCH SPAWN: FRESH TERMINAL"
_OLD_COLLIDING = "EXECUTION_MODE: multi_terminal"




def test_conductor_banner_drops_colliding_execution_mode_token() -> None:
    out = _generate_orchestrator_protocol(
        "job-1",
        "tenant-1",
        "exec-1",
        execution_mode="multi_terminal",
        tool="multi_terminal",
        is_chain_conductor=True,
    )
    assert _NEW_HEADER in out
    assert "ROLE: CHAIN CONDUCTOR" in out
    assert _OLD_COLLIDING not in out
    assert "This header is NOT an execution_mode" in out
    assert "WORKERS" in out
    assert "Task(" in out
    assert "you spawn each sub-orchestrator YOURSELF" in out


def test_non_conductor_multi_terminal_banner_keeps_execution_mode_header() -> None:
    out = _generate_orchestrator_protocol(
        "job-1",
        "tenant-1",
        "exec-1",
        execution_mode="multi_terminal",
        tool="multi_terminal",
    )
    assert _OLD_COLLIDING in out
    assert _NEW_HEADER not in out




def test_banner_and_ch_capability_yield_single_execution_mode_value() -> None:
    banner = _generate_orchestrator_protocol(
        "job-1",
        "tenant-1",
        "exec-1",
        execution_mode="multi_terminal",
        tool="multi_terminal",
        is_chain_conductor=True,
    )
    ch_cap = _build_ch_capability(execution_mode="claude_code_cli")

    assert _OLD_COLLIDING not in banner
    assert "EXECUTION_MODE" not in banner
    assert "EXECUTION MODE = claude_code_cli" in ch_cap
    assert "EXECUTION MODE = multi_terminal" not in ch_cap




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
        self.agent_name = "Chain Conductor"
        self.spawned_by = None
        self.status = "working"
        self.started_at = None
        self.project_phase = None


@pytest.mark.asyncio
async def test_subagent_conductor_assembled_banner_drops_colliding_token(db_manager) -> None:
    p1 = str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager, project_ids=[p1], conductor_agent_id="cond-1", execution_mode="claude_code_cli"
    )
    svc = _svc(db_manager)
    job = _FakeJob(project_id=None, job_id="job-cond")
    execution = _FakeExec("cond-1")

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

    protocol = resp.full_protocol
    assert _OLD_COLLIDING not in protocol
    assert _NEW_HEADER in protocol
