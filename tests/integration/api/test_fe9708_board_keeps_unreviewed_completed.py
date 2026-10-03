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

from api.endpoints.projects import router as projects_router
from api.endpoints.projects.dependencies import get_project_service
from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import Product, Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


class _User:
    id = "user-fe9708"
    username = "fe9708"

    def __init__(self, tenant_key: str) -> None:
        self.tenant_key = tenant_key


def _service(db_manager, tenant_key: str) -> ProjectService:
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)
    return ProjectService(db_manager=db_manager, tenant_manager=tenant_manager)


def _app(db_manager, tenant_key: str) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(projects_router)
    service = _service(db_manager, tenant_key)

    async def _user() -> _User:
        return _User(tenant_key)

    async def _svc() -> AsyncIterator[ProjectService]:
        yield service

    app.dependency_overrides[get_current_active_user] = _user
    app.dependency_overrides[get_project_service] = _svc
    return app


async def _seed(db_manager, tenant_key: str) -> tuple[str, str]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid.uuid4()),
            name=f"FE-9708 {uuid.uuid4().hex[:6]}",
            description="board source",
            tenant_key=tenant_key,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(product)
        await session.flush()
        project = Project(
            id=str(uuid.uuid4()),
            name=f"FE-9708 {uuid.uuid4().hex[:6]}",
            description="finished by its agent",
            mission="m",
            status="active",
            tenant_key=tenant_key,
            product_id=product.id,
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
        )
        session.add(project)
        await session.commit()
        return product.id, project.id


@pytest_asyncio.fixture
async def agent_completed_project(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    product_id, project_id = await _seed(db_manager, tenant_key)
    result = await _service(db_manager, tenant_key).update_project_metadata_for_mcp(
        project_id=project_id, status="completed", tenant_key=tenant_key, force=True
    )
    assert result["success"] is True
    try:
        yield tenant_key, product_id, project_id
    finally:
        await purge_tenant_rows(db_manager, tenant_key)


async def _board_ids(client: AsyncClient, product_id: str) -> dict[str, dict]:
    resp = await client.get("/api/v1/projects/active", params={"product_id": product_id, "include_unreviewed": "true"})
    assert resp.status_code == 200, resp.text
    return {row["id"]: row for row in resp.json()}


async def test_agent_completed_project_stays_on_board_until_human_review(db_manager, agent_completed_project):
    tenant_key, product_id, project_id = agent_completed_project
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant_key)), base_url="http://t") as client:
        rows = await _board_ids(client, product_id)
        assert project_id in rows, "an agent-completed, unreviewed project must stay on the board"
        assert rows[project_id]["status"] == "completed"
        assert rows[project_id]["reviewed_at"] is None
        assert rows[project_id]["review_pending"] is True

        plain = await client.get("/api/v1/projects/active", params={"product_id": product_id})
        assert project_id not in {r["id"] for r in plain.json()}, "the default read stays active-only"

        stamped = await client.post(f"/api/v1/projects/{project_id}/reviewed")
        assert stamped.status_code == 200, stamped.text
        first = stamped.json()["reviewed_at"]
        assert first is not None
        assert project_id not in await _board_ids(client, product_id)

        again = await client.post(f"/api/v1/projects/{project_id}/reviewed")
        assert again.json()["reviewed_at"] == first, "a second press keeps the first stamp"


async def test_unreviewed_completed_project_is_tenant_scoped(db_manager, agent_completed_project):
    _, product_id, project_id = agent_completed_project
    other = TenantManager.generate_tenant_key()
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, other)), base_url="http://t") as client:
        assert project_id not in await _board_ids(client, product_id)
        denied = await client.post(f"/api/v1/projects/{project_id}/reviewed")
        assert denied.status_code == 404


async def test_review_stamp_refused_on_a_project_still_running(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    _, project_id = await _seed(db_manager, tenant_key)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=_app(db_manager, tenant_key)), base_url="http://t"
        ) as client:
            resp = await client.post(f"/api/v1/projects/{project_id}/reviewed")
            assert resp.status_code == 409, resp.text
    finally:
        await purge_tenant_rows(db_manager, tenant_key)


async def test_single_project_read_reports_the_review_stamp(db_manager, agent_completed_project):
    tenant_key, _, project_id = agent_completed_project
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant_key)), base_url="http://t") as client:
        pending = await client.get(f"/api/v1/projects/{project_id}")
        assert pending.status_code == 200, pending.text
        assert pending.json()["reviewed_at"] is None
        assert pending.json()["review_pending"] is True

        stamped = await client.post(f"/api/v1/projects/{project_id}/reviewed")
        assert stamped.status_code == 200, stamped.text

        reviewed = (await client.get(f"/api/v1/projects/{project_id}")).json()
        assert reviewed["reviewed_at"] is not None
        assert reviewed["review_pending"] is False
