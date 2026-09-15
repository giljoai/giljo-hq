# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.schemas.responses.project import ProjectListItem, ProjectTypeInfo
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio




class TestParseIsoDatetimeParam:

    async def test_date_only_string_returns_tz_aware(self):
        from api.endpoints.mcp_sdk_server import _parse_iso_datetime_param

        result = _parse_iso_datetime_param("2026-04-17")
        assert result is not None
        assert result.tzinfo is not None, (
            "CE-0034: date-only ISO strings must be coerced to tz-aware (UTC) "
            "so downstream comparisons against TIMESTAMPTZ values don't raise TypeError"
        )
        assert result == datetime(2026, 4, 17, tzinfo=UTC)

    async def test_full_isoformat_with_z_suffix_returns_tz_aware(self):
        from api.endpoints.mcp_sdk_server import _parse_iso_datetime_param

        result = _parse_iso_datetime_param("2026-04-17T12:30:00Z")
        assert result is not None
        assert result.tzinfo is not None
        assert result == datetime(2026, 4, 17, 12, 30, 0, tzinfo=UTC)

    async def test_full_isoformat_with_offset_preserves_offset(self):
        from api.endpoints.mcp_sdk_server import _parse_iso_datetime_param

        result = _parse_iso_datetime_param("2026-04-17T12:30:00+05:00")
        assert result is not None
        assert result.tzinfo is not None

    async def test_empty_string_returns_none(self):
        from api.endpoints.mcp_sdk_server import _parse_iso_datetime_param

        assert _parse_iso_datetime_param("") is None

    async def test_invalid_string_raises_validation_error(self):
        from api.endpoints.mcp_sdk_server import _parse_iso_datetime_param

        with pytest.raises(ValidationError):
            _parse_iso_datetime_param("not-a-date")




def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _make_project_item(
    *,
    project_id: str,
    status: str = "active",
    created_at: datetime,
    completed_at: datetime | None = None,
    tenant_key: str,
) -> ProjectListItem:
    return ProjectListItem(
        id=project_id,
        name=f"Project {project_id}",
        mission="",
        description="",
        status=status,
        staging_status=None,
        tenant_key=tenant_key,
        product_id="prod-001",
        created_at=created_at.isoformat(),
        updated_at=created_at.isoformat(),
        completed_at=completed_at.isoformat() if completed_at else None,
        project_type_id="t-1",
        project_type=ProjectTypeInfo(id="t-1", abbreviation="BE", label="BE", color="#fff"),
        series_number=5036,
        subseries=None,
        taxonomy_alias=f"BE-{5036 + int(project_id, 36) % 999:04d}",
        hidden=False,
    )


@pytest_asyncio.fixture
async def date_filter_mcp_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    project_items = [
        _make_project_item(
            project_id="abc",
            status="completed",
            created_at=datetime(2026, 1, 5, tzinfo=UTC),
            completed_at=datetime(2026, 3, 1, tzinfo=UTC),
            tenant_key=tenant_key,
        ),
        _make_project_item(
            project_id="def",
            status="completed",
            created_at=datetime(2026, 5, 10, tzinfo=UTC),
            completed_at=datetime(2026, 6, 1, tzinfo=UTC),
            tenant_key=tenant_key,
        ),
    ]

    product = Mock()
    product.id = "prod-001"

    product_svc_patch = patch("giljo_mcp.services.product_service.ProductService")
    list_proj_patch = patch(
        "giljo_mcp.services.project_service.ProjectService.list_projects",
        new=AsyncMock(return_value=project_items),
    )
    build_list_patch = patch(
        "giljo_mcp.services.project_service.ProjectService._build_mcp_project_list",
        new=AsyncMock(
            side_effect=lambda projects, depth, tk, **_kwargs: [
                {
                    "project_id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "taxonomy_alias": p.taxonomy_alias,
                    "created_at": p.created_at,
                    "completed_at": p.completed_at,
                }
                for p in projects
            ]
        ),
    )

    mock_product_svc = product_svc_patch.start()
    mock_product_svc.return_value.get_default_product = AsyncMock(return_value=product)
    mock_product_svc.return_value.resolve_binding_product = AsyncMock(return_value=product)
    list_proj_patch.start()
    build_list_patch.start()

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, project_items
    finally:
        product_svc_patch.stop()
        list_proj_patch.stop()
        build_list_patch.stop()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


class TestListProjectsDateFiltersMCPBoundary:

    async def test_created_after_date_only_string_no_typeerror(self, date_filter_mcp_client):
        new_client, _tenant_key, _items = date_filter_mcp_client

        async with new_client() as mcp_session:
            result = await mcp_session.call_tool(
                "list_projects",
                {"created_after": "2026-04-17", "include_completed": True},
            )

        assert result.is_error is False, (
            f"CE-0034: list_projects with date-only created_after must NOT raise; got: {_error_text(result)}"
        )
        payload = _payload(result)
        assert payload.get("success") is True
        ids = {p["project_id"] for p in payload.get("projects", [])}
        assert "def" in ids
        assert "abc" not in ids

    async def test_created_before_date_only_string_no_typeerror(self, date_filter_mcp_client):
        new_client, _tenant_key, _items = date_filter_mcp_client

        async with new_client() as mcp_session:
            result = await mcp_session.call_tool(
                "list_projects",
                {"created_before": "2026-04-17", "include_completed": True},
            )

        assert result.is_error is False, (
            f"CE-0034: list_projects with date-only created_before must NOT raise; got: {_error_text(result)}"
        )
        payload = _payload(result)
        assert payload.get("success") is True
        ids = {p["project_id"] for p in payload.get("projects", [])}
        assert "abc" in ids
        assert "def" not in ids

    async def test_completed_after_date_only_string_no_typeerror(self, date_filter_mcp_client):
        new_client, _tenant_key, _items = date_filter_mcp_client

        async with new_client() as mcp_session:
            result = await mcp_session.call_tool(
                "list_projects",
                {"completed_after": "2026-04-17", "include_completed": True},
            )

        assert result.is_error is False, (
            f"CE-0034: list_projects with date-only completed_after must NOT raise; got: {_error_text(result)}"
        )
        payload = _payload(result)
        assert payload.get("success") is True
        ids = {p["project_id"] for p in payload.get("projects", [])}
        assert ids == {"def"}

    async def test_completed_before_date_only_string_no_typeerror(self, date_filter_mcp_client):
        new_client, _tenant_key, _items = date_filter_mcp_client

        async with new_client() as mcp_session:
            result = await mcp_session.call_tool(
                "list_projects",
                {"completed_before": "2026-04-17", "include_completed": True},
            )

        assert result.is_error is False, (
            f"CE-0034: list_projects with date-only completed_before must NOT raise; got: {_error_text(result)}"
        )
        payload = _payload(result)
        assert payload.get("success") is True
        ids = {p["project_id"] for p in payload.get("projects", [])}
        assert ids == {"abc"}

    async def test_all_four_date_params_simultaneously_no_typeerror(self, date_filter_mcp_client):
        new_client, _tenant_key, _items = date_filter_mcp_client

        async with new_client() as mcp_session:
            result = await mcp_session.call_tool(
                "list_projects",
                {
                    "created_after": "2026-01-01",
                    "created_before": "2026-12-31",
                    "completed_after": "2026-01-01",
                    "completed_before": "2026-12-31",
                    "include_completed": True,
                },
            )

        assert result.is_error is False, (
            f"CE-0034: list_projects with all four date-only filters must NOT raise; got: {_error_text(result)}"
        )
        payload = _payload(result)
        assert payload.get("success") is True
