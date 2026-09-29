# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool returned no content")


@pytest_asyncio.fixture
async def seeded(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    product_id = str(uuid.uuid4())
    revived_id = str(uuid.uuid4())
    trashed_id = str(uuid.uuid4())
    tag = uuid.uuid4().hex[:8]
    deleted_at = datetime.now(UTC) - timedelta(days=2)

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, name=f"FE9651 product {tag}", tenant_key=tenant_key, is_active=True))
        await session.flush()
        session.add(
            Project(
                id=revived_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name=f"Revived move {tag}",
                description="d",
                mission="m",
                status=ProjectStatus.ACTIVE,
                series_number=1,
                deleted_at=deleted_at,
                completed_at=deleted_at,
                implementation_launched_at=deleted_at,
            )
        )
        session.add(
            Project(
                id=trashed_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name=f"Trashed card {tag}",
                description="d",
                mission="m",
                status=ProjectStatus.DELETED,
                series_number=2,
                deleted_at=deleted_at,
            )
        )
        await session.flush()
        for job_type in ("orchestrator", "implementer", "tester"):
            job = AgentJob(
                job_id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                project_id=revived_id,
                job_type=job_type,
                mission="x",
                status="active",
                created_at=deleted_at,
            )
            session.add(job)
            await session.flush()
            session.add(
                AgentExecution(
                    id=str(uuid.uuid4()),
                    agent_id=str(uuid.uuid4()),
                    job_id=job.job_id,
                    tenant_key=tenant_key,
                    agent_display_name=job_type,
                    status="decommissioned",
                    started_at=deleted_at,
                    completed_at=deleted_at,
                )
            )
        await session.commit()

    try:
        yield {
            "tenant_key": tenant_key,
            "product_id": product_id,
            "revived_id": revived_id,
            "trashed_id": trashed_id,
            "tag": tag,
        }
    finally:
        async with db_manager.get_session_async(tenant_key=tenant_key) as cleanup:
            job_ids = [
                j
                for (j,) in (
                    await cleanup.execute(
                        AgentJob.__table__.select()
                        .with_only_columns(AgentJob.job_id)
                        .where(AgentJob.tenant_key == tenant_key)
                    )
                ).all()
            ]
            if job_ids:
                await cleanup.execute(delete(AgentExecution).where(AgentExecution.job_id.in_(job_ids)))
                await cleanup.execute(delete(AgentJob).where(AgentJob.job_id.in_(job_ids)))
            await cleanup.execute(delete(Project).where(Project.tenant_key == tenant_key))
            await cleanup.execute(delete(Product).where(Product.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _list(args: dict) -> set[str]:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("list_projects", args)
    assert result.is_error is False, result
    return {p["project_id"] for p in _payload(result)["projects"]}


async def test_list_projects_finds_revived_project_by_status(seeded):
    ids = await _list({"product_id": seeded["product_id"], "status": "active"})
    assert seeded["revived_id"] in ids
    assert seeded["trashed_id"] not in ids


async def test_list_projects_finds_revived_project_by_query(seeded):
    ids = await _list({"product_id": seeded["product_id"], "query": f"Revived move {seeded['tag']}"})
    assert ids == {seeded["revived_id"]}


async def test_list_projects_default_view_lists_revived_but_not_trashed(seeded):
    ids = await _list({"product_id": seeded["product_id"]})
    assert seeded["revived_id"] in ids
    assert seeded["trashed_id"] not in ids


async def test_trash_filter_still_reaches_only_the_trashed_project(seeded):
    ids = await _list({"product_id": seeded["product_id"], "status": "deleted"})
    assert ids == {seeded["trashed_id"]}


async def test_dashboard_active_read_agrees_with_the_agent_door(db_manager, seeded):
    from giljo_mcp.services.project_service import ProjectService

    TenantManager.set_current_tenant(seeded["tenant_key"])
    service = ProjectService(db_manager=db_manager, tenant_manager=TenantManager())
    rest_ids = {p.id for p in await service.query.get_active_projects(product_id=seeded["product_id"])}
    mcp_ids = await _list({"product_id": seeded["product_id"], "status": "active"})
    assert rest_ids == mcp_ids == {seeded["revived_id"]}
