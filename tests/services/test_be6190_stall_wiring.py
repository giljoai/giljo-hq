# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6190: stall wiring — wire the dead mark_stalled_if_past_deadline into SilenceDetector.

The previously dead SequenceChainContextResolver.mark_stalled_if_past_deadline now has a
runtime caller: SilenceDetector._stall_runs_for_silenced_projects flips an active chain run
to "stalled" when its CURRENT in-flight member's orchestrator has gone silent past the
threshold. It reuses the agents the silence cycle already marked silent (no second scan,
no new background timer).

Invariants under test:
1/2. mark_stalled_if_past_deadline flips status="stalled" past the deadline, no-ops before.
3.   _stall_runs_for_silenced_projects stalls the run when the silent project is CURRENT.
4.   A silent NON-current member does NOT stall the run.
5.   A silent solo project (no active run) is a no-op (never raises).

Parallel-safe: DB-touching tests use db_session (TransactionalTestContext). No module-level
mutable state. Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.services.silence_detector import SilenceDetector
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6190 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        # BE-9429: uq_project_taxonomy_active is NULLS NOT DISTINCT, so these
        # NULL-product/NULL-type rows collide unless the serial differs.
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


def _resolver(session: AsyncSession) -> SequenceChainContextResolver:
    return SequenceChainContextResolver(db_manager=None, tenant_manager=TenantManager(), test_session=session)


def _detector(session: AsyncSession) -> SilenceDetector:
    # The stall path only uses self.db (forwarded as test_session into the resolver/run svc).
    # ws_manager is unused by _stall_runs_for_silenced_projects, so None is sufficient.
    return SilenceDetector(db_manager=None, ws_manager=None)


# ---------------------------------------------------------------------------
# 1. mark_stalled flips a running run to stalled past the deadline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_stalled_flips_run_past_deadline(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)

    run = await _run_svc(db_session).create(
        project_ids=[pid],
        resolved_order=[pid],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
        current_index=0,
    )

    past = datetime.now(UTC) - timedelta(minutes=30)
    later = datetime.now(UTC)

    flipped = await _resolver(db_session).mark_stalled_if_past_deadline(
        run_id=run["id"], tenant_key=tenant, deadline_iso_or_dt=past, now=later
    )
    assert flipped is True

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=pid, tenant_key=tenant)
    assert refreshed["status"] == "stalled"


# ---------------------------------------------------------------------------
# 2. mark_stalled is a no-op before the deadline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_stalled_noop_before_deadline(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)

    run = await _run_svc(db_session).create(
        project_ids=[pid],
        resolved_order=[pid],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
        current_index=0,
    )

    future = datetime.now(UTC) + timedelta(minutes=30)

    flipped = await _resolver(db_session).mark_stalled_if_past_deadline(
        run_id=run["id"], tenant_key=tenant, deadline_iso_or_dt=future, now=datetime.now(UTC)
    )
    assert flipped is False

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=pid, tenant_key=tenant)
    assert refreshed["status"] != "stalled"


# ---------------------------------------------------------------------------
# 3. the wired method stalls the run when the silent project is CURRENT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stall_current_member_run(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p0 = await _seed_project(db_session, tenant)
    p1 = await _seed_project(db_session, tenant)

    await _run_svc(db_session).create(
        project_ids=[p0, p1],
        resolved_order=[p0, p1],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
        current_index=0,
    )

    silenced = [(tenant, p0, datetime.now(UTC) - timedelta(minutes=60), 10)]
    await _detector(db_session)._stall_runs_for_silenced_projects(db_session, silenced)

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p0, tenant_key=tenant)
    assert refreshed["status"] == "stalled"


# ---------------------------------------------------------------------------
# 4. a silent NON-current member does NOT stall the run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_stall_for_noncurrent_member(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p0 = await _seed_project(db_session, tenant)
    p1 = await _seed_project(db_session, tenant)

    await _run_svc(db_session).create(
        project_ids=[p0, p1],
        resolved_order=[p0, p1],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
        current_index=0,
    )

    # p1 is index 1 — NOT the current in-flight member.
    silenced = [(tenant, p1, datetime.now(UTC) - timedelta(minutes=60), 10)]
    await _detector(db_session)._stall_runs_for_silenced_projects(db_session, silenced)

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["status"] != "stalled"


# ---------------------------------------------------------------------------
# 5. a silent solo project (no active run) is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_stall_solo_no_run(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)

    silenced = [(tenant, pid, datetime.now(UTC) - timedelta(minutes=60), 10)]
    # No active run contains pid => the loop finds nothing and never raises.
    await _detector(db_session)._stall_runs_for_silenced_projects(db_session, silenced)
