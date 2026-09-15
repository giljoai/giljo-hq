# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.progress_service import ProgressService


pytestmark = pytest.mark.asyncio


def _seeded_service(cls, db_session, tenant_key):
    return cls(db_manager=MagicMock(), tenant_manager=MagicMock(), test_session=db_session)


async def _seed_job_with_execution_status(db_session, tenant_key: str, execution_status: str) -> str:
    job = AgentJob(
        tenant_key=tenant_key,
        project_id=None,
        mission="tsk9003 regression",
        job_type="implementer",
        status="active",
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status=execution_status,
    )
    db_session.add(execution)
    await db_session.flush()
    return job.job_id


def _tenant_key() -> str:
    return f"tk_tsk9003_{random.randint(1, 10_000_000)}"




async def test_complete_job_unknown_job_id_names_itself_distinctly(db_session):
    tenant_key = _tenant_key()
    service = _seeded_service(JobCompletionService, db_session, tenant_key)
    ghost_job_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await service.complete_job(ghost_job_id, {"summary": "test"}, tenant_key)

    err = exc_info.value
    assert "No job found with ID" in str(err)
    assert err.context["reason"] == "unknown_job_id"
    assert err.context["next_action"]["tool"] == "diagnose_project_state"


async def test_complete_job_wrong_state_names_actual_status(db_session):
    tenant_key = _tenant_key()
    service = _seeded_service(JobCompletionService, db_session, tenant_key)
    job_id = await _seed_job_with_execution_status(db_session, tenant_key, "complete")

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await service.complete_job(job_id, {"summary": "test"}, tenant_key)

    err = exc_info.value
    assert "'complete' status, not 'active'" in str(err)
    assert err.context["reason"] == "wrong_state"
    assert err.context["actual_status"] == "complete"
    assert err.context["expected_status"] == "active"
    assert err.context["next_action"]["tool"] == "diagnose_project_state"




async def test_get_agent_mission_unknown_job_id_names_itself_distinctly(db_session):
    tenant_key = _tenant_key()
    service = _seeded_service(MissionService, db_session, tenant_key)
    ghost_job_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await service.get_agent_mission(ghost_job_id, tenant_key)

    err = exc_info.value
    assert "not found" in str(err)
    assert "not 'active'" not in str(err)


async def test_get_agent_mission_wrong_state_names_actual_status(db_session):
    tenant_key = _tenant_key()
    service = _seeded_service(MissionService, db_session, tenant_key)
    job_id = await _seed_job_with_execution_status(db_session, tenant_key, "complete")

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await service.get_agent_mission(job_id, tenant_key)

    err = exc_info.value
    assert "'complete' status, not 'active'" in str(err)
    assert err.context["reason"] == "wrong_state"
    assert err.context["actual_status"] == "complete"




async def test_report_progress_unknown_job_id_names_itself_distinctly(db_session):
    tenant_key = _tenant_key()
    service = _seeded_service(ProgressService, db_session, tenant_key)
    ghost_job_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await service.report_progress(ghost_job_id, progress={"percent": 50}, tenant_key=tenant_key)

    err = exc_info.value
    assert "No job found with ID" in str(err)
    assert err.context["reason"] == "unknown_job_id"
    assert err.context["next_action"]["tool"] == "diagnose_project_state"
