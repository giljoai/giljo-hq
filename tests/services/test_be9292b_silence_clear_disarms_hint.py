# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.services._error_helpers import _wrong_state_next_action
from giljo_mcp.services.silence_detector import DEFAULT_SILENCE_THRESHOLD_MINUTES


pytestmark = pytest.mark.asyncio


class _FlushOnlySession:

    def __init__(self) -> None:
        self.flushes = 0

    async def flush(self) -> None:
        self.flushes += 1


def _stalled_execution() -> AgentExecution:
    long_ago = datetime.now(UTC) - timedelta(minutes=DEFAULT_SILENCE_THRESHOLD_MINUTES * 4)
    return AgentExecution(
        job_id="job-9292b-f1",
        tenant_key="tk-9292b-f1",
        agent_display_name="implementer",
        status="silent",
        last_progress_at=long_ago,
        health_status="timeout",
        block_reason="Auto-detected timeout: no progress for 40m",
    )


async def test_clearing_silence_also_refreshes_last_progress_at() -> None:
    execution = _stalled_execution()
    before = execution.last_progress_at
    session = _FlushOnlySession()

    await AgentOperationsRepository().clear_silent_to_working(session, execution)

    assert execution.status == "working"
    assert execution.last_progress_at > before
    staleness = datetime.now(UTC) - execution.last_progress_at
    assert staleness < timedelta(minutes=DEFAULT_SILENCE_THRESHOLD_MINUTES), (
        "clear_silent_to_working stamps last_progress_at=now, so the execution reads FRESH "
        "immediately after a bystander read — the auditor's proposed 'non-terminal AND stale' "
        "gate cannot fire here either. F1 is not closable at the hint layer."
    )


async def test_hint_withholds_after_the_disarm_under_both_candidate_gates() -> None:
    execution = _stalled_execution()
    await AgentOperationsRepository().clear_silent_to_working(_FlushOnlySession(), execution)

    next_action = _wrong_state_next_action(
        job_id="job-9292b-f1",
        project_id="proj-9292b-f1",
        actual_status=execution.status,
        expected_status="complete",
    )

    assert next_action["tool"] == "diagnose_project_state"
    assert datetime.now(UTC) - execution.last_progress_at < timedelta(minutes=DEFAULT_SILENCE_THRESHOLD_MINUTES)


async def test_the_disarm_is_indistinguishable_from_a_genuine_revival() -> None:
    disarmed_by_bystander = _stalled_execution()
    revived_by_the_agent_itself = _stalled_execution()

    repo = AgentOperationsRepository()
    await repo.clear_silent_to_working(_FlushOnlySession(), disarmed_by_bystander)
    await repo.clear_silent_to_working(_FlushOnlySession(), revived_by_the_agent_itself)

    def _observable(execution: AgentExecution) -> tuple:
        return (execution.status, execution.health_status, execution.block_reason)

    assert _observable(disarmed_by_bystander) == _observable(revived_by_the_agent_itself)
    assert disarmed_by_bystander.health_status == "timeout"
    assert disarmed_by_bystander.block_reason is not None
