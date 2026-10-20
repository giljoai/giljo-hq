# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(session, reason="test teardown: wipe sequence_runs", models=(SequenceRun,)):
            await session.execute(delete(SequenceRun))
        await session.commit()


def _svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=None, session=session)


async def _project(session: AsyncSession, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()), tenant_key=tenant_key, name=f"P {uuid.uuid4().hex[:6]}", description="x", is_active=False
    )
    session.add(product)
    pid = str(uuid.uuid4())
    session.add(
        Project(
            id=pid,
            name="BE-9813 member",
            description="x",
            mission="x",
            status="active",
            tenant_key=tenant_key,
            product_id=product.id,
            execution_mode="subagent",
            series_number=random.randint(1, 9000),
        )
    )
    await session.commit()
    return pid


async def _listed(session: AsyncSession, tenant_key: str, run_id: str) -> dict:
    runs = await _svc(session).list_active(tenant_key=tenant_key)
    return next(r for r in runs if r["id"] == run_id)


async def test_listed_run_reports_its_conductors_status(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _project(db_session, tenant)
    run = await _svc(db_session).create(
        project_ids=[pid], resolved_order=[pid], execution_mode="subagent", status="running", tenant_key=tenant
    )
    assert run["conductor_agent_id"]

    assert (await _listed(db_session, tenant, run["id"]))["conductor_status"] == "waiting"

    await db_session.execute(
        update(AgentExecution)
        .where(AgentExecution.tenant_key == tenant, AgentExecution.agent_id == run["conductor_agent_id"])
        .values(status="working")
    )
    await db_session.commit()

    assert (await _listed(db_session, tenant, run["id"]))["conductor_status"] == "working"


async def test_run_without_a_conductor_execution_reports_none(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _project(db_session, tenant)
    run = await _svc(db_session).create(
        project_ids=[pid], resolved_order=[pid], execution_mode="subagent", status="running", tenant_key=tenant
    )
    await db_session.execute(
        delete(AgentExecution).where(
            AgentExecution.tenant_key == tenant, AgentExecution.agent_id == run["conductor_agent_id"]
        )
    )
    await db_session.commit()

    assert (await _listed(db_session, tenant, run["id"]))["conductor_status"] is None
