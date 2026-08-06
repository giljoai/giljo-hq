# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6185 — chain-mission storage on sequence_runs (service layer).

Regression at the failing layer (SequenceRunService), the owning service for the
``chain_mission`` column. Exercised on a real DB via the injected session,
tenant-scoped, parallel-safe (no module-level mutable state, no ordering deps).

Covers the BE-6185 deliverables:
  1. update(chain_mission=...) round-trips through get() + the serializer.
  2. An over-cap chain_mission raises ValidationError (-> 422), never a 500.
  3. A chain_mission write on an ultralocked run is REFUSED (read-only after
     Implement); the project-mission read-only path is independent.
  4. Solo / NULL: a run with chain_mission unset serializes with None.

The ``_wipe_sequence_runs`` autouse teardown mirrors test_fe6171_chain_lock_
foundation.py: the service COMMITs through the injected session (escaping
rollback), so the table is wiped after each test (per-worker DB, serial -> safe).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import MAX_CHAIN_MISSION_CHARS, SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_MODE = "claude_code_cli"


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        await session.commit()


def _svc(session: AsyncSession, tenant_key: str | None = None) -> SequenceRunService:
    tm = TenantManager()
    if tenant_key:
        tm.set_current_tenant(tenant_key)
    return SequenceRunService(db_manager=None, tenant_manager=tm, session=session)


async def _create(svc: SequenceRunService, tenant: str, *, project_ids: list[str] | None = None, **kw) -> dict:
    pids = project_ids or [str(uuid.uuid4()), str(uuid.uuid4())]
    return await svc.create(
        project_ids=pids,
        resolved_order=list(pids),
        execution_mode=_MODE,
        project_statuses=dict.fromkeys(pids, "pending"),
        tenant_key=tenant,
        **kw,
    )


async def _make_project(session: AsyncSession, tenant: str, *, staging_status: str | None = None) -> str:
    """Create a real product + project row; optionally mark it staging_complete."""
    product = Product(
        id=str(uuid.uuid4()),
        name="Chain Product",
        description="desc",
        tenant_key=tenant,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name="Chain Project",
        description="human requirements",
        mission="mission",
        tenant_key=tenant,
        product_id=product.id,
        status=ProjectStatus.INACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    if staging_status is not None:
        project.staging_status = staging_status
    session.add(project)
    await session.flush()
    return project.id


# ---------------------------------------------------------------------------
# 1 — round-trip through update -> get + serializer
# ---------------------------------------------------------------------------


async def test_update_chain_mission_round_trips(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant)

    mission = "Build A, then wire A into B, then run the B->C migration."
    updated = await svc.update(run_id=run["id"], tenant_key=tenant, chain_mission=mission)
    assert updated["chain_mission"] == mission, "update() must persist chain_mission"

    fetched = await svc.get(run_id=run["id"], tenant_key=tenant)
    assert fetched["chain_mission"] == mission, "get() must read back the stored chain_mission"


async def test_update_chain_mission_is_non_none_gated(db_session: AsyncSession) -> None:
    """An update that omits chain_mission must NOT clobber a previously-set value."""
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant)

    await svc.update(run_id=run["id"], tenant_key=tenant, chain_mission="first plan")
    # A later update that touches only current_index leaves chain_mission intact.
    after = await svc.update(run_id=run["id"], tenant_key=tenant, current_index=1)
    assert after["chain_mission"] == "first plan", "non-None-gated: omitting the field preserves it"


# ---------------------------------------------------------------------------
# 2 — over-cap raises ValidationError (422), not a 500
# ---------------------------------------------------------------------------


async def test_over_cap_chain_mission_raises_validation_error(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant)

    oversized = "x" * (MAX_CHAIN_MISSION_CHARS + 1)
    with pytest.raises(ValidationError):
        await svc.update(run_id=run["id"], tenant_key=tenant, chain_mission=oversized)


async def test_at_cap_chain_mission_is_accepted(db_session: AsyncSession) -> None:
    """Exactly at the cap is allowed (boundary is inclusive)."""
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant)

    at_cap = "y" * MAX_CHAIN_MISSION_CHARS
    updated = await svc.update(run_id=run["id"], tenant_key=tenant, chain_mission=at_cap)
    assert len(updated["chain_mission"]) == MAX_CHAIN_MISSION_CHARS


# ---------------------------------------------------------------------------
# 3 — ultralocked run refuses the chain_mission write (read-only after Implement)
# ---------------------------------------------------------------------------


async def test_chain_mission_write_refused_when_running(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    # status=running -> ultralocked tier (implementation in flight).
    run = await _create(svc, tenant, status="running")
    with pytest.raises(ValidationError):
        await svc.update(run_id=run["id"], tenant_key=tenant, chain_mission="too late")


async def test_chain_mission_write_refused_when_member_staging_complete(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    staged_member = await _make_project(db_session, tenant, staging_status="staging_complete")
    other = str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[staged_member, other])

    with pytest.raises(ValidationError):
        await svc.update(run_id=run["id"], tenant_key=tenant, chain_mission="frozen at implement")


async def test_chain_mission_editable_before_implement(db_session: AsyncSession) -> None:
    """Control: a pending run with no staging-complete member (and even after Stage,
    locked=True) still accepts a chain_mission edit — read-only only kicks in at the
    ultralock (Implement) tier, not the bare Stage flag."""
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant)

    # Stage the run (locked=True) — still pre-Implement, mission stays editable.
    await svc.update(run_id=run["id"], tenant_key=tenant, locked=True)
    updated = await svc.update(run_id=run["id"], tenant_key=tenant, chain_mission="staged-tier edit")
    assert updated["chain_mission"] == "staged-tier edit"
    assert updated["locked"] is True


async def test_project_mission_independent_of_chain_mission(db_session: AsyncSession) -> None:
    """The chain_mission lock is on the RUN. A member project's own mission is a
    separate column on a separate table and is not touched by this path."""
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    member = await _make_project(db_session, tenant)
    other = str(uuid.uuid4())
    run = await _create(svc, tenant, project_ids=[member, other])

    await svc.update(run_id=run["id"], tenant_key=tenant, chain_mission="chain plan")

    row = await db_session.execute(select(Project).where(Project.id == member))
    project = row.scalar_one()
    assert project.mission == "mission", "member project's own mission is untouched by the chain_mission write"


# ---------------------------------------------------------------------------
# 4 — solo / NULL default serializes as None
# ---------------------------------------------------------------------------


async def test_unset_chain_mission_serializes_as_none(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _svc(db_session, tenant)
    run = await _create(svc, tenant)
    assert run["chain_mission"] is None, "a fresh run carries chain_mission=None (no solo-path change)"

    fetched = await svc.get(run_id=run["id"], tenant_key=tenant)
    assert fetched["chain_mission"] is None
