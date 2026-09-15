# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
import types
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.sequence_runs import CHAIN_TERMINAL_PROJECT_STATUSES
from giljo_mcp.services.project_helpers import compute_completion_percent


if "api" not in sys.modules:
    _api_stub = types.ModuleType("api")
    _api_stub.__path__ = ["api"]
    _api_stub.__package__ = "api"
    sys.modules["api"] = _api_stub

from giljo_mcp.services.job_completion_service import JobCompletionService  # noqa: E402
from giljo_mcp.services.job_query_service import JobQueryService  # noqa: E402




class TestChainTerminalStatuses:
    def test_wide_set_includes_failed_and_cancelled(self):
        assert {"completed", "terminated", "cancelled", "failed"} == set(CHAIN_TERMINAL_PROJECT_STATUSES)

    def _make_service(self):
        return JobCompletionService(db_manager=Mock(), tenant_manager=Mock())

    @pytest.mark.asyncio
    async def test_conductor_can_complete_after_member_failed(self):
        service = self._make_service()
        job = Mock(job_type="orchestrator")
        execution = Mock(agent_id="conductor-agent")
        run = {
            "id": "run-1",
            "resolved_order": ["p1", "p2"],
            "project_statuses": {"p1": "completed", "p2": "failed"},
        }
        with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as mock_svc:
            mock_svc.return_value.find_active_run_for_conductor = AsyncMock(return_value=run)
            await service._guard_conductor_chain_incomplete(
                session=Mock(), job=job, execution=execution, tenant_key="tk", job_id="j1"
            )

    @pytest.mark.asyncio
    async def test_conductor_can_complete_after_member_cancelled(self):
        service = self._make_service()
        job = Mock(job_type="orchestrator")
        execution = Mock(agent_id="conductor-agent")
        run = {
            "id": "run-1",
            "resolved_order": ["p1", "p2"],
            "project_statuses": {"p1": "completed", "p2": "cancelled"},
        }
        with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as mock_svc:
            mock_svc.return_value.find_active_run_for_conductor = AsyncMock(return_value=run)
            await service._guard_conductor_chain_incomplete(
                session=Mock(), job=job, execution=execution, tenant_key="tk", job_id="j1"
            )

    @pytest.mark.asyncio
    async def test_conductor_blocked_when_member_still_in_flight(self):
        service = self._make_service()
        job = Mock(job_type="orchestrator")
        execution = Mock(agent_id="conductor-agent")
        run = {
            "id": "run-1",
            "resolved_order": ["p1", "p2"],
            "project_statuses": {"p1": "completed", "p2": "implementing"},
        }
        with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as mock_svc:
            mock_svc.return_value.find_active_run_for_conductor = AsyncMock(return_value=run)
            with patch(
                "giljo_mcp.services.job_completion_staging.heal_chain_member_statuses",
                AsyncMock(return_value=run["project_statuses"]),
            ):
                with pytest.raises(ValidationError):
                    await service._guard_conductor_chain_incomplete(
                        session=Mock(), job=job, execution=execution, tenant_key="tk", job_id="j1"
                    )




class TestCompletionPercent:
    def test_excludes_decommissioned_from_denominator(self):
        assert compute_completion_percent(completed=2, total=5, decommissioned=1) == 50.0

    def test_project_with_retired_agents_can_reach_100(self):
        assert compute_completion_percent(completed=2, total=3, decommissioned=1) == 100.0

    def test_zero_actionable_returns_zero(self):
        assert compute_completion_percent(completed=0, total=2, decommissioned=2) == 0.0
        assert compute_completion_percent(completed=0, total=0, decommissioned=0) == 0.0

    def test_default_decommissioned_zero(self):
        assert compute_completion_percent(completed=1, total=4) == 25.0




def _todo_item(status: str):
    item = MagicMock()
    item.status = status
    return item


class TestDeriveStepsSummaryDrift:
    def _service(self):
        return JobQueryService(MagicMock(), MagicMock())

    def test_live_rows_win_over_stale_cache(self):
        service = self._service()
        job = MagicMock()
        job.job_metadata = {"todo_steps": {"total_steps": 5, "completed_steps": 5, "skipped_steps": 0}}
        job.todo_items = [
            _todo_item("completed"),
            _todo_item("pending"),
            _todo_item("in_progress"),
            _todo_item("pending"),
        ]

        result = service._derive_steps_summary(job)

        assert result == {"total": 4, "completed": 1, "skipped": 0}

    def test_cache_used_only_when_no_live_rows(self):
        service = self._service()
        job = MagicMock()
        job.job_metadata = {"todo_steps": {"total_steps": 3, "completed_steps": 2, "skipped_steps": 1}}
        job.todo_items = []

        result = service._derive_steps_summary(job)

        assert result == {"total": 3, "completed": 2, "skipped": 1}
