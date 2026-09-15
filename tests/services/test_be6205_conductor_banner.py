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


_CONDUCTOR_AUTONOMY = "you spawn each sub-orchestrator YOURSELF"
_CONDUCTOR_RUN_CMD = "RUNNING the fresh-terminal launch command"

_STOCK_USER_TERMINALS = "The USER opens each agent's new session"
_STOCK_NOT_EXECUTE = "you do NOT execute"




def test_renderer_conductor_variant_has_autonomy_wording() -> None:
    out = _generate_orchestrator_protocol(
        "job-1",
        "tenant-1",
        "exec-1",
        execution_mode="multi_terminal",
        tool="multi_terminal",
        is_chain_conductor=True,
    )
    assert _CONDUCTOR_AUTONOMY in out
    assert _CONDUCTOR_RUN_CMD in out
    assert "Bash" in out and "PowerShell" in out
    assert _STOCK_USER_TERMINALS not in out
    assert _STOCK_NOT_EXECUTE not in out
    assert "Task(" in out
    assert "SUB-ORCH SPAWN: FRESH TERMINAL" in out
    assert "EXECUTION_MODE: multi_terminal" not in out


def test_renderer_non_conductor_multi_terminal_keeps_stock_banner() -> None:
    out = _generate_orchestrator_protocol(
        "job-1",
        "tenant-1",
        "exec-1",
        execution_mode="multi_terminal",
        tool="multi_terminal",
    )
    assert _STOCK_USER_TERMINALS in out
    assert _CONDUCTOR_AUTONOMY not in out
    assert _CONDUCTOR_RUN_CMD not in out




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


class _FakeProject:
    def __init__(self, execution_mode):
        self.execution_mode = execution_mode
        self.auto_checkin_interval = 10
        self.implementation_launched_at = None


def _assemble(svc, *, job, execution, chain_mode, project):
    return svc._assemble_mission_context(
        job=job,
        execution=execution,
        project=project,
        agent_identity=None,
        all_project_executions=[execution],
        mission_lookup={job.job_id: ""},
        current_team_state=None,
        tenant_key="tk_x",
        integrations={},
        chain_execution_mode=chain_mode,
    )


@pytest.mark.asyncio
async def test_projectless_conductor_gets_autonomy_banner(db_manager) -> None:
    p1 = str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager, project_ids=[p1], conductor_agent_id="cond-1", execution_mode="claude_code_cli"
    )
    svc = _svc(db_manager)
    job = _FakeJob(project_id=None, job_id="job-cond")
    execution = _FakeExec("cond-1")

    async with svc._get_session(tenant_key) as session:
        chain_mode = await svc._resolve_chain_execution_mode(session, job, execution, tenant_key)

    resp = _assemble(svc, job=job, execution=execution, chain_mode=chain_mode, project=None)

    assert _CONDUCTOR_AUTONOMY in resp.full_protocol
    assert _CONDUCTOR_RUN_CMD in resp.full_protocol
    assert _STOCK_USER_TERMINALS not in resp.full_protocol
    assert _STOCK_NOT_EXECUTE not in resp.full_protocol
    assert "Task(" in resp.full_protocol


@pytest.mark.asyncio
async def test_project_bound_suborch_keeps_stock_banner(db_manager) -> None:
    p1 = str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager, project_ids=[p1], conductor_agent_id="cond-1", execution_mode="multi_terminal"
    )
    svc = _svc(db_manager)
    job = _FakeJob(project_id=p1, job_id="job-sub")
    execution = _FakeExec("sub-1")

    async with svc._get_session(tenant_key) as session:
        chain_mode = await svc._resolve_chain_execution_mode(session, job, execution, tenant_key)
    assert chain_mode == "multi_terminal"

    resp = _assemble(svc, job=job, execution=execution, chain_mode=chain_mode, project=_FakeProject("multi_terminal"))

    assert _STOCK_USER_TERMINALS in resp.full_protocol
    assert _CONDUCTOR_AUTONOMY not in resp.full_protocol
    assert _CONDUCTOR_RUN_CMD not in resp.full_protocol
