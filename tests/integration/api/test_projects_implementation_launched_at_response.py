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
from giljo_mcp.schemas.service_responses import ProjectDetail


pytestmark = pytest.mark.asyncio


_FAKE_USER_TENANT = "tenant-ce0037-test"


class _FakeUser:

    id = "user-ce0037-test"
    username = "ce0037_tester"
    tenant_key = _FAKE_USER_TENANT


class _StubProjectService:

    def __init__(self, project_detail: ProjectDetail) -> None:
        self._project_detail = project_detail

    async def get_project(self, project_id: str, tenant_key: str) -> ProjectDetail:
        return self._project_detail


def _build_app(stub_service: _StubProjectService) -> FastAPI:
    app = FastAPI()
    app.include_router(projects_router)

    async def _override_user() -> _FakeUser:
        return _FakeUser()

    async def _override_service() -> AsyncIterator[_StubProjectService]:
        yield stub_service

    app.dependency_overrides[get_current_active_user] = _override_user
    app.dependency_overrides[get_project_service] = _override_service
    return app


def _detail_with_launch_ts(launch_ts: datetime | None) -> ProjectDetail:
    return ProjectDetail(
        id="proj-ce0037",
        alias="CE37",
        name="CE-0037 Regression Project",
        mission="exercise the API serialization layer",
        description="seeded for CE-0037 integration test",
        status="active",
        staging_status="staging_complete",
        implementation_launched_at=(launch_ts.isoformat() if launch_ts else None),
        product_id="prod-ce0037",
        tenant_key=_FAKE_USER_TENANT,
        execution_mode="multi_terminal",
        auto_checkin_enabled=False,
        auto_checkin_interval=10,
        created_at="2026-05-18T00:00:00+00:00",
        updated_at="2026-05-18T01:00:00+00:00",
        agents=[],
        agent_count=0,
        message_count=0,
    )


async def test_get_project_response_includes_implementation_launched_at_when_set():
    launch_ts = datetime(2026, 5, 18, 3, 29, 18, tzinfo=UTC)
    detail = _detail_with_launch_ts(launch_ts)
    app = _build_app(_StubProjectService(detail))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/projects/{detail.id}")

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "implementation_launched_at" in body, (
        "REST ProjectResponse JSON is missing implementation_launched_at — the CE-0036 bug regressed. "
        "Check api/endpoints/projects/models.py::ProjectResponse and crud.py::get_project construction site."
    )
    assert body["implementation_launched_at"] is not None
    assert datetime.fromisoformat(body["implementation_launched_at"]) == launch_ts


async def test_get_project_response_keeps_implementation_launched_at_when_null():
    detail = _detail_with_launch_ts(None)
    app = _build_app(_StubProjectService(detail))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/projects/{detail.id}")

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "implementation_launched_at" in body, (
        "REST ProjectResponse JSON dropped implementation_launched_at when value is null — "
        "frontend gate relies on property presence, not just truthiness."
    )
    assert body["implementation_launched_at"] is None
