# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints.projects import router as projects_router
from api.endpoints.projects.dependencies import get_project_service
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.schemas.responses.project import ProjectData, ProjectDetail


_FAKE_TENANT = "tenant-ce0038-wire"


class _FakeUser:
    id = "user-ce0038-wire"
    username = "ce0038_wire_tester"
    tenant_key = _FAKE_TENANT


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




def _full_detail() -> ProjectDetail:
    return ProjectDetail(
        id="proj-wire-full",
        alias="WF",
        name="Wire-format Full",
        mission="full mission",
        description="every optional field populated",
        status="active",
        staging_status="staging_complete",
        implementation_launched_at="2026-05-18T03:29:18+00:00",
        product_id="prod-wire",
        tenant_key=_FAKE_TENANT,
        execution_mode="multi_terminal",
        auto_checkin_enabled=True,
        auto_checkin_interval=15,
        cancellation_reason=None,
        early_termination=False,
        created_at="2026-05-18T00:00:00+00:00",
        updated_at="2026-05-18T01:00:00+00:00",
        completed_at=None,
        agents=[],
        agent_count=2,
        message_count=7,
        project_type_id="type-be",
        project_type=None,
        series_number=42,
        subseries="a",
        taxonomy_alias="BE-0042a",
        hidden=False,
    )


def _nulled_detail() -> ProjectDetail:
    return ProjectDetail(
        id="proj-wire-nulled",
        alias="WN",
        name="Wire-format Nulled",
        mission=None,
        description=None,
        status="inactive",
        staging_status=None,
        implementation_launched_at=None,
        product_id=None,
        tenant_key=_FAKE_TENANT,
        execution_mode=None,
        auto_checkin_enabled=False,
        auto_checkin_interval=10,
        cancellation_reason=None,
        early_termination=False,
        created_at="2026-05-18T00:00:00+00:00",
        updated_at="2026-05-18T00:00:00+00:00",
        completed_at=None,
        agents=[],
        agent_count=0,
        message_count=0,
        project_type_id=None,
        project_type=None,
        series_number=None,
        subseries=None,
        taxonomy_alias=None,
        hidden=False,
    )


EXPECTED_REST_FULL: dict = {
    "id": "proj-wire-full",
    "alias": "WF",
    "name": "Wire-format Full",
    "description": "every optional field populated",
    "mission": "full mission",
    "status": "active",
    "staging_status": "staging_complete",
    "product_id": "prod-wire",
    "created_at": "2026-05-18T00:00:00Z",
    "updated_at": "2026-05-18T01:00:00Z",
    "completed_at": None,
    "implementation_launched_at": "2026-05-18T03:29:18Z",
    "reviewed_at": None,
    "review_pending": False,
    "agent_count": 2,
    "message_count": 7,
    "agents": [],
    "execution_mode": "multi_terminal",
    "auto_checkin_enabled": True,
    "auto_checkin_interval": 15,
    "project_type_id": "type-be",
    "project_type": None,
    "series_number": 42,
    "subseries": "a",
    "taxonomy_alias": "BE-0042a",
    "hidden": False,
    "successor_project_id": None,
}

EXPECTED_REST_NULLED: dict = {
    "id": "proj-wire-nulled",
    "alias": "WN",
    "name": "Wire-format Nulled",
    "description": None,
    "mission": "",
    "status": "inactive",
    "staging_status": None,
    "product_id": None,
    "created_at": "2026-05-18T00:00:00Z",
    "updated_at": "2026-05-18T00:00:00Z",
    "completed_at": None,
    "implementation_launched_at": None,
    "reviewed_at": None,
    "review_pending": False,
    "agent_count": 0,
    "message_count": 0,
    "agents": [],
    "execution_mode": None,
    "auto_checkin_enabled": False,
    "auto_checkin_interval": 10,
    "project_type_id": None,
    "project_type": None,
    "series_number": None,
    "subseries": None,
    "taxonomy_alias": None,
    "hidden": False,
    "successor_project_id": None,
}


@pytest.mark.asyncio
async def test_rest_get_project_wire_format_full() -> None:
    app = _build_app(_StubProjectService(_full_detail()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/proj-wire-full")
    assert resp.status_code == 200, resp.text
    assert resp.json() == EXPECTED_REST_FULL, (
        "REST wire format drift detected. CE-0038 schema consolidation must "
        "preserve byte-identical output. Inspect the diff."
    )


@pytest.mark.asyncio
async def test_rest_get_project_wire_format_nulled() -> None:
    app = _build_app(_StubProjectService(_nulled_detail()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/proj-wire-nulled")
    assert resp.status_code == 200, resp.text
    assert resp.json() == EXPECTED_REST_NULLED, (
        "REST wire format drift detected (null-fields case). The frontend "
        "closeout guard checks property presence — fields must be present "
        "with explicit null, not absent."
    )




EXPECTED_MCP_DETAIL_FULL: dict = {
    "id": "proj-wire-full",
    "alias": "WF",
    "name": "Wire-format Full",
    "mission": "full mission",
    "description": "every optional field populated",
    "status": "active",
    "staging_status": "staging_complete",
    "implementation_launched_at": "2026-05-18T03:29:18+00:00",
    "reviewed_at": None,
    "review_pending": False,
    "product_id": "prod-wire",
    "tenant_key": _FAKE_TENANT,
    "execution_mode": "multi_terminal",
    "auto_checkin_enabled": True,
    "auto_checkin_interval": 15,
    "created_at": "2026-05-18T00:00:00+00:00",
    "updated_at": "2026-05-18T01:00:00+00:00",
    "completed_at": None,
    "cancellation_reason": None,
    "early_termination": False,
    "agents": [],
    "agent_count": 2,
    "message_count": 7,
    "project_type_id": "type-be",
    "project_type": None,
    "series_number": 42,
    "subseries": "a",
    "taxonomy_alias": "BE-0042a",
    "hidden": False,
    "successor_project_id": None,
}


def test_mcp_project_detail_wire_format_full() -> None:
    detail = _full_detail()
    assert detail.model_dump(mode="json") == EXPECTED_MCP_DETAIL_FULL, (
        "MCP ProjectDetail wire format drift detected. Orchestrator and "
        "agent prompts depend on this exact shape (field names, types, "
        "presence-vs-null semantics)."
    )




def _full_data() -> ProjectData:
    return ProjectData(
        id="proj-data-full",
        name="ProjectData Full",
        status="active",
        mission="data mission",
        description="data description",
        execution_mode="multi_terminal",
        auto_checkin_enabled=True,
        auto_checkin_interval=20,
        cancellation_reason=None,
        early_termination=False,
        created_at="2026-05-18T00:00:00+00:00",
        updated_at="2026-05-18T01:00:00+00:00",
        completed_at=None,
        product_id="prod-data",
        project_type_id="type-fe",
        project_type=None,
        series_number=7,
        subseries=None,
        taxonomy_alias="FE-0007",
        hidden=False,
    )


EXPECTED_MCP_DATA_FULL: dict = {
    "id": "proj-data-full",
    "name": "ProjectData Full",
    "status": "active",
    "mission": "data mission",
    "description": "data description",
    "execution_mode": "multi_terminal",
    "auto_checkin_enabled": True,
    "auto_checkin_interval": 20,
    "cancellation_reason": None,
    "early_termination": False,
    "created_at": "2026-05-18T00:00:00+00:00",
    "updated_at": "2026-05-18T01:00:00+00:00",
    "completed_at": None,
    "product_id": "prod-data",
    "project_type_id": "type-fe",
    "project_type": None,
    "series_number": 7,
    "subseries": None,
    "taxonomy_alias": "FE-0007",
    "hidden": False,
    "successor_project_id": None,
}


def test_mcp_project_data_wire_format_full() -> None:
    data = _full_data()
    assert data.model_dump(mode="json") == EXPECTED_MCP_DATA_FULL, (
        "MCP ProjectData wire format drift detected. cancel_staging and "
        "update_project responses depend on this exact shape."
    )
