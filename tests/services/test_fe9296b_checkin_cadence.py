# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9296b — retire the cadence sliders: one durable account-level default.

Covers the new plumbing at the layers it lives:

- resolve_agent_checkin_cadence_minutes: THE precedence rule (project override
  -> tenant override -> system_settings -> 10), including malformed-row
  tolerance for the schemaless configurations JSONB.
- SystemSettingsService cadence get/update (deployment-wide value).
- get_workflow_status surfaces the RESOLVED checkin_cadence_minutes (the live
  value a running orchestrator's CH6 loop re-reads each cycle) while keeping
  the legacy auto_checkin_* fields for in-flight protocols (tolerance).
- get_my_turn fills a loop directive armed WITHOUT an explicit cadence with the
  account default (chat-surface agents read one concrete number).
- set_agent_status stores the structured wake markers the dashboard indicator
  parses: wake_on_signal -> `wake_mode=signal`, wake_in_minutes -> timer marker.
- the project-less chain conductor's mission carries the CH6 conductor variant
  (DoD 6: a conductor observably receives a check-in cadence).

Real DB where the behaviour is storage-backed (rollback-isolated db_session),
mock-based where the behaviour is pure service logic. Parallel-safe.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.system_setting import SystemSetting
from giljo_mcp.repositories.configuration_repository import ConfigurationRepository
from giljo_mcp.services.settings_service import (
    AGENT_CHECKIN_CADENCE_KEY,
    DEFAULT_AGENT_CHECKIN_CADENCE_MINUTES,
    SystemSettingsService,
    resolve_agent_checkin_cadence_minutes,
)
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# The precedence rule
# ---------------------------------------------------------------------------


async def _set_system_cadence(db_session, value: str) -> None:
    db_session.add(SystemSetting(key=AGENT_CHECKIN_CADENCE_KEY, value=value))
    await db_session.flush()


async def _set_tenant_override(db_session, tenant_key: str, value) -> None:
    await ConfigurationRepository(None).upsert_value(
        db_session, tenant_key, AGENT_CHECKIN_CADENCE_KEY, value, category="system"
    )
    await db_session.flush()


def _project(*, enabled: bool, interval: int) -> Project:
    # Never persisted — the resolver only reads attributes off the row.
    return Project(
        id=str(uuid.uuid4()),
        name="cadence project",
        description="",
        mission="",
        status="active",
        tenant_key="tk-unused",
        series_number=99296,
        auto_checkin_enabled=enabled,
        auto_checkin_interval=interval,
    )


async def test_resolve_defaults_to_ten_with_nothing_set(db_session):
    tenant = TenantManager.generate_tenant_key()
    assert await resolve_agent_checkin_cadence_minutes(db_session, tenant) == (DEFAULT_AGENT_CHECKIN_CADENCE_MINUTES)


async def test_resolve_reads_the_deployment_wide_system_setting(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _set_system_cadence(db_session, "45")
    assert await resolve_agent_checkin_cadence_minutes(db_session, tenant) == 45


async def test_resolve_tenant_override_beats_system_setting(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _set_system_cadence(db_session, "45")
    await _set_tenant_override(db_session, tenant, 20)
    assert await resolve_agent_checkin_cadence_minutes(db_session, tenant) == 20


async def test_resolve_tenant_override_is_tenant_scoped(db_session):
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    await _set_tenant_override(db_session, tenant_a, 20)
    assert await resolve_agent_checkin_cadence_minutes(db_session, tenant_b) == (DEFAULT_AGENT_CHECKIN_CADENCE_MINUTES)


async def test_resolve_project_override_wins_when_slider_era_flag_is_on(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _set_system_cadence(db_session, "45")
    await _set_tenant_override(db_session, tenant, 20)
    project = _project(enabled=True, interval=30)
    assert await resolve_agent_checkin_cadence_minutes(db_session, tenant, project) == 30


async def test_resolve_ignores_project_columns_when_flag_is_off(db_session):
    # enabled=False is the column DEFAULT — a project the user never dialed must
    # follow the account default, not its default-10 column.
    tenant = TenantManager.generate_tenant_key()
    await _set_system_cadence(db_session, "45")
    project = _project(enabled=False, interval=30)
    assert await resolve_agent_checkin_cadence_minutes(db_session, tenant, project) == 45


@pytest.mark.parametrize("bad", [True, "not-a-number", 0, -5, 99999, None, [7]])
async def test_resolve_drops_malformed_tenant_override(db_session, bad):
    """configurations.value is schemaless JSONB — a row written outside the
    validated path must degrade to the next precedence level, never crash."""
    tenant = TenantManager.generate_tenant_key()
    await _set_system_cadence(db_session, "45")
    await _set_tenant_override(db_session, tenant, bad)
    assert await resolve_agent_checkin_cadence_minutes(db_session, tenant) == 45


# ---------------------------------------------------------------------------
# SystemSettingsService cadence pair
# ---------------------------------------------------------------------------


async def test_system_settings_cadence_roundtrip(db_session):
    svc = SystemSettingsService(db_session)
    assert await svc.get_agent_checkin_cadence_minutes() is None
    assert await svc.update_agent_checkin_cadence_minutes(35) == 35
    assert await svc.get_agent_checkin_cadence_minutes() == 35
    # Upsert, not insert-twice.
    assert await svc.update_agent_checkin_cadence_minutes(40) == 40
    assert await svc.get_agent_checkin_cadence_minutes() == 40


@pytest.mark.parametrize("bad", [0, -1, "10", 10.5, True])
async def test_system_settings_cadence_rejects_invalid_input(db_session, bad):
    svc = SystemSettingsService(db_session)
    with pytest.raises(ValidationError):
        await svc.update_agent_checkin_cadence_minutes(bad)


# ---------------------------------------------------------------------------
# get_workflow_status surfaces the resolved cadence
# ---------------------------------------------------------------------------


async def test_workflow_status_surfaces_resolved_cadence(db_session, test_tenant_key):
    from giljo_mcp.services.workflow_status_service import WorkflowStatusService

    await _set_system_cadence(db_session, "25")
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name="WF cadence",
        description="",
        mission="m",
        status="active",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        series_number=99297,
        auto_checkin_enabled=False,
        auto_checkin_interval=10,
    )
    db_session.add(project)
    await db_session.flush()

    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    service = WorkflowStatusService(db_manager=MagicMock(), tenant_manager=tenant_manager, test_session=db_session)

    status = await service.get_workflow_status(project.id, test_tenant_key)
    # Resolved: no project override (flag off) -> deployment value.
    assert status.checkin_cadence_minutes == 25
    # Tolerance: the legacy raw-column fields stay for in-flight CH6 prose.
    assert status.auto_checkin_enabled is False
    assert status.auto_checkin_interval == 10


async def test_workflow_status_cadence_honours_project_override(db_session, test_tenant_key):
    from giljo_mcp.services.workflow_status_service import WorkflowStatusService

    await _set_system_cadence(db_session, "25")
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name="WF cadence override",
        description="",
        mission="m",
        status="active",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        series_number=99298,
        auto_checkin_enabled=True,
        auto_checkin_interval=60,
    )
    db_session.add(project)
    await db_session.flush()

    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    service = WorkflowStatusService(db_manager=MagicMock(), tenant_manager=tenant_manager, test_session=db_session)

    status = await service.get_workflow_status(project.id, test_tenant_key)
    assert status.checkin_cadence_minutes == 60


# ---------------------------------------------------------------------------
# get_my_turn fills an interval-less loop directive with the account default
# ---------------------------------------------------------------------------


async def test_get_my_turn_fills_unset_loop_directive_interval(db_session):
    from giljo_mcp.services.comm_thread_service import CommThreadService
    from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded

    tenant = TenantManager.generate_tenant_key()
    from giljo_mcp.database import tenant_session_context

    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    await _set_system_cadence(db_session, "35")

    comm = CommThreadService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    thread = await comm.create_thread(subject="loop", creator_id="orchestrator", tenant_key=tenant)
    await comm.join_thread(thread_id=thread["thread_id"], participant_id="worker-1", tenant_key=tenant)
    # Armed WITHOUT an explicit cadence — the old behaviour surfaced None and
    # every harness invented its own number.
    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="loop please",
        from_agent="orchestrator",
        loop_directive=True,
        tenant_key=tenant,
    )

    mine = await comm.get_my_turn(agent_id="worker-1", tenant_key=tenant)
    assert len(mine["loop_directives"]) == 1
    assert mine["loop_directives"][0]["interval_minutes"] == 35


async def test_get_my_turn_keeps_an_explicit_loop_directive_interval(db_session):
    from giljo_mcp.services.comm_thread_service import CommThreadService
    from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded

    tenant = TenantManager.generate_tenant_key()
    from giljo_mcp.database import tenant_session_context

    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    await _set_system_cadence(db_session, "35")

    comm = CommThreadService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    thread = await comm.create_thread(subject="loop", creator_id="orchestrator", tenant_key=tenant)
    await comm.join_thread(thread_id=thread["thread_id"], participant_id="worker-1", tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="loop please",
        from_agent="orchestrator",
        loop_directive=True,
        loop_interval_minutes=15,
        tenant_key=tenant,
    )

    mine = await comm.get_my_turn(agent_id="worker-1", tenant_key=tenant)
    assert mine["loop_directives"][0]["interval_minutes"] == 15


# ---------------------------------------------------------------------------
# set_agent_status wake markers (what the dashboard indicator parses)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _fake_session_ctx(session):
    yield session


def _state_service_with_mocks():
    from giljo_mcp.services.orchestration_agent_state_service import (
        OrchestrationAgentStateService,
    )

    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = "tk-test"
    svc = OrchestrationAgentStateService(db_manager=MagicMock(), tenant_manager=tenant_manager)

    session = AsyncMock()
    session.info = {}
    svc._get_session = MagicMock(return_value=_fake_session_ctx(session))

    execution = MagicMock()
    execution.status = "working"
    execution.agent_display_name = "implementer"  # bypasses the staging lock
    execution.agent_name = "impl-1"
    execution.duration_seconds = None
    execution.working_started_at = None

    job = MagicMock()
    job.project_id = None
    job.job_metadata = {}

    svc._job_repo = MagicMock()
    svc._job_repo.find_active_execution_for_job = AsyncMock(return_value=execution)
    svc._job_repo.get_agent_job_by_job_id = AsyncMock(return_value=job)
    svc._job_repo.flush = AsyncMock()
    svc._websocket_manager = None
    return svc, execution


async def test_set_agent_status_wake_on_signal_stores_signal_marker():
    svc, execution = _state_service_with_mocks()

    result = await svc.set_agent_status(
        job_id="job-1",
        status="sleeping",
        reason="Waiting for Hub activity",
        wake_on_signal=True,
        tenant_key="tk-test",
    )

    assert execution.block_reason == "Waiting for Hub activity | wake_mode=signal"
    assert "wake_mode=signal" in result.block_reason


async def test_set_agent_status_wake_on_signal_wins_over_timer():
    # An agent parked on await_my_turn has no timed wake — the timer marker
    # would lie, so the signal marker must win when both are passed.
    svc, execution = _state_service_with_mocks()

    await svc.set_agent_status(
        job_id="job-1",
        status="sleeping",
        reason="",
        wake_in_minutes=10,
        wake_on_signal=True,
        tenant_key="tk-test",
    )

    assert execution.block_reason == "wake_mode=signal"


async def test_set_agent_status_timer_marker_unchanged():
    svc, execution = _state_service_with_mocks()

    await svc.set_agent_status(
        job_id="job-1",
        status="sleeping",
        reason="Auto check-in: sleeping for 10 minutes",
        wake_in_minutes=10,
        tenant_key="tk-test",
    )

    assert execution.block_reason == "Auto check-in: sleeping for 10 minutes | wake_in_minutes=10"


# ---------------------------------------------------------------------------
# DoD 6 — the project-less conductor observably receives a check-in cadence
# ---------------------------------------------------------------------------


class _FakeJob:
    def __init__(self, *, project_id, job_type="orchestrator", job_id="job-x"):
        self.project_id = project_id
        self.job_type = job_type
        self.job_id = job_id
        self.mission = ""
        self.created_at = None


class _FakeExec:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.agent_display_name = "orchestrator"
        self.agent_name = "orchestrator"
        self.spawned_by = None
        self.status = "working"
        self.started_at = None
        self.project_phase = None


async def test_projectless_conductor_mission_carries_conductor_ch6(db_manager):
    """A multi_terminal chain's project-less conductor gets the CH6 conductor
    variant seeded with the caller-resolved cadence. Before FE-9296b it could
    never receive CH6 at all (the injection required a project row)."""
    from giljo_mcp.models.sequence_runs import SequenceRun
    from giljo_mcp.services.mission_service import MissionService

    p1 = str(uuid.uuid4())
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        session.add(
            SequenceRun(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                project_ids=[p1],
                resolved_order=[p1],
                current_index=0,
                execution_mode="multi_terminal",
                status="running",
                locked=True,
                conductor_agent_id="cond-1",
                project_statuses={p1: "pending"},
            )
        )
        await session.commit()

    svc = MissionService(db_manager=db_manager, tenant_manager=TenantManager())
    job = _FakeJob(project_id=None, job_id="job-cond")
    execution = _FakeExec("cond-1")

    async with svc._get_session(tenant_key) as session:
        chain_mode = await svc._resolve_chain_execution_mode(session, job, execution, tenant_key)
    assert chain_mode == "multi_terminal"

    resp = svc._assemble_mission_context(
        job=job,
        execution=execution,
        project=None,
        agent_identity=None,
        all_project_executions=[execution],
        mission_lookup={job.job_id: ""},
        current_team_state=None,
        tenant_key=tenant_key,
        integrations={},
        chain_execution_mode=chain_mode,
        checkin_cadence_minutes=25,
    )

    assert "CH6: CHECK-IN CADENCE — CHAIN CONDUCTOR" in resp.full_protocol
    assert "25 minutes" in resp.full_protocol
    assert "await_my_turn" in resp.full_protocol


async def test_cli_chain_conductor_also_gets_conductor_ch6(db_manager):
    """A claude_code_cli chain's conductor ALSO receives the conductor CH6.

    BE-6205 pins the project-less conductor's header mode to multi_terminal for
    every chain mode (it always spawns sub-orchestrators in fresh terminals),
    so the CH6 gate — keyed off that same resolved mode — fires for it too.
    That is desirable: DoD 6 wants EVERY conductor to carry a cadence, and the
    conductor variant's wake branch is exactly right for a CLI-harness
    conductor. Project-BOUND orchestrators on CLI modes still get no CH6
    (pinned by test_orchestration_service_agent_mission + BE-9335)."""
    from giljo_mcp.models.sequence_runs import SequenceRun
    from giljo_mcp.services.mission_service import MissionService

    p1 = str(uuid.uuid4())
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        session.add(
            SequenceRun(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                project_ids=[p1],
                resolved_order=[p1],
                current_index=0,
                execution_mode="claude_code_cli",
                status="running",
                locked=True,
                conductor_agent_id="cond-2",
                project_statuses={p1: "pending"},
            )
        )
        await session.commit()

    svc = MissionService(db_manager=db_manager, tenant_manager=TenantManager())
    job = _FakeJob(project_id=None, job_id="job-cond-cli")
    execution = _FakeExec("cond-2")

    async with svc._get_session(tenant_key) as session:
        chain_mode = await svc._resolve_chain_execution_mode(session, job, execution, tenant_key)
    # BE-6205: the conductor header is PINNED to multi_terminal for every run mode.
    assert chain_mode == "multi_terminal"

    resp = svc._assemble_mission_context(
        job=job,
        execution=execution,
        project=None,
        agent_identity=None,
        all_project_executions=[execution],
        mission_lookup={job.job_id: ""},
        current_team_state=None,
        tenant_key=tenant_key,
        integrations={},
        chain_execution_mode=chain_mode,
        checkin_cadence_minutes=25,
    )

    assert "CH6: CHECK-IN CADENCE — CHAIN CONDUCTOR" in resp.full_protocol
