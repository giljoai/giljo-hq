# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text, update

from giljo_mcp.database import DatabaseManager, tenant_isolation_bypass
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.settings_service import AGENT_SILENCE_THRESHOLD_KEY
from giljo_mcp.services.silence_detector import SilenceDetector, _coerce_threshold_overrides
from giljo_mcp.tenant import TenantManager


def _ws_manager() -> AsyncMock:
    ws = AsyncMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    return ws


def _detector() -> SilenceDetector:
    return SilenceDetector(db_manager=Mock(spec=DatabaseManager), ws_manager=_ws_manager())


@pytest_asyncio.fixture(autouse=True)
async def _retire_stale_working_residue(db_manager):
    async with db_manager.get_session_async() as session:
        stmt = update(AgentExecution).where(AgentExecution.status == "working").values(status="decommissioned")
        with tenant_isolation_bypass(
            session,
            reason="BE-9373 test isolation: retire stale cross-run residue before exact-count assertions",
            models=(AgentExecution,),
        ):
            await session.execute(stmt)
        await session.commit()
    yield


async def _seed_working_agent(session, tenant_key: str, last_progress_at: datetime) -> AgentExecution:
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=None,
        job_type="implementer",
        mission="FE-9241 test mission",
        status="active",
        job_metadata={},
    )
    session.add(job)
    await session.flush()

    agent = AgentExecution(
        agent_id=str(uuid4()),
        tenant_key=tenant_key,
        job_id=job.job_id,
        agent_display_name="fe-9241-agent",
        status="working",
        started_at=last_progress_at,
        last_progress_at=last_progress_at,
    )
    session.add(agent)
    await session.flush()
    return agent


@pytest.mark.asyncio
async def test_tenant_override_flags_silent_before_deployment_default_would(db_session):
    tenant_override = TenantManager.generate_tenant_key()
    five_minutes_ago = datetime.now(UTC) - timedelta(minutes=5)

    agent = await _seed_working_agent(db_session, tenant_override, five_minutes_ago)

    count = await _detector()._detect_silent_agents(
        db_session,
        threshold_minutes=10,
        tenant_overrides={tenant_override: 2},
    )

    assert count == 1
    assert agent.status == "silent"


@pytest.mark.asyncio
async def test_unset_tenant_falls_back_to_deployment_default(db_session):
    tenant_no_override = TenantManager.generate_tenant_key()
    fifteen_minutes_ago = datetime.now(UTC) - timedelta(minutes=15)

    agent = await _seed_working_agent(db_session, tenant_no_override, fifteen_minutes_ago)

    count = await _detector()._detect_silent_agents(
        db_session,
        threshold_minutes=10,
        tenant_overrides={},
    )

    assert count == 1
    assert agent.status == "silent"


@pytest.mark.asyncio
async def test_tenant_within_its_own_override_window_is_not_flagged(db_session):
    tenant_loose_override = TenantManager.generate_tenant_key()
    seven_minutes_ago = datetime.now(UTC) - timedelta(minutes=7)

    agent = await _seed_working_agent(db_session, tenant_loose_override, seven_minutes_ago)

    count = await _detector()._detect_silent_agents(
        db_session,
        threshold_minutes=5,
        tenant_overrides={tenant_loose_override: 30},
    )

    assert count == 0
    assert agent.status == "working"


@pytest.mark.asyncio
async def test_no_overrides_matches_pre_fe9241_single_threshold_behavior(db_session):
    tenant = TenantManager.generate_tenant_key()
    twenty_minutes_ago = datetime.now(UTC) - timedelta(minutes=20)

    agent = await _seed_working_agent(db_session, tenant, twenty_minutes_ago)

    count = await _detector()._detect_silent_agents(db_session, threshold_minutes=10)

    assert count == 1
    assert agent.status == "silent"




@pytest.mark.parametrize(
    ("raw_value", "kept"),
    [
        ({"nested": "dict"}, False),
        ([1, 2, 3], False),
        (None, False),
        (True, False),
        (False, False),
        ("abc", False),
        (0, False),
        (-5, False),
        (1e400, False),
        (1441, False),
        (1440, True),
        (1, True),
        (45, True),
    ],
    ids=[
        "dict-value",
        "list-value",
        "none-value",
        "bool-true",
        "bool-false",
        "non-numeric-string",
        "zero",
        "negative",
        "float-overflow-1e400",
        "above-max-1441",
        "boundary-max-1440",
        "boundary-min-1",
        "mid-range-45",
    ],
)
def test_coerce_threshold_overrides_table_driven(raw_value, kept):
    result = _coerce_threshold_overrides({"tenant-under-test": raw_value})

    if kept:
        assert result == {"tenant-under-test": raw_value}
    else:
        assert result == {}


@pytest.mark.asyncio
async def test_run_detection_cycle_survives_malformed_override_row(db_manager):
    malformed_tenant = TenantManager.generate_tenant_key()
    valid_tenant = TenantManager.generate_tenant_key()
    twenty_minutes_ago = datetime.now(UTC) - timedelta(minutes=20)

    async with db_manager.get_session_async() as session:
        await session.execute(
            text(
                "INSERT INTO configurations (id, tenant_key, key, value, category) "
                "VALUES (:id, :tenant_key, :key, '1e400'::jsonb, 'system')"
            ),
            {"id": str(uuid4()), "tenant_key": malformed_tenant, "key": AGENT_SILENCE_THRESHOLD_KEY},
        )
        await session.commit()

        agent = await _seed_working_agent(session, valid_tenant, twenty_minutes_ago)

    detector = SilenceDetector(db_manager=db_manager, ws_manager=_ws_manager())

    await detector._run_detection_cycle()

    async with db_manager.get_session_async(tenant_key=valid_tenant) as verify_session:
        refreshed = await verify_session.get(AgentExecution, agent.id)
        assert refreshed.status == "silent"
