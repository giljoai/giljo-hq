# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.heartbeat import DEBOUNCE_SECONDS, touch_heartbeat


@pytest_asyncio.fixture
async def job_with_execution(db_session, test_tenant_key):
    job_id = str(uuid4())
    agent_id = str(uuid4())

    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        mission="heartbeat test",
        job_type="implementer",
        status="active",
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        agent_id=agent_id,
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_display_name="test-agent",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.flush()
    return job_id, agent_id, test_tenant_key


@pytest.mark.asyncio
async def test_heartbeat_sets_last_activity(db_session, job_with_execution):
    job_id, _, tenant_key = job_with_execution

    await touch_heartbeat(db_session, job_id, tenant_key=tenant_key)

    result = await db_session.execute(select(AgentExecution.last_activity_at).where(AgentExecution.job_id == job_id))
    ts = result.scalar_one()
    assert ts is not None
    assert (datetime.now(UTC) - ts).total_seconds() < 5


@pytest.mark.asyncio
async def test_heartbeat_debounce_skips_recent(db_session, job_with_execution):
    job_id, _, tenant_key = job_with_execution

    recent_ts = datetime.now(UTC) - timedelta(seconds=10)
    result = await db_session.execute(select(AgentExecution).where(AgentExecution.job_id == job_id))
    execution = result.scalar_one()
    execution.last_activity_at = recent_ts
    await db_session.flush()

    await touch_heartbeat(db_session, job_id, tenant_key=tenant_key)

    await db_session.refresh(execution)
    assert abs((execution.last_activity_at - recent_ts).total_seconds()) < 2


@pytest.mark.asyncio
async def test_heartbeat_updates_stale(db_session, job_with_execution):
    job_id, _, tenant_key = job_with_execution

    old_ts = datetime.now(UTC) - timedelta(seconds=DEBOUNCE_SECONDS + 10)
    result = await db_session.execute(select(AgentExecution).where(AgentExecution.job_id == job_id))
    execution = result.scalar_one()
    execution.last_activity_at = old_ts
    await db_session.flush()

    await touch_heartbeat(db_session, job_id, tenant_key=tenant_key)

    await db_session.refresh(execution)
    assert (datetime.now(UTC) - execution.last_activity_at).total_seconds() < 5


@pytest.mark.asyncio
async def test_heartbeat_skips_terminal_status(db_session, test_tenant_key):
    job_id = str(uuid4())
    agent_id = str(uuid4())

    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        mission="terminal test",
        job_type="implementer",
        status="completed",
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        agent_id=agent_id,
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_display_name="test-agent",
        status="complete",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.flush()

    await touch_heartbeat(db_session, job_id, tenant_key=test_tenant_key)

    await db_session.refresh(execution)
    assert execution.last_activity_at is None


@pytest.mark.asyncio
async def test_heartbeat_nonexistent_job_is_noop(db_session, test_tenant_key):
    fake_job_id = str(uuid4())
    await touch_heartbeat(db_session, fake_job_id, tenant_key=test_tenant_key)


@pytest.mark.asyncio
async def test_heartbeat_skips_closed_status(db_session, test_tenant_key):
    job_id = str(uuid4())
    agent_id = str(uuid4())

    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        mission="closed test",
        job_type="implementer",
        status="completed",
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        agent_id=agent_id,
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_display_name="test-agent",
        status="closed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.flush()

    await touch_heartbeat(db_session, job_id, tenant_key=test_tenant_key)

    await db_session.refresh(execution)
    assert execution.last_activity_at is None


@pytest.mark.asyncio
async def test_heartbeat_skips_decommissioned_status(db_session, test_tenant_key):
    job_id = str(uuid4())
    agent_id = str(uuid4())

    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        mission="decom test",
        job_type="implementer",
        status="completed",
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        agent_id=agent_id,
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_display_name="test-agent",
        status="decommissioned",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.flush()

    await touch_heartbeat(db_session, job_id, tenant_key=test_tenant_key)

    await db_session.refresh(execution)
    assert execution.last_activity_at is None
