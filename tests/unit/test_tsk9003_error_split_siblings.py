# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9003 — propagate the not-found/wrong-state error split to 3 sibling services.

BE-8003b split OrchestrationAgentStateService's ambiguous "not found or not in
status X" message into two distinct cases (unknown job_id vs exists-but-wrong-
state), but job_completion_service.py, mission_service.py, and
progress_service.py each kept their own copy of the old ambiguous "No active
execution found for job {id}" message. This exercises the SERVICE layer (the
layer that actually raises) for all three, proving each now uses the shared
``not_found_or_wrong_state_error`` builder: an unknown job_id names itself
distinctly from a job that exists but whose latest execution is in the wrong
status (which also now names the actual status + points at
diagnose_project_state, matching the disambiguation
test_be8003b_batch_validation_errors_mcp_boundary.py already proved for
finalize_job).

Parallel-safety: DB-touching; uses the db_session fixture (TransactionalTestContext,
rollback at teardown) via each service's test_session injection point, mirroring
test_job_completion_service.py's existing fixture pattern. No module-level
mutable state, no ordering dependency.
"""

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
    """Seed a job whose only execution is in ``execution_status`` -- the
    exists-but-wrong-state half of the disambiguation."""
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


# ---------------------------------------------------------------------------
# job_completion_service.complete_job -> _raise_for_missing_execution
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# mission_service.get_agent_mission -> _fetch_job_and_execution
# ---------------------------------------------------------------------------


async def test_get_agent_mission_unknown_job_id_names_itself_distinctly(db_session):
    """mission_service's ``_fetch_job_and_execution`` checks job-existence BEFORE
    the shared helper is ever reached (a pre-existing, separate "Agent job {id}
    not found" raise) -- so an unknown job_id here never even hits the shared
    ambiguous-message path the other two siblings share. Pin that it still
    names itself distinctly (not the wrong-state message)."""
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


# ---------------------------------------------------------------------------
# progress_service.report_progress -> _fetch_active_execution
# ---------------------------------------------------------------------------


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
