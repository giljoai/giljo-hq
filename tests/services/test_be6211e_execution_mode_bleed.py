# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.project_helpers import mark_chain_member_status
from giljo_mcp.services.protocol_sections.agent_lifecycle import _build_wake_pattern
from giljo_mcp.tenant import TenantManager



_SUBAGENT_TOOLS = ("claude-code", "codex")


def _wake(execution_mode: str) -> str:
    return _build_wake_pattern(execution_mode, executor_id="EXEC-1", tenant_key="TK-1")


def test_subagent_wake_blocks_use_inline_get_agent_result_not_sleep_poll() -> None:
    for mode in _SUBAGENT_TOOLS:
        block = _wake(mode)
        assert "get_agent_result" in block, f"{mode}: must point at get_agent_result for own workers"
        assert "BLOCKS" in block, f"{mode}: must state the spawn call BLOCKS / returns inline"
        assert "do NOT" in block and "sleep" in block, f"{mode}: must forbid sleep-polling own workers"
        assert "Sleep-and-check pattern (when waiting for agents)" not in block


def test_subagent_wake_blocks_keep_cross_terminal_receive_messages_note() -> None:
    for mode in _SUBAGENT_TOOLS:
        block = _wake(mode)
        assert "get_thread_history" in block, f"{mode}: must keep the cross-terminal get_thread_history note"


def test_multi_terminal_wake_block_is_unchanged_and_carries_no_own_worker_inline_prose() -> None:
    block = _wake("multi_terminal")
    assert "CONSTELLATION: MULTI-TERMINAL" in block
    assert "get_agent_result" not in block
    assert "The user mediates between sessions." in block


def test_unregistered_subagent_cli_fails_safe_to_subagent_generic_not_multi_terminal() -> None:
    for mode in ("some_future_cli",):
        block = _wake(mode)
        assert "get_agent_result" in block, f"{mode}: unknown subagent must get the inline-return contract"
        assert "CONSTELLATION: MULTI-TERMINAL" not in block, f"{mode}: must NOT leak the multi_terminal block"
        assert "The user mediates between sessions." not in block



pytestmark = pytest.mark.asyncio


async def _seed_run(
    session: AsyncSession,
    tenant_key: str,
    *,
    resolved_order: list[str],
    conductor_agent_id: str | None,
    project_statuses: dict[str, str] | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    run = SequenceRun(
        id=run_id,
        tenant_key=tenant_key,
        project_ids=resolved_order,
        resolved_order=resolved_order,
        current_index=0,
        execution_mode="claude_code_cli",
        status="running",
        review_policy="per_card",
        project_statuses=project_statuses or {},
        conductor_agent_id=conductor_agent_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return run_id


async def _seed_blocked_conductor(session: AsyncSession, tenant_key: str, conductor_agent_id: str) -> str:
    job_id = str(uuid.uuid4())
    session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=None,
            mission="drive the chain",
            job_type="orchestrator",
            status="completed",
            job_metadata={},
        )
    )
    session.add(
        AgentExecution(
            agent_id=conductor_agent_id,
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="conductor",
            agent_name="orchestrator",
            status="blocked",
            health_status="unknown",
            project_phase="implementation",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return job_id


async def _get_execution(session: AsyncSession, tenant_key: str, agent_id: str) -> AgentExecution:
    from giljo_mcp.repositories.agent_job_repository import AgentJobRepository

    repo = AgentJobRepository(None)
    execution = await repo.get_execution_by_agent_id(session, tenant_key, agent_id)
    assert execution is not None
    return execution


async def test_member_completed_event_wakes_blocked_conductor(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p0, p1 = str(uuid.uuid4()), str(uuid.uuid4())
    conductor_agent_id = str(uuid.uuid4())
    await _seed_run(
        db_session,
        tenant,
        resolved_order=[p0, p1],
        conductor_agent_id=conductor_agent_id,
        project_statuses={p0: "running"},
    )
    job_id = await _seed_blocked_conductor(db_session, tenant, conductor_agent_id)

    wrote = await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p0,
        tenant_key=tenant,
        status="completed",
        test_session=db_session,
    )
    assert wrote is True

    execution = await _get_execution(db_session, tenant, conductor_agent_id)
    assert execution.status == "working", "blocked conductor must be reactivated on the member closeout"

    from giljo_mcp.repositories.agent_job_repository import AgentJobRepository

    job = await AgentJobRepository(None).get_agent_job_by_job_id(db_session, tenant, job_id)
    assert job is not None and job.status == "active", "conductor job completed→active on reactivation"


async def test_member_completed_with_absent_conductor_is_non_fatal(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p0 = str(uuid.uuid4())
    await _seed_run(
        db_session,
        tenant,
        resolved_order=[p0],
        conductor_agent_id=str(uuid.uuid4()),
        project_statuses={p0: "running"},
    )

    wrote = await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p0,
        tenant_key=tenant,
        status="completed",
        test_session=db_session,
    )
    assert wrote is True


async def test_in_flight_status_does_not_event_wake_conductor(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p0 = str(uuid.uuid4())
    conductor_agent_id = str(uuid.uuid4())
    await _seed_run(
        db_session,
        tenant,
        resolved_order=[p0],
        conductor_agent_id=conductor_agent_id,
        project_statuses={p0: "running"},
    )
    await _seed_blocked_conductor(db_session, tenant, conductor_agent_id)

    wrote = await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p0,
        tenant_key=tenant,
        status="implementing",
        test_session=db_session,
    )
    assert wrote is True

    execution = await _get_execution(db_session, tenant, conductor_agent_id)
    assert execution.status == "blocked", "in-flight status must not reactivate the conductor"
