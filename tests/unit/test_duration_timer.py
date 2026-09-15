# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime, timedelta

import pytest

from giljo_mcp.models.agent_identity import AgentExecution


def _make_execution(status: str = "waiting") -> AgentExecution:
    return AgentExecution(
        agent_id="00000000-0000-0000-0000-000000000001",
        job_id="00000000-0000-0000-0000-00000000000a",
        tenant_key="t",
        agent_display_name="test-agent",
        status=status,
    )


def test_waiting_agent_has_no_duration():
    execution = _make_execution(status="waiting")
    assert execution.working_started_at is None
    assert execution.duration_seconds is None


def test_transition_to_working_anchors_once_and_ticks():
    execution = _make_execution(status="waiting")
    assert execution.working_started_at is None

    execution.status = "working"
    first_anchor = execution.working_started_at
    assert first_anchor is not None

    first_reading = execution.duration_seconds
    assert first_reading is not None
    assert first_reading >= 0.0

    execution.status = "working"
    assert execution.working_started_at == first_anchor


def test_reactivation_complete_to_working_does_not_reset_anchor():
    execution = _make_execution(status="waiting")
    execution.status = "working"
    original_anchor = execution.working_started_at
    assert original_anchor is not None

    execution.status = "complete"
    execution.completed_at = datetime.now(UTC)
    execution.status = "working"

    assert execution.working_started_at == original_anchor


def test_complete_status_freezes_duration_at_completed_at():
    execution = _make_execution(status="waiting")
    anchor = datetime.now(UTC) - timedelta(seconds=42)
    completed_at = anchor + timedelta(seconds=30)

    execution.working_started_at = anchor
    execution.completed_at = completed_at
    execution.status = "complete"

    assert execution.duration_seconds == pytest.approx(30.0, abs=0.5)


def test_closed_status_freezes_duration_at_completed_at():
    execution = _make_execution(status="waiting")
    anchor = datetime.now(UTC) - timedelta(seconds=100)
    completed_at = anchor + timedelta(seconds=75)

    execution.working_started_at = anchor
    execution.completed_at = completed_at
    execution.status = "closed"

    assert execution.duration_seconds == pytest.approx(75.0, abs=0.5)
