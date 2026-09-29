# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from api.endpoints.projects import router as projects_router
from api.endpoints.projects.dependencies import get_project_service
from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

REASON = "The agents stopped without writing a closeout; closing from the dashboard."


async def _seed(db_manager, tenant_key: str, agent_status: str) -> dict:
    product_id, project_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, name="FE9651 close product", tenant_key=tenant_key, is_active=True))
        await session.flush()
        session.add(
            Project(
                id=project_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name="Stopped project",
                description="d",
                mission="m",
                status=ProjectStatus.ACTIVE,
                series_number=1,
                implementation_launched_at=datetime.now(UTC),
            )
        )
        await session.flush()
        for job_type in ("orchestrator", "implementer"):
            job = AgentJob(
                job_id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                project_id=project_id,
                job_type=job_type,
                mission="x",
                status="active",
                created_at=datetime.now(UTC),
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
                    status="decommissioned" if job_type == "orchestrator" else agent_status,
                    started_at=datetime.now(UTC),
                )
            )
        await session.commit()
    return {"product_id": product_id, "project_id": project_id}


@pytest_asyncio.fixture
async def http(db_manager) -> AsyncIterator[tuple[AsyncClient, str]]:
    tenant_key = TenantManager.generate_tenant_key()

    class _User:
        id = "user-fe9651"
        username = "fe9651"

    _User.tenant_key = tenant_key

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(projects_router)

    async def _override_user():
        return _User()

    async def _override_service():
        TenantManager.set_current_tenant(tenant_key)
        yield ProjectService(db_manager=db_manager, tenant_manager=TenantManager())

    app.dependency_overrides[get_current_active_user] = _override_user
    app.dependency_overrides[get_project_service] = _override_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, tenant_key

    async with db_manager.get_session_async(tenant_key=tenant_key) as cleanup:
        job_ids = list(
            (await cleanup.execute(select(AgentJob.job_id).where(AgentJob.tenant_key == tenant_key))).scalars()
        )
        if job_ids:
            await cleanup.execute(delete(AgentExecution).where(AgentExecution.job_id.in_(job_ids)))
            await cleanup.execute(delete(AgentJob).where(AgentJob.job_id.in_(job_ids)))
        await cleanup.execute(delete(ProductMemoryEntry).where(ProductMemoryEntry.tenant_key == tenant_key))
        await cleanup.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await cleanup.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await cleanup.commit()


async def _closeout_entries(db_manager, tenant_key: str, project_id: str) -> list[ProductMemoryEntry]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        rows = await session.execute(
            select(ProductMemoryEntry).where(
                ProductMemoryEntry.tenant_key == tenant_key, ProductMemoryEntry.project_id == project_id
            )
        )
        return list(rows.scalars())


async def _project_status(db_manager, tenant_key: str, project_id: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        project = (
            await session.execute(select(Project).where(Project.tenant_key == tenant_key, Project.id == project_id))
        ).scalar_one()
        return project.status.value if hasattr(project.status, "value") else project.status


async def test_close_without_summary_writes_closeout_then_archive_completes(db_manager, http):
    client, tenant_key = http
    seeded = await _seed(db_manager, tenant_key, agent_status="decommissioned")
    project_id = seeded["project_id"]

    resp = await client.post(f"/api/v1/projects/{project_id}/closeout-without-summary", json={"reason": REASON})
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    entries = await _closeout_entries(db_manager, tenant_key, project_id)
    assert len(entries) == 1
    assert REASON in (entries[0].summary or "")
    assert await _project_status(db_manager, tenant_key, project_id) == "active"

    archived = await client.post(f"/api/v1/projects/{project_id}/archive")
    assert archived.status_code == 200, archived.text
    assert await _project_status(db_manager, tenant_key, project_id) == "completed"


async def test_close_without_summary_is_refused_while_an_agent_is_working(db_manager, http):
    client, tenant_key = http
    seeded = await _seed(db_manager, tenant_key, agent_status="working")
    project_id = seeded["project_id"]

    resp = await client.post(f"/api/v1/projects/{project_id}/closeout-without-summary", json={"reason": REASON})
    assert resp.status_code == 409, resp.text
    assert await _closeout_entries(db_manager, tenant_key, project_id) == []
    assert await _project_status(db_manager, tenant_key, project_id) == "active"


async def test_close_without_summary_requires_a_reason(db_manager, http):
    client, tenant_key = http
    seeded = await _seed(db_manager, tenant_key, agent_status="decommissioned")
    resp = await client.post(f"/api/v1/projects/{seeded['project_id']}/closeout-without-summary", json={"reason": ""})
    assert resp.status_code == 422
