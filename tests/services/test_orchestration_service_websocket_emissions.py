# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Handover 0379e: SaaS Broker (Pub/Sub) + Loopback Elimination

These tests enforce that OrchestrationService emits WebSocket events via the
in-process WebSocketManager.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.services.orchestration_service import OrchestrationService


# pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_db_manager():
    db_manager = MagicMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.info = {}  # tenant_session_context save/restore target
    db_manager.get_session_async = MagicMock(return_value=session)
    return db_manager, session


@pytest.fixture
def mock_tenant_manager():
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant = MagicMock(return_value="tenant-test-123")
    return tenant_manager


@pytest.fixture
def mock_websocket_manager():
    return AsyncMock()


@pytest.fixture
def orchestration_service(mock_db_manager, mock_tenant_manager, mock_websocket_manager):
    db_manager, _ = mock_db_manager
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=mock_tenant_manager,
        websocket_manager=mock_websocket_manager,
    )


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _rows_result(rows):
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return result


async def test_get_agent_mission_emits_ack_and_status_changed(
    orchestration_service,
    mock_db_manager,
    mock_websocket_manager,
):
    _db_manager, session = mock_db_manager
    tenant_key = "tenant-test-123"
    project_id = str(uuid4())
    job_id = str(uuid4())
    agent_id = str(uuid4())

    job = SimpleNamespace(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        mission="Do work",
        created_at=datetime.now(UTC),
        job_type="orchestrator",
    )
    execution = SimpleNamespace(
        agent_id=agent_id,
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        agent_name="impl-worker-1",
        spawned_by=None,
        status="waiting",
        mission_acknowledged_at=None,
        started_at=None,
        duration_seconds=None,
        working_started_at=None,
    )
    project = SimpleNamespace(
        id=project_id,
        tenant_key=tenant_key,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
    )

    session.execute.side_effect = [
        _scalar_result(job),
        _scalar_result(execution),
        _scalar_result(project),
        # TSK-9459: get_agent_mission now resolves the project's bound Hub thread
        # for the ORCHESTRATOR too, so it is joined structurally instead of being
        # left off its own thread. This mocked test does not exercise the Hub —
        # let the resolver take its documented best-effort degradation to None.
        RuntimeError("TSK-9459: no Hub thread in this mocked session"),
        _rows_result([(execution, job)]),
        # Extra entries to cover additional queries in _resolve_mission_template
        # (project lookup) and other downstream code added since this test was
        # first written. Excess entries are harmless if not consumed.
        _scalar_result(project),
        _scalar_result(project),
        _scalar_result(project),
    ]

    await orchestration_service.get_agent_mission(job_id=job_id, tenant_key=tenant_key)

    # No success wrapper after 0730b refactor
    assert execution.status == "working"
    assert execution.started_at is not None

    event_types = [c.kwargs["event_type"] for c in mock_websocket_manager.broadcast_to_tenant.await_args_list]
    assert "agent:status_changed" in event_types


async def test_get_agent_mission_is_idempotent_and_does_not_re_emit(
    orchestration_service,
    mock_db_manager,
    mock_websocket_manager,
):
    _db_manager, session = mock_db_manager
    tenant_key = "tenant-test-123"
    project_id = str(uuid4())
    job_id = str(uuid4())
    agent_id = str(uuid4())

    job = SimpleNamespace(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        mission="Do work",
        created_at=datetime.now(UTC),
        job_type="orchestrator",
    )
    execution = SimpleNamespace(
        agent_id=agent_id,
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        agent_name="impl-worker-1",
        spawned_by=None,
        status="working",
        mission_acknowledged_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        working_started_at=datetime.now(UTC),
    )
    project = SimpleNamespace(
        id=project_id,
        tenant_key=tenant_key,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
    )

    session.execute.side_effect = [
        _scalar_result(job),
        _scalar_result(execution),
        _scalar_result(project),
        # TSK-9459: get_agent_mission now resolves the project's bound Hub thread
        # for the ORCHESTRATOR too, so it is joined structurally instead of being
        # left off its own thread. This mocked test does not exercise the Hub —
        # let the resolver take its documented best-effort degradation to None.
        RuntimeError("TSK-9459: no Hub thread in this mocked session"),
        _rows_result([(execution, job)]),
        # Extra entries to cover additional queries in _resolve_mission_template
        # (project lookup) and other downstream code added since this test was
        # first written. Excess entries are harmless if not consumed.
        _scalar_result(project),
        _scalar_result(project),
        _scalar_result(project),
    ]

    await orchestration_service.get_agent_mission(job_id=job_id, tenant_key=tenant_key)

    # No success wrapper after 0730b refactor
    mock_websocket_manager.broadcast_to_tenant.assert_not_awaited()


async def test_complete_job_emits_status_changed_with_duration_seconds(
    orchestration_service,
    mock_db_manager,
    mock_websocket_manager,
):
    _db_manager, session = mock_db_manager
    tenant_key = "tenant-test-123"
    job_id = str(uuid4())

    started_at = datetime.now(UTC) - timedelta(seconds=60)
    execution = SimpleNamespace(
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        agent_name="impl-worker-1",
        status="working",
        started_at=started_at,
        working_started_at=started_at,
        completed_at=None,
        progress=0,
        duration_seconds=60.0,
    )
    job = SimpleNamespace(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=str(uuid4()),
        status="active",
        completed_at=None,
        job_type="orchestrator",
    )

    # complete_job's execute calls for orchestrator jobs:
    # 1. execution lookup (scalar_one_or_none)
    # 2. job lookup (scalar_one_or_none)
    # 3. unread messages (scalars().all())
    # 4. todo items (scalars().all())
    # 5. other active executions (scalar_one_or_none)
    # 6. find orchestrator execution for auto-completion message (scalar_one_or_none)
    #
    # Of the two trailing entries this list used to carry, only the LAST was spare.
    # Both were labelled as 360-memory lookups, and the 360-memory query really is
    # gone (BE-5028 "Fix A" removed the warning that called it; IMP-9342 deleted the
    # orphaned _check_360_memory_written and its repository query). But the
    # second-to-last entry was feeding a live call it was never named for: the
    # conductor-purge (complete_chain_run_if_finished -> find_active_run_for_conductor),
    # which now takes the StopIteration from this shortened list and swallows it in the
    # broad except at project_helpers.py:650. The call_count assert after the call under
    # test pins the real total so a future 10th execute cannot hide in that same swallow.
    unread_result = MagicMock()
    unread_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    todo_result = MagicMock()
    todo_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    session.execute.side_effect = [
        _scalar_result(execution),
        _scalar_result(job),
        # BE-6177 (C1): the conductor-chain guard runs for every orchestrator
        # complete_job and queries find_active_run_for_conductor. None = this
        # agent is not a conductor (solo), so the guard no-ops (byte-identical).
        _scalar_result(None),  # conductor guard: no active run for this agent
        unread_result,  # unread messages (empty list)
        todo_result,  # todo items (empty list)
        _scalar_result(None),  # BE-9153: closeout_mode settings read (no row -> default hitl; clean result -> no gate)
        _scalar_result(None),  # other active executions (none)
        _scalar_result(None),  # find_orchestrator_execution (none — skip auto-message)
    ]

    result = await orchestration_service.complete_job(job_id=job_id, result={"ok": True}, tenant_key=tenant_key)

    # Pinned: 9 execute calls, one more than this 8-entry list feeds. Call 9 is the
    # conductor-purge, whose broad except swallows the resulting StopIteration.
    assert session.execute.call_count == 9

    # Handover 0731c: Returns CompleteJobResult typed model.
    # BE-9153: a CLEAN orchestrator closeout completes under the default (hitl) mode —
    # the gate blocks only on signal, and result={"ok": True} carries none. (Was the
    # vacuous ``in ("success", "blocked_hitl")`` — "blocked_hitl" is produced nowhere.)
    assert result.status == "success"
    assert execution.status == "complete"

    last_call = mock_websocket_manager.broadcast_to_tenant.await_args_list[-1].kwargs
    assert last_call["event_type"] == "agent:status_changed"
    assert last_call["data"]["status"] == "complete"
    assert 59 <= last_call["data"]["duration_seconds"] <= 61


async def test_report_progress_fallback_emits_message_new_event(
    orchestration_service,
    mock_db_manager,
    mock_websocket_manager,
    monkeypatch,
):
    _db_manager, session = mock_db_manager
    tenant_key = "tenant-test-123"
    job_id = str(uuid4())

    execution = SimpleNamespace(
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        agent_name="impl-worker-1",
        status="working",
        started_at=datetime.now(UTC),
        mission_acknowledged_at=datetime.now(UTC),
        working_started_at=datetime.now(UTC),
    )
    job = SimpleNamespace(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=str(uuid4()),
        job_metadata={},  # Required for websocket broadcast
        job_type="orchestrator",
    )

    # report_progress uses 2 session contexts with 3 total execute calls:
    # Session 1: execution, job (both scalar_one_or_none)
    # Session 2: todo_items (scalars().all())
    todo_items_result = MagicMock()
    todo_items_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    session.execute.side_effect = [
        _scalar_result(execution),
        _scalar_result(job),
        todo_items_result,  # todo_items query (empty list)
    ]

    # Force fallback path by ensuring MessageService is unavailable
    orchestration_service._message_service = None

    result = await orchestration_service.report_progress(
        job_id=job_id,
        progress={"percent": 50, "message": "Half done"},
        tenant_key=tenant_key,
    )

    # Handover 0731c: Returns ProgressResult typed model
    assert result.status == "success"
    mock_websocket_manager.broadcast_to_tenant.assert_awaited()

    # report_progress emits job:progress_update event (not message:new)
    last_call = mock_websocket_manager.broadcast_to_tenant.await_args_list[-1].kwargs
    assert last_call["tenant_key"] == tenant_key
    assert last_call["event_type"] == "job:progress_update"
