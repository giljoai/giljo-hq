# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints.projects import router as projects_router
from api.endpoints.projects.dependencies import get_project_service
from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import Product, Project
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


class _User:
    id = "user-fe9763"
    username = "fe9763"

    def __init__(self, tenant_key: str) -> None:
        self.tenant_key = tenant_key


def _app(db_manager, tenant_key: str) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(projects_router)
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)
    service = ProjectService(db_manager=db_manager, tenant_manager=tenant_manager)

    async def _user() -> _User:
        return _User(tenant_key)

    async def _svc() -> AsyncIterator[ProjectService]:
        yield service

    app.dependency_overrides[get_current_active_user] = _user
    app.dependency_overrides[get_project_service] = _svc
    return app


def _project(tenant_key: str, product_id: str, status: str, series: int) -> Project:
    return Project(
        id=str(uuid.uuid4()),
        name=f"FE-9763 {uuid.uuid4().hex[:6]}",
        description="closed without staging",
        mission="",
        status=status,
        tenant_key=tenant_key,
        product_id=product_id,
        series_number=series,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC) if status == "completed" else None,
    )


def _entry(tenant_key: str, product_id: str, project_id: str, seq: int, entry_type: str, summary: str, **kw):
    return ProductMemoryEntry(
        tenant_key=tenant_key,
        product_id=product_id,
        project_id=project_id,
        sequence=seq,
        entry_type=entry_type,
        source="closeout_v1",
        timestamp=datetime.now(UTC),
        summary=summary,
        **kw,
    )


async def _seed(db_manager, tenant_key: str, other_tenant: str) -> dict[str, str]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid.uuid4()),
            name=f"FE-9763 {uuid.uuid4().hex[:6]}",
            description="board source",
            tenant_key=tenant_key,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(product)
        await session.flush()
        done = _project(tenant_key, product.id, "completed", 1)
        bare = _project(tenant_key, product.id, "completed", 2)
        running = _project(tenant_key, product.id, "active", 3)
        session.add_all([done, bare, running])
        await session.flush()
        session.add_all(
            [
                _entry(tenant_key, product.id, done.id, 1, "project_closeout", "Older closeout."),
                _entry(tenant_key, product.id, done.id, 2, "project_completion", "Latest closeout."),
                _entry(tenant_key, product.id, done.id, 3, "decision", "A decision, not a closeout."),
                _entry(
                    tenant_key, product.id, done.id, 4, "project_closeout", "Deleted closeout.", deleted_by_user=True
                ),
                _entry(other_tenant, product.id, done.id, 5, "project_closeout", "Another tenant's closeout."),
                _entry(tenant_key, product.id, running.id, 6, "project_closeout", "A running project's note."),
            ]
        )
        await session.commit()
        return {"product": product.id, "done": done.id, "bare": bare.id, "running": running.id}


@pytest.mark.parametrize("mode", ["ce", "saas"])
async def test_board_read_carries_latest_closeout_summary(db_manager, monkeypatch, mode):
    monkeypatch.setenv("GILJO_MODE", mode)
    tenant_key = TenantManager.generate_tenant_key()
    other_tenant = TenantManager.generate_tenant_key()
    ids = await _seed(db_manager, tenant_key, other_tenant)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=_app(db_manager, tenant_key)), base_url="http://t"
        ) as client:
            resp = await client.get(
                "/api/v1/projects/active", params={"product_id": ids["product"], "include_unreviewed": "true"}
            )
            assert resp.status_code == 200, resp.text
            rows = {row["id"]: row for row in resp.json()}

        assert rows[ids["done"]]["closeout_summary"] == "Latest closeout."
        assert rows[ids["bare"]]["closeout_summary"] is None, "no closeout entry: no summary"
        assert rows[ids["running"]]["closeout_summary"] is None, "only a completed project carries one"
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
        await purge_tenant_rows(db_manager, other_tenant)
