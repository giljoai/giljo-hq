# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.job_completion_staging import guard_conductor_chain_incomplete


def _orchestrator_job() -> Mock:
    return Mock(job_type="orchestrator")


def _conductor_execution() -> Mock:
    return Mock(agent_id="conductor-agent")


async def _run_guard(run: dict) -> None:
    with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as mock_svc:
        mock_svc.return_value.find_active_run_for_conductor = AsyncMock(return_value=run)
        await guard_conductor_chain_incomplete(
            Mock(),
            _orchestrator_job(),
            _conductor_execution(),
            "tk",
            "j1",
            db_manager=Mock(),
            tenant_manager=Mock(),
        )


@pytest.mark.asyncio
async def test_guard_noop_for_non_orchestrator() -> None:
    await guard_conductor_chain_incomplete(
        Mock(),
        Mock(job_type="worker"),
        _conductor_execution(),
        "tk",
        "j1",
        db_manager=Mock(),
        tenant_manager=Mock(),
    )


@pytest.mark.asyncio
async def test_guard_passes_when_all_members_terminal() -> None:
    run = {
        "id": "run-1",
        "resolved_order": ["p1", "p2"],
        "project_statuses": {"p1": "completed", "p2": "failed"},
    }
    with patch(
        "giljo_mcp.services.job_completion_staging.heal_chain_member_statuses",
        AsyncMock(),
    ) as mock_heal:
        await _run_guard(run)
        mock_heal.assert_not_awaited()


@pytest.mark.asyncio
async def test_guard_self_heals_stale_copy_then_passes() -> None:
    run = {
        "id": "run-1",
        "resolved_order": ["p1", "p2"],
        "project_statuses": {"p1": "completed", "p2": "implementing"},
    }
    healed = {"p1": "completed", "p2": "completed"}
    with patch(
        "giljo_mcp.services.job_completion_staging.heal_chain_member_statuses",
        AsyncMock(return_value=healed),
    ) as mock_heal:
        await _run_guard(run)
        mock_heal.assert_awaited_once()


@pytest.mark.asyncio
async def test_guard_blocks_when_genuinely_incomplete() -> None:
    run = {
        "id": "run-1",
        "resolved_order": ["p1", "p2"],
        "project_statuses": {"p1": "completed", "p2": "implementing"},
    }
    with patch(
        "giljo_mcp.services.job_completion_staging.heal_chain_member_statuses",
        AsyncMock(return_value=run["project_statuses"]),
    ):
        with pytest.raises(ValidationError) as exc_info:
            await _run_guard(run)
    assert exc_info.value.error_code == "CONDUCTOR_CHAIN_INCOMPLETE"
    assert "chain run" in str(exc_info.value)
