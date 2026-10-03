# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_ORIGINAL = "Original product name"
_UNCOMMITTED = "Renamed by the caller, never committed"


@pytest_asyncio.fixture
async def seeded_run(db_manager) -> AsyncIterator[dict[str, str]]:
    tenant_key = TenantManager.generate_tenant_key()
    product_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, tenant_key=tenant_key, name=_ORIGINAL))
        session.add(
            Project(
                id=project_id,
                product_id=product_id,
                name="Chain member",
                description="member",
                mission="member",
                status="completed",
                tenant_key=tenant_key,
                series_number=random.randint(1, 9000),
            )
        )
        await session.flush()
        run = await SequenceRunService(session=session).create(
            project_ids=[project_id],
            resolved_order=[project_id],
            execution_mode="claude_code_cli",
            status="running",
            project_statuses={project_id: "completed"},
            tenant_key=tenant_key,
        )
    yield {"tenant_key": tenant_key, "product_id": product_id, "project_id": project_id, "run_id": run["id"]}
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tenant_key))
        await session.execute(delete(AgentJob).where(AgentJob.tenant_key == tenant_key))
        await session.execute(delete(SequenceRun).where(SequenceRun.tenant_key == tenant_key))
        await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))


async def _stage_uncommitted_rename(session: AsyncSession, seeded: dict[str, str]) -> None:
    product = await session.get(Product, seeded["product_id"])
    product.name = _UNCOMMITTED
    await session.flush()


async def _committed_product_name(db_manager, seeded: dict[str, str]) -> str:
    async with db_manager.get_session_async(tenant_key=seeded["tenant_key"]) as session:
        return await session.scalar(select(Product.name).where(Product.id == seeded["product_id"]))


async def test_purge_run_leaves_the_commit_to_the_caller(db_manager, seeded_run) -> None:
    tenant_key = seeded_run["tenant_key"]
    async with AsyncSession(db_manager.async_engine, expire_on_commit=False) as caller:
        with tenant_session_context(caller, tenant_key):
            await _stage_uncommitted_rename(caller, seeded_run)
            await SequenceRunService(session=caller).purge_run(run_id=seeded_run["run_id"], tenant_key=tenant_key)
            await caller.rollback()

    assert await _committed_product_name(db_manager, seeded_run) == _ORIGINAL


async def test_mark_member_reviewed_leaves_the_commit_to_the_caller(db_manager, seeded_run) -> None:
    tenant_key = seeded_run["tenant_key"]
    async with AsyncSession(db_manager.async_engine, expire_on_commit=False) as caller:
        with tenant_session_context(caller, tenant_key):
            await _stage_uncommitted_rename(caller, seeded_run)
            await SequenceRunService(session=caller).mark_member_reviewed(
                run_id=seeded_run["run_id"], project_id=seeded_run["project_id"], tenant_key=tenant_key, via="harness"
            )
            await caller.rollback()

    assert await _committed_product_name(db_manager, seeded_run) == _ORIGINAL
