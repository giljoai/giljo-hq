# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9292b / audit F1 — why the close_job recovery hint can be disarmed, characterized.

AUDIT_9292B found that the ``close_job`` wrong-state recovery hint fires only while the
execution reads literally ``'silent'``, and that ``_base._call_tool``'s ``auto_clear_silent``
post-hook flips that flag on ANY successful MCP call carrying the job_id — including an
orchestrator's own read ABOUT the stalled job. The auditor proposed re-gating the hint on
the CONDITION (non-terminal AND ``last_progress_at`` older than the silence threshold)
instead of on the mutable flag.

**These tests exist because that proposal does not work, and the reason is not obvious.**
``clear_silent_to_working`` does not only move the status — it also stamps
``last_progress_at = now()``. So after the disarming read the execution is neither
``'silent'`` NOR stale, and a staleness gate withholds the hint exactly as the flag gate
does. Worse, the two situations become indistinguishable in the persisted row: an
orchestrator reading about a stalled agent and the stalled agent itself waking up leave
byte-identical state, so no predicate over that state can separate them.

They are characterization tests: they pin what the code DOES today, so the follow-up that
closes F1 starts from proof rather than from argument, and so a future attempt at the
staleness gate fails here instead of shipping a fix that cannot fire. If the disarm is
ever closed at the mutation layer (caller identity, or a write-only tool allowlist), the
second test below is the one that should change, deliberately and with its reason stated.

Pure tests (no DB, no module-level mutable state) — parallel-safe under xdist.
Edition Scope: CE.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.services._error_helpers import _wrong_state_next_action
from giljo_mcp.services.silence_detector import DEFAULT_SILENCE_THRESHOLD_MINUTES


pytestmark = pytest.mark.asyncio


class _FlushOnlySession:
    """``clear_silent_to_working`` mutates the ORM object and flushes — nothing else."""

    def __init__(self) -> None:
        self.flushes = 0

    async def flush(self) -> None:
        self.flushes += 1


def _stalled_execution() -> AgentExecution:
    """An execution the health monitor marked silent well past the threshold."""
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
    """The disarm resets the very timestamp a staleness gate would key on."""
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
    """Flag gate and staleness gate both withhold — this is F1, characterized."""
    execution = _stalled_execution()
    await AgentOperationsRepository().clear_silent_to_working(_FlushOnlySession(), execution)

    next_action = _wrong_state_next_action(
        job_id="job-9292b-f1",
        project_id="proj-9292b-f1",
        actual_status=execution.status,
        expected_status="complete",
    )

    # Gate as shipped: keyed on the literal flag, now cleared.
    assert next_action["tool"] == "diagnose_project_state"
    # Gate as proposed by the audit: keyed on staleness, now refreshed. Same outcome.
    assert datetime.now(UTC) - execution.last_progress_at < timedelta(minutes=DEFAULT_SILENCE_THRESHOLD_MINUTES)


async def test_the_disarm_is_indistinguishable_from_a_genuine_revival() -> None:
    """Why no hint-layer predicate can work: both paths leave identical rows.

    ``auto_clear_silent`` carries no caller identity, so 'the orchestrator read about a
    stalled agent' and 'the stalled agent itself woke up' run the SAME mutation. Every
    durable marker of the earlier silence (``health_status``, ``block_reason``) is left
    untouched by both, so keying on one would fire for a genuinely revived, live agent —
    reintroducing the over-fire that ``test_be8003b_batch_validation_errors_mcp_boundary``
    and this project's own 'working' case exist to prevent.
    """
    disarmed_by_bystander = _stalled_execution()
    revived_by_the_agent_itself = _stalled_execution()

    repo = AgentOperationsRepository()
    await repo.clear_silent_to_working(_FlushOnlySession(), disarmed_by_bystander)
    await repo.clear_silent_to_working(_FlushOnlySession(), revived_by_the_agent_itself)

    def _observable(execution: AgentExecution) -> tuple:
        return (execution.status, execution.health_status, execution.block_reason)

    assert _observable(disarmed_by_bystander) == _observable(revived_by_the_agent_itself)
    # And the sticky markers still assert the OLD verdict, which is why they are unusable
    # as a hint predicate: they never get reset for an agent that genuinely came back.
    assert disarmed_by_bystander.health_status == "timeout"
    assert disarmed_by_bystander.block_reason is not None
