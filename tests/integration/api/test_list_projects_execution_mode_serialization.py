# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints.projects import router as projects_router
from api.endpoints.projects.dependencies import get_project_service
from api.endpoints.projects.models import ProjectListResponse
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.schemas.responses.project import ProjectListItem


def _list_item(execution_mode: str | None) -> ProjectListItem:
    return ProjectListItem(
        id="11111111-1111-1111-1111-111111111111",
        name="Regression Project",
        mission="do the thing",
        description="desc",
        status="active",
        staging_status=None,
        implementation_launched_at=None,
        execution_mode=execution_mode,
        tenant_key="tk_test",
        product_id="22222222-2222-2222-2222-222222222222",
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
        completed_at=None,
        project_type_id=None,
        project_type=None,
        series_number=None,
        subseries=None,
        taxonomy_alias=None,
        hidden=False,
    )


def _map_like_endpoint(proj: ProjectListItem) -> ProjectListResponse:
    return ProjectListResponse(
        id=proj.id,
        alias="",
        name=proj.name,
        status=proj.status,
        staging_status=proj.staging_status,
        product_id=proj.product_id,
        created_at=proj.created_at,
        updated_at=proj.updated_at,
        completed_at=None,
        implementation_launched_at=None,
        agent_count=0,
        message_count=0,
        agents=[],
        execution_mode=proj.execution_mode,
        project_type_id=proj.project_type_id,
        project_type=proj.project_type,
        series_number=proj.series_number,
        subseries=proj.subseries,
        taxonomy_alias=proj.taxonomy_alias,
        hidden=getattr(proj, "hidden", False),
    )


def test_project_list_item_has_execution_mode():
    assert hasattr(_list_item(None), "execution_mode")


def test_list_endpoint_mapping_with_null_execution_mode():
    resp = _map_like_endpoint(_list_item(None))
    assert resp.execution_mode is None


def test_list_endpoint_mapping_with_selected_execution_mode():
    resp = _map_like_endpoint(_list_item("claude_code_cli"))
    assert resp.execution_mode == "claude_code_cli"




_GUARD_TENANT = "tenant-be1000d-guard"


class _FakeUser:
    id = "user-be1000d-guard"
    username = "be1000d_guard_tester"
    tenant_key = _GUARD_TENANT


class _StubProjectService:

    def __init__(self, items: list[ProjectListItem]) -> None:
        self._items = items

    async def list_projects(
        self,
        status: str | None = None,
        tenant_key: str | None = None,
        include_cancelled: bool = False,
        product_id: str | None = None,
        hidden: bool | None = None,
        search: str | None = None,
        sort_key: str | None = None,
        sort_dir: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[ProjectListItem]:
        return self._items

    async def count_projects(self, **_kwargs) -> int:
        return len(self._items)


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


def _fully_populated_item() -> ProjectListItem:
    now = datetime.now(UTC).isoformat()
    return ProjectListItem(
        id="33333333-3333-3333-3333-333333333333",
        name="Real-router Guard Project",
        mission="exercise the real endpoint",
        description="full population",
        status="active",
        staging_status="staging_complete",
        implementation_launched_at=now,
        execution_mode="claude_code_cli",
        tenant_key=_GUARD_TENANT,
        product_id="44444444-4444-4444-4444-444444444444",
        created_at=now,
        updated_at=now,
        completed_at=None,
        project_type_id="55555555-5555-5555-5555-555555555555",
        project_type=None,
        series_number=7,
        subseries="a",
        taxonomy_alias="BE-0007a",
        hidden=False,
    )


@pytest.mark.asyncio
async def test_list_endpoint_real_router_serializes() -> None:
    app = _build_app(_StubProjectService([_fully_populated_item()]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["execution_mode"] == "claude_code_cli"


@pytest.mark.asyncio
async def test_deleted_endpoint_real_router_serializes() -> None:
    app = _build_app(_StubProjectService([_fully_populated_item()]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/deleted")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["execution_mode"] == "claude_code_cli"




@pytest.mark.asyncio
async def test_list_wire_omits_mission_and_description() -> None:
    app = _build_app(_StubProjectService([_fully_populated_item()]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert "mission" not in row, "list wire must not ship per-row mission"
    assert "description" not in row, "list wire must not ship per-row description"
    assert row["name"] == "Real-router Guard Project"
    assert row["taxonomy_alias"] == "BE-0007a"
    assert row["status"] == "active"


@pytest.mark.asyncio
async def test_deleted_wire_omits_mission_and_description() -> None:
    app = _build_app(_StubProjectService([_fully_populated_item()]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/deleted")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert "mission" not in row
    assert "description" not in row


def test_list_wire_model_drops_body_fields() -> None:
    fields = set(ProjectListResponse.model_fields)
    assert "mission" not in fields
    assert "description" not in fields




class _CapturingProjectService:

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def list_projects(
        self,
        status=None,
        tenant_key: str | None = None,
        include_cancelled: bool = False,
        product_id: str | None = None,
        hidden: bool | None = None,
        search: str | None = None,
        sort_key: str | None = None,
        sort_dir: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[ProjectListItem]:
        self.calls.append(
            {
                "status": status,
                "tenant_key": tenant_key,
                "include_cancelled": include_cancelled,
                "product_id": product_id,
                "hidden": hidden,
                "search": search,
                "sort_key": sort_key,
                "sort_dir": sort_dir,
                "limit": limit,
                "offset": offset,
            }
        )
        return []

    async def count_projects(self, **_kwargs) -> int:
        return 0


@pytest.mark.asyncio
async def test_list_default_excludes_archived_statuses() -> None:
    svc = _CapturingProjectService()
    app = _build_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/")
    assert resp.status_code == 200, resp.text

    passed_status = svc.calls[0]["status"]
    assert isinstance(passed_status, list)
    for archived in ("completed", "cancelled", "terminated", "deleted", "superseded"):
        assert archived not in passed_status, f"default list must exclude {archived}"
    assert "active" in passed_status
    assert svc.calls[0]["hidden"] is False, "default list must exclude hidden rows"


@pytest.mark.asyncio
async def test_list_include_completed_shows_all() -> None:
    svc = _CapturingProjectService()
    app = _build_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/?include_completed=true")
    assert resp.status_code == 200, resp.text

    assert svc.calls[0]["status"] is None
    assert svc.calls[0]["include_cancelled"] is True
    assert svc.calls[0]["hidden"] is False


@pytest.mark.asyncio
async def test_list_explicit_status_filter_overrides_default() -> None:
    svc = _CapturingProjectService()
    app = _build_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/?status_filter=completed")
    assert resp.status_code == 200, resp.text

    assert svc.calls[0]["status"] == "completed"




@pytest.mark.asyncio
async def test_list_default_excludes_hidden() -> None:
    svc = _CapturingProjectService()
    app = _build_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/")
    assert resp.status_code == 200, resp.text
    assert svc.calls[0]["hidden"] is False


@pytest.mark.asyncio
async def test_list_hidden_only_returns_hidden() -> None:
    svc = _CapturingProjectService()
    app = _build_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/?hidden_only=true&include_completed=true")
    assert resp.status_code == 200, resp.text
    assert svc.calls[0]["hidden"] is True
    assert svc.calls[0]["status"] is None


@pytest.mark.asyncio
async def test_list_include_hidden_returns_both() -> None:
    svc = _CapturingProjectService()
    app = _build_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/?include_hidden=true")
    assert resp.status_code == 200, resp.text
    assert svc.calls[0]["hidden"] is None


@pytest.mark.asyncio
async def test_hidden_only_wins_over_include_hidden() -> None:
    svc = _CapturingProjectService()
    app = _build_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/?include_hidden=true&hidden_only=true")
    assert resp.status_code == 200, resp.text
    assert svc.calls[0]["hidden"] is True


@pytest.mark.asyncio
async def test_list_emits_real_completed_at() -> None:
    completed_iso = datetime(2026, 6, 9, 12, 0, tzinfo=UTC).isoformat()
    item = ProjectListItem(
        id="66666666-6666-6666-6666-666666666666",
        name="Finished Project",
        mission="m",
        description="d",
        status="completed",
        staging_status=None,
        implementation_launched_at=None,
        execution_mode="claude_code_cli",
        tenant_key=_GUARD_TENANT,
        product_id="44444444-4444-4444-4444-444444444444",
        created_at=datetime(2026, 6, 1, tzinfo=UTC).isoformat(),
        updated_at=datetime(2026, 6, 9, tzinfo=UTC).isoformat(),
        completed_at=completed_iso,
        project_type_id=None,
        project_type=None,
        series_number=8,
        subseries=None,
        taxonomy_alias="BE-0008",
        hidden=False,
    )
    app = _build_app(_StubProjectService([item]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects/?include_completed=true")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["completed_at"] is not None, "completed_at must not be hard-coded to None"
    assert body[0]["completed_at"].startswith("2026-06-09")
