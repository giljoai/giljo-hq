# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints.projects import router as projects_router
from api.endpoints.projects.dependencies import get_project_service
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.schemas.service_responses import ActiveProjectDetail


pytestmark = pytest.mark.asyncio

_TENANT = "tenant-active-impl-ts-test"


class _FakeUser:

    id = "user-active-test"
    username = "active_tester"
    tenant_key = _TENANT


class _FakeQuery:

    def __init__(self, detail: ActiveProjectDetail | None) -> None:
        self._detail = detail
        self.last_product_id: str | None = "UNCALLED"

    async def get_active_projects(self, product_id: str | None = None) -> list[ActiveProjectDetail]:
        self.last_product_id = product_id
        return [self._detail] if self._detail is not None else []


class _StubProjectService:
    def __init__(self, detail: ActiveProjectDetail | None) -> None:
        self.query = _FakeQuery(detail)


def _build_app(stub: _StubProjectService) -> FastAPI:
    app = FastAPI()
    app.include_router(projects_router)

    async def _override_user() -> _FakeUser:
        return _FakeUser()

    async def _override_service() -> AsyncIterator[_StubProjectService]:
        yield stub

    app.dependency_overrides[get_current_active_user] = _override_user
    app.dependency_overrides[get_project_service] = _override_service
    return app


def _active_detail(launch_ts: datetime | None) -> ActiveProjectDetail:
    return ActiveProjectDetail(
        id="proj-active-impl",
        alias="ACT",
        name="Active Impl-TS Project",
        mission="exercise GET /active serialization",
        description="seeded for active-impl-ts regression",
        status="active",
        product_id="prod-active",
        created_at="2026-06-10T00:00:00+00:00",
        updated_at="2026-06-10T01:00:00+00:00",
        completed_at=None,
        implementation_launched_at=(launch_ts.isoformat() if launch_ts else None),
        deleted_at=None,
        agent_count=0,
        message_count=0,
    )


async def test_active_endpoint_includes_implementation_launched_at_when_set():
    launch_ts = datetime(2026, 6, 10, 3, 29, 18, tzinfo=UTC)
    app = _build_app(_StubProjectService(_active_detail(launch_ts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/active")

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert isinstance(body, list) and len(body) == 1
    assert "implementation_launched_at" in body[0], (
        "GET /active dropped implementation_launched_at — the ActiveProjectDetail "
        "schema regressed. Check schemas/responses/project.py::ActiveProjectDetail "
        "and services/project_query_service.py construction site."
    )
    assert body[0]["implementation_launched_at"] is not None
    assert datetime.fromisoformat(body[0]["implementation_launched_at"]) == launch_ts


async def test_active_endpoint_keeps_implementation_launched_at_when_null():
    app = _build_app(_StubProjectService(_active_detail(None)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/active")

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert isinstance(body, list) and len(body) == 1
    assert "implementation_launched_at" in body[0]
    assert body[0]["implementation_launched_at"] is None


async def test_active_endpoint_returns_empty_list_when_no_active_project():
    app = _build_app(_StubProjectService(None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/active")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_active_endpoint_forwards_product_id_query_param():
    stub = _StubProjectService(None)
    app = _build_app(stub)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/active", params={"product_id": "prod-b"})

    assert resp.status_code == 200
    assert stub.query.last_product_id == "prod-b"


async def test_active_endpoint_omits_product_id_when_not_given():
    stub = _StubProjectService(None)
    app = _build_app(stub)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/active")

    assert resp.status_code == 200
    assert stub.query.last_product_id is None


async def test_active_endpoint_serializes_staging_status_and_execution_mode():
    base = _active_detail(None).model_dump()
    detail = ActiveProjectDetail(**{**base, "staging_status": "staging_complete", "execution_mode": "subagent"})
    app = _build_app(_StubProjectService(detail))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/active")

    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["staging_status"] == "staging_complete"
    assert body["execution_mode"] == "subagent"
