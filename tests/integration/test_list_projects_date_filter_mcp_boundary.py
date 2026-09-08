# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary regression tests for CE-0034 list_projects date filters.

CLAUDE.md mandates a regression test at the failing layer for every bug-fix
project. The CE-0034 bug lives at the FastMCP ``@mcp.tool`` wrapper for
``list_projects`` in ``api/endpoints/mcp_sdk_server.py``: date-only ISO strings
like ``"2026-04-17"`` were parsed by ``datetime.fromisoformat()`` into NAIVE
datetimes, then handed to ``ProjectService.list_projects_for_mcp`` where they
were compared against tz-aware ``ProjectListItem.created_at`` / ``completed_at``
values. The comparison raised ``TypeError: can't compare offset-naive and
offset-aware datetimes``.

The existing service-layer tests at
``tests/unit/services/test_list_projects_filtering.py`` cover
``created_after`` / ``completed_after`` but pass pre-parsed tz-aware datetime
objects directly to the service — bypassing the wrapper boundary where the
bug lives. This file closes that gap by exercising the actual FastMCP
transport for all four date params.

Also includes a direct unit test on the extracted
``_parse_iso_datetime_param`` helper so the regression is visible at the
exact line the bug used to live on.

Pattern reference: ``tests/integration/test_complete_job_mcp_boundary.py``
(same in-memory transport, same ``_resolve_tenant`` monkeypatch).
"""

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


# ---------------------------------------------------------------------------
# Direct unit tests on the extracted helper
# ---------------------------------------------------------------------------


class TestParseIsoDatetimeParam:
    """Unit tests on ``_parse_iso_datetime_param`` — the helper that lives at
    the MCP boundary and used to return naive datetimes for date-only strings."""

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


# ---------------------------------------------------------------------------
# End-to-end FastMCP transport tests
# ---------------------------------------------------------------------------


def _payload(call_tool_result) -> dict:
    """Extract structured payload from an MCP CallToolResult."""
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
    """Build a ProjectListItem for list_projects_for_mcp consumption."""
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
    """Yield ``(new_client, tenant_key, project_items)`` for FastMCP transport tests.

    The fixture installs:
    - A monkeypatched ``_resolve_tenant`` so the in-memory transport has a
      synthetic tenant_key (no auth middleware in the in-process MCP fixture).
    - A patched ``ProductService`` (as seen from the ProjectService module)
      whose ``get_default_product()`` returns a canned product — so the
      ``no active product`` validation gate doesn't block dispatch.
    - A patched ``ProjectService.list_projects`` returning canned
      ``ProjectListItem`` rows with tz-aware ``created_at`` / ``completed_at``
      values — the comparison block in ``list_projects_for_mcp`` then runs
      against the parsed date-filter params and exercises the exact line the
      CE-0034 ``TypeError`` used to raise on.
    """
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

    # BE-6042d: the @mcp.tool wrappers + _call_tool moved into the
    # api.endpoints.mcp_tools subpackage; _resolve_tenant/_resolve_user_id are now
    # resolved from mcp_tools._base, so the in-memory-transport monkeypatch must
    # target _base (mcp_sdk_server re-exports them but the call site reads _base).
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    # Canned data that exercises the date-comparison block.
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

    # Patch the inner data sources used by list_projects_for_mcp.
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
    # BE-9499a: list_projects_for_mcp resolves through resolve_binding_product now
    # (byte-identical result for an omitted product_id -- the active product).
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
    """Through the FastMCP transport, pass date-only ISO STRINGS to every
    date filter and assert the wrapper does not raise ``TypeError``.

    Pre-CE-0034: ``datetime.fromisoformat("2026-04-17")`` returned a naive
    datetime that crashed the comparison block. The fix coerces to
    tz-aware (UTC) at the boundary."""

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
        # Only the "def" project (created 2026-05-10) is after the 2026-04-17 boundary.
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
        # Only "abc" (created 2026-01-05) is before the 2026-04-17 boundary.
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
        # "def" completed 2026-06-01 (after); "abc" completed 2026-03-01 (before).
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
        """Defense-in-depth: every date param passed at once as date-only strings
        through the same call. Pre-fix this would crash on whichever comparison
        ran first."""
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
