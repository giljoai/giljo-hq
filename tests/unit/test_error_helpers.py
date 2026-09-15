# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.services import _error_helpers


@pytest.fixture
def repo_mock(monkeypatch):
    instance = MagicMock()
    instance.get_latest_execution_for_job = AsyncMock(return_value=None)
    instance.get_agent_job_by_job_id = AsyncMock(return_value=None)
    monkeypatch.setattr(_error_helpers, "AgentJobRepository", MagicMock(return_value=instance))
    return instance


@pytest.mark.asyncio
async def test_unknown_job_id_names_the_unknown_case(repo_mock):
    err = await _error_helpers.not_found_or_wrong_state_error(
        session=MagicMock(),
        tenant_key="tk_test",
        job_id="job-does-not-exist",
        expected_status="working",
        method="unit_test",
        db_manager=MagicMock(),
    )

    assert isinstance(err, ResourceNotFoundError)
    assert err.context["reason"] == "unknown_job_id"
    assert "No job found with ID job-does-not-exist" in err.message
    assert err.context["next_action"]["tool"] == "diagnose_project_state"


@pytest.mark.asyncio
async def test_wrong_state_names_both_statuses(repo_mock):
    repo_mock.get_latest_execution_for_job.return_value = SimpleNamespace(status="blocked")
    repo_mock.get_agent_job_by_job_id.return_value = SimpleNamespace(project_id="proj-1")

    err = await _error_helpers.not_found_or_wrong_state_error(
        session=MagicMock(),
        tenant_key="tk_test",
        job_id="job-1",
        expected_status="working",
        method="unit_test",
        db_manager=MagicMock(),
    )

    assert isinstance(err, ResourceNotFoundError)
    assert err.context["reason"] == "wrong_state"
    assert err.context["actual_status"] == "blocked"
    assert err.context["expected_status"] == "working"
    assert "'blocked'" in err.message and "'working'" in err.message
    assert err.context["next_action"]["args_hint"] == {"project_id": "proj-1"}
