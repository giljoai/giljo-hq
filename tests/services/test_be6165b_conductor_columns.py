# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6165b — SequenceRun conductor-identity columns + lifecycle enum extension.

Regression at the failing layer = the SequenceRunService write boundary. The
ChainDirectiveComposer reads conductor_agent_id / conductor_project_id /
conductor_label off the run; those columns + the PATCH path that writes them did
not exist, so the composer was permanently dormant. These tests pin:

1. ``test_conductor_fields_round_trip``: create (BE-6184 mints a conductor_agent_id;
   conductor_project_id/label stay NULL), then PATCH conductor_* and GET them back.
2. ``test_execution_mode_and_resolved_order_mutable`` — both are now PATCHable
   (cockpit sets mode at staging + reorders pre-Stage); an invalid execution_mode
   on PATCH still raises ValidationError (-> 422), not a 500.
3. ``test_project_ids_immutable`` — update() exposes no project_ids param, so the
   election can never be mutated post-create.
4. ``test_new_lifecycle_statuses_round_trip`` — the 3 new enum values
   (run: terminated/cancelled; per-project: terminated) validate + persist.
5. ``test_update_tenant_isolation`` — a PATCH under the wrong tenant raises
   ResourceNotFoundError (-> 404), never a cross-tenant write.

Parallel-safety: DB-touching, runs inside the ``db_session`` fixture
(TransactionalTestContext — rollback at teardown). No module-level mutable state;
each test owns its setup.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


_EXECUTION_MODE = "claude_code_cli"


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    """Delete sequence_runs after each test (parallel-safety hardening).

    SequenceRunService.create/update COMMIT through the injected session (the
    established service pattern — RoadmapService does the same), which escapes the
    TransactionalTestContext rollback, so rows persist in this worker's DB. Each
    pytest-xdist worker owns its own DB and runs its tests serially, so a
    full-table delete here is isolated and keeps committed rows from accumulating
    across tests (which is what surfaced as flakiness under -n6).
    """
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        await session.commit()


def _service(session: AsyncSession) -> SequenceRunService:
    """SequenceRunService bound to the injected (rolled-back) test session."""
    return SequenceRunService(db_manager=None, tenant_manager=None, session=session)


async def _create_run(svc: SequenceRunService, tenant_key: str) -> dict:
    pa, pb = str(uuid.uuid4()), str(uuid.uuid4())
    return await svc.create(
        project_ids=[pa, pb],
        resolved_order=[pa, pb],
        execution_mode=_EXECUTION_MODE,
        status="pending",
        project_statuses={pa: "pending", pb: "pending"},
        tenant_key=tenant_key,
    )


# ---------------------------------------------------------------------------
# 1. conductor fields default NULL, then round-trip through PATCH
# ---------------------------------------------------------------------------


async def test_conductor_fields_round_trip(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant)
    # BE-6184: create() mints the dedicated conductor -> conductor_agent_id is set;
    # conductor_project_id / conductor_label stay NULL (the conductor owns no project).
    assert created["conductor_agent_id"] is not None
    assert created["conductor_project_id"] is None
    assert created["conductor_label"] is None

    agent_id = str(uuid.uuid4())
    project_id = created["resolved_order"][0]
    updated = await svc.update(
        run_id=created["id"],
        tenant_key=tenant,
        conductor_agent_id=agent_id,
        conductor_project_id=project_id,
        conductor_label="head-of-order conductor",
    )
    assert updated["conductor_agent_id"] == agent_id
    assert updated["conductor_project_id"] == project_id
    assert updated["conductor_label"] == "head-of-order conductor"

    # GET re-reads the persisted identity (the composer's read path).
    fetched = await svc.get(run_id=created["id"], tenant_key=tenant)
    assert fetched["conductor_agent_id"] == agent_id
    assert fetched["conductor_project_id"] == project_id
    assert fetched["conductor_label"] == "head-of-order conductor"


# ---------------------------------------------------------------------------
# 2. execution_mode + resolved_order are mutable (were immutable post-create)
# ---------------------------------------------------------------------------


async def test_execution_mode_and_resolved_order_mutable(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant)
    pa, pb = created["resolved_order"]

    updated = await svc.update(
        run_id=created["id"],
        tenant_key=tenant,
        execution_mode="multi_terminal",
        resolved_order=[pb, pa],  # cockpit drag-reorder pre-Stage
    )
    assert updated["execution_mode"] == "multi_terminal"
    assert updated["resolved_order"] == [pb, pa]

    # Invalid execution_mode on PATCH is a 422, not a DB-constraint 500.
    with pytest.raises(ValidationError):
        await svc.update(
            run_id=created["id"],
            tenant_key=tenant,
            execution_mode="not_a_real_mode",
        )


# ---------------------------------------------------------------------------
# 3. project_ids stays immutable (no update param exists for it)
# ---------------------------------------------------------------------------


async def test_project_ids_immutable(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant)
    original = list(created["project_ids"])

    # update() has no project_ids parameter; a stray kwarg must be rejected.
    with pytest.raises(TypeError):
        await svc.update(
            run_id=created["id"],
            tenant_key=tenant,
            project_ids=[str(uuid.uuid4())],  # type: ignore[call-arg]
        )

    fetched = await svc.get(run_id=created["id"], tenant_key=tenant)
    assert fetched["project_ids"] == original


# ---------------------------------------------------------------------------
# 4. the 3 new lifecycle statuses validate + persist
# ---------------------------------------------------------------------------


async def test_new_lifecycle_statuses_round_trip(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant)
    pa = created["resolved_order"][0]

    # run-level: terminated (graceful) + cancelled (hard reset).
    for run_status in ("terminated", "cancelled"):
        updated = await svc.update(run_id=created["id"], tenant_key=tenant, status=run_status)
        assert updated["status"] == run_status

    # per-project: terminated (the in-flight project at a graceful terminate).
    updated = await svc.update(
        run_id=created["id"],
        tenant_key=tenant,
        project_statuses={pa: "terminated"},
    )
    assert updated["project_statuses"][pa] == "terminated"

    # A value outside the extended set is still rejected (422, not 500).
    with pytest.raises(ValidationError):
        await svc.update(run_id=created["id"], tenant_key=tenant, status="released")


# ---------------------------------------------------------------------------
# 5. tenant isolation on the write boundary
# ---------------------------------------------------------------------------


async def test_update_tenant_isolation(db_session: AsyncSession) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant_a)
    minted_conductor = created["conductor_agent_id"]  # BE-6184: stamped at create

    # Tenant B must not be able to PATCH tenant A's run.
    with pytest.raises(ResourceNotFoundError):
        await svc.update(
            run_id=created["id"],
            tenant_key=tenant_b,
            conductor_agent_id=str(uuid.uuid4()),
        )

    # Tenant A's run is unchanged (no cross-tenant write leaked through).
    fetched = await svc.get(run_id=created["id"], tenant_key=tenant_a)
    assert fetched["conductor_agent_id"] == minted_conductor
