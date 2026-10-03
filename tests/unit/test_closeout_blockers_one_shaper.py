# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.services.project_closeout_readiness import shape_readiness_blockers
from giljo_mcp.services.project_closeout_service import (
    AgentReadinessFinding,
    CloseoutReadinessReport,
    ProjectCloseoutService,
)
from giljo_mcp.tools.write_memory_entry import _check_closeout_readiness, _derive_verified


def _awaiting_user_report() -> CloseoutReadinessReport:
    finding = AgentReadinessFinding(
        job_id="job-1",
        agent_id="agent-1",
        agent_name="impl-1",
        status="awaiting_user",
        messages_waiting=0,
        incomplete_todos=[],
        incomplete_pending=0,
        incomplete_in_progress=0,
        awaiting_user=True,
        approval_id="approval-1",
    )
    return CloseoutReadinessReport(
        findings=[finding],
        agents_checked=1,
        status_counts={"total": 1, "completed": 0, "blocked": 0, "silent": 0, "active": 1},
        orchestrator_incomplete=[],
        orchestrator_pending=0,
        orchestrator_in_progress=0,
    )


@pytest.mark.asyncio
async def test_memory_gate_reports_an_awaiting_approval_like_the_closeout_gate():
    report = _awaiting_user_report()

    with patch.object(ProjectCloseoutService, "evaluate_closeout_readiness", new=AsyncMock(return_value=report)):
        is_ready, result = await _check_closeout_readiness(Mock(), "proj-1", "tenant-1")

    closeout_gate_blocker = shape_readiness_blockers(report)[0]
    assert is_ready is False
    assert result["blockers"] == [closeout_gate_blocker]
    assert result["blockers"][0]["issue_type"] == "awaiting_user_approval"
    assert result["blockers"][0]["approval_id"] == "approval-1"
    assert _derive_verified(result)["all_complete"] is False
