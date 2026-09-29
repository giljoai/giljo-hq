# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.orchestrator_caller_guard import (
    ORCHESTRATOR_ONLY,
    require_project_orchestrator,
    warn_if_never_started,
)


def _repo(jobs: dict[str, SimpleNamespace]) -> MagicMock:
    repo = MagicMock()
    repo.get_agent_job_by_job_id = AsyncMock(side_effect=lambda _s, _t, job_id: jobs.get(job_id))
    return repo


TARGET = SimpleNamespace(job_type="implementer", project_id="p1")
JOBS = {
    "orch-p1": SimpleNamespace(job_type="orchestrator", project_id="p1"),
    "orch-p2": SimpleNamespace(job_type="orchestrator", project_id="p2"),
    "worker-p1": SimpleNamespace(job_type="implementer", project_id="p1"),
}


@pytest.mark.asyncio
async def test_project_orchestrator_is_accepted():
    await require_project_orchestrator(MagicMock(), _repo(JOBS), "tk", TARGET, "orch-p1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("caller_job_id", "role"),
    [
        (None, "unknown"),
        ("ghost", "unknown"),
        ("worker-p1", "implementer"),
        ("orch-p2", "orchestrator"),
    ],
)
async def test_everyone_else_is_refused(caller_job_id, role):
    with pytest.raises(ValidationError) as excinfo:
        await require_project_orchestrator(MagicMock(), _repo(JOBS), "tk", TARGET, caller_job_id)
    assert excinfo.value.error_code == ORCHESTRATOR_ONLY
    assert excinfo.value.context["caller_role"] == role
    assert "complete_job" in excinfo.value.message


@pytest.mark.parametrize(
    ("job_type", "status", "warns"),
    [
        ("implementer", "waiting", True),
        ("implementer", "staged", True),
        ("implementer", "working", False),
        ("implementer", "silent", False),
        ("orchestrator", "waiting", False),
    ],
)
def test_never_started_warning(job_type, status, warns):
    warnings: list[str] = []
    warn_if_never_started(SimpleNamespace(job_type=job_type), SimpleNamespace(status=status), warnings)
    assert bool(warnings) is warns
