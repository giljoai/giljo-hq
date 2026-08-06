# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for SilenceDetector's per-tenant threshold fallback chain (FE-9241 — SaaS
per-tenant override with fallback: tenant override -> deployment-wide default ->
DEFAULT_SILENCE_THRESHOLD_MINUTES).

Exercises SilenceDetector._detect_silent_agents directly against real
AgentJob/AgentExecution rows (db_session, TransactionalTestContext) -- the
failing layer for this feature is the detector's per-agent threshold decision,
not the repository (already covered separately) or the endpoint (covered in
tests/api). CE parity: passing tenant_overrides={} (or omitting it) must behave
identically to the pre-FE-9241 single-threshold scan.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import text

from giljo_mcp.database import DatabaseManager
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
    await session.commit()
    return agent


@pytest.mark.asyncio
async def test_tenant_override_flags_silent_before_deployment_default_would(db_session):
    """A tenant with a tight 2-minute override is marked silent off 5 minutes of
    quiet, even though the 10-minute deployment default alone would NOT have
    flagged it yet -- proves the override is APPLIED, not ignored."""
    tenant_override = TenantManager.generate_tenant_key()
    five_minutes_ago = datetime.now(UTC) - timedelta(minutes=5)

    agent = await _seed_working_agent(db_session, tenant_override, five_minutes_ago)

    count = await _detector()._detect_silent_agents(
        db_session,
        threshold_minutes=10,  # deployment-wide default: 5 min of silence would NOT trip this alone
        tenant_overrides={tenant_override: 2},  # this tenant's own override: 5 min DOES trip 2 min
    )

    assert count == 1
    assert agent.status == "silent"


@pytest.mark.asyncio
async def test_unset_tenant_falls_back_to_deployment_default(db_session):
    """A tenant with NO override in tenant_overrides uses threshold_minutes (the
    deployment-wide default) -- the fallback chain's second link."""
    tenant_no_override = TenantManager.generate_tenant_key()
    fifteen_minutes_ago = datetime.now(UTC) - timedelta(minutes=15)

    agent = await _seed_working_agent(db_session, tenant_no_override, fifteen_minutes_ago)

    count = await _detector()._detect_silent_agents(
        db_session,
        threshold_minutes=10,
        tenant_overrides={},  # no override for this (or any) tenant
    )

    assert count == 1
    assert agent.status == "silent"


@pytest.mark.asyncio
async def test_tenant_within_its_own_override_window_is_not_flagged(db_session):
    """A tenant whose override is LOOSER than the deployment default is NOT
    flagged even though the default alone would have flagged it -- proves the
    per-agent drop-if-not-actually-stale step (not just the SQL pre-filter)."""
    tenant_loose_override = TenantManager.generate_tenant_key()
    seven_minutes_ago = datetime.now(UTC) - timedelta(minutes=7)

    agent = await _seed_working_agent(db_session, tenant_loose_override, seven_minutes_ago)

    count = await _detector()._detect_silent_agents(
        db_session,
        threshold_minutes=5,  # deployment default alone WOULD flag 7 min of silence
        tenant_overrides={tenant_loose_override: 30},  # this tenant's own override: 7 min does NOT trip 30 min
    )

    assert count == 0
    assert agent.status == "working"


@pytest.mark.asyncio
async def test_no_overrides_matches_pre_fe9241_single_threshold_behavior(db_session):
    """CE parity: an empty/omitted tenant_overrides dict behaves identically to
    the original single-global-threshold scan (every tenant uses threshold_minutes)."""
    tenant = TenantManager.generate_tenant_key()
    twenty_minutes_ago = datetime.now(UTC) - timedelta(minutes=20)

    agent = await _seed_working_agent(db_session, tenant, twenty_minutes_ago)

    # tenant_overrides omitted entirely (defaults to None -> {} internally).
    count = await _detector()._detect_silent_agents(db_session, threshold_minutes=10)

    assert count == 1
    assert agent.status == "silent"


# ---------------------------------------------------------------------------
# TSK-9271: resilience coverage for _coerce_threshold_overrides + the
# _run_detection_cycle path that feeds it -- audit follow-up on PR #600.
# `configurations.value` is schemaless JSONB, so a row written outside the
# validated TenantConfigurationService write path (a raw edit, a bad migration,
# manual DB surgery) can hold anything. These tests lock in that the coercion
# never raises and correctly keeps only genuinely valid int-in-range minutes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_value", "kept"),
    [
        ({"nested": "dict"}, False),
        ([1, 2, 3], False),
        (None, False),
        (True, False),  # bool is an int subclass -- must NOT silently coerce to 1
        (False, False),  # bool is an int subclass -- must NOT silently coerce to 0
        ("abc", False),
        (0, False),
        (-5, False),
        (1e400, False),  # JSON number so large it overflows a Python float to +inf
        (1441, False),
        (1440, True),  # upper boundary
        (1, True),  # lower boundary
        (45, True),  # ordinary mid-range value
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
    """_coerce_threshold_overrides never raises and drops everything except a
    genuine int in [1, 1440] -- table-driven across malformed/edge JSONB values."""
    result = _coerce_threshold_overrides({"tenant-under-test": raw_value})

    if kept:
        assert result == {"tenant-under-test": raw_value}
    else:
        assert result == {}


@pytest.mark.asyncio
async def test_run_detection_cycle_survives_malformed_override_row(db_manager):
    """End-to-end: a malformed `configurations` override row (written by
    bypassing the validated write path via a raw SQL insert, mirroring how a
    real malformed row could land in prod) must NOT crash the whole detection
    cycle -- and a stale agent in a DIFFERENT, valid tenant must still be
    correctly marked silent in that SAME cycle.

    Uses db_manager (real commits) rather than db_session (TransactionalTestContext)
    because SilenceDetector._run_detection_cycle opens its OWN session via
    self.db.get_session_async() -- a separate connection that would not see rows
    only committed inside a different transactional test session.
    """
    malformed_tenant = TenantManager.generate_tenant_key()
    valid_tenant = TenantManager.generate_tenant_key()
    twenty_minutes_ago = datetime.now(UTC) - timedelta(minutes=20)

    async with db_manager.get_session_async() as session:
        # Raw insert bypassing TenantConfigurationService.set_agent_silence_threshold_minutes
        # (which would reject this at the validated write boundary) -- simulates a row
        # already malformed in the database, e.g. from manual surgery or a bad migration.
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

    # Must complete without raising despite the malformed_tenant override row.
    await detector._run_detection_cycle()

    async with db_manager.get_session_async(tenant_key=valid_tenant) as verify_session:
        refreshed = await verify_session.get(AgentExecution, agent.id)
        assert refreshed.status == "silent"
