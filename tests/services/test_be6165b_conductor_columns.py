# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        await session.commit()


def _service(session: AsyncSession) -> SequenceRunService:
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




async def test_conductor_fields_round_trip(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant)
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

    fetched = await svc.get(run_id=created["id"], tenant_key=tenant)
    assert fetched["conductor_agent_id"] == agent_id
    assert fetched["conductor_project_id"] == project_id
    assert fetched["conductor_label"] == "head-of-order conductor"




async def test_execution_mode_and_resolved_order_mutable(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant)
    pa, pb = created["resolved_order"]

    updated = await svc.update(
        run_id=created["id"],
        tenant_key=tenant,
        execution_mode="multi_terminal",
        resolved_order=[pb, pa],
    )
    assert updated["execution_mode"] == "multi_terminal"
    assert updated["resolved_order"] == [pb, pa]

    with pytest.raises(ValidationError):
        await svc.update(
            run_id=created["id"],
            tenant_key=tenant,
            execution_mode="not_a_real_mode",
        )




async def test_project_ids_immutable(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant)
    original = list(created["project_ids"])

    with pytest.raises(TypeError):
        await svc.update(
            run_id=created["id"],
            tenant_key=tenant,
            project_ids=[str(uuid.uuid4())],  # type: ignore[call-arg]
        )

    fetched = await svc.get(run_id=created["id"], tenant_key=tenant)
    assert fetched["project_ids"] == original




async def test_new_lifecycle_statuses_round_trip(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant)
    pa = created["resolved_order"][0]

    for run_status in ("terminated", "cancelled"):
        updated = await svc.update(run_id=created["id"], tenant_key=tenant, status=run_status)
        assert updated["status"] == run_status

    updated = await svc.update(
        run_id=created["id"],
        tenant_key=tenant,
        project_statuses={pa: "terminated"},
    )
    assert updated["project_statuses"][pa] == "terminated"

    with pytest.raises(ValidationError):
        await svc.update(run_id=created["id"], tenant_key=tenant, status="released")




async def test_update_tenant_isolation(db_session: AsyncSession) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    svc = _service(db_session)

    created = await _create_run(svc, tenant_a)
    minted_conductor = created["conductor_agent_id"]

    with pytest.raises(ResourceNotFoundError):
        await svc.update(
            run_id=created["id"],
            tenant_key=tenant_b,
            conductor_agent_id=str(uuid.uuid4()),
        )

    fetched = await svc.get(run_id=created["id"], tenant_key=tenant_a)
    assert fetched["conductor_agent_id"] == minted_conductor
