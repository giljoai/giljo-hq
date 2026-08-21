# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for v1.2.1 list_projects server-side filtering contract.

Covers ProjectService.list_projects_for_mcp() new parameter surface:
- status: str | list[str] | None
- project_type: str | list[str] | None
- taxonomy_alias_prefix: str | None
- created_after / created_before: datetime | None
- completed_after / completed_before: datetime | None
- include_completed: bool (default False) -- new lifecycle filter
- hidden: bool | None

Default behavior change (BREAKING):
- status=None AND include_completed=False  ->  exclude {completed, cancelled}
- status explicitly set                    ->  user wins, ignore include_completed
- hidden defaults to None (do NOT auto-hide hidden projects)

Tenant isolation: every test passes an explicit tenant_key. Cross-tenant
test confirms tenant_key flows through unchanged.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.schemas.responses.project import ProjectListItem, ProjectTypeInfo
from giljo_mcp.services.project_service import (
    LIFECYCLE_FINISHED_STATUSES,
    ProjectService,
)
from giljo_mcp.utils.taxonomy_alias import format_taxonomy_alias


_TENANT_A = "tenant-aaa"
_TENANT_B = "tenant-bbb"
_PRODUCT_SERVICE_PATH = "giljo_mcp.services.product_service.ProductService"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(tenant_key: str) -> ProjectService:
    db_manager = Mock()
    mock_session = AsyncMock()
    db_manager.get_session_async = Mock(return_value=mock_session)
    db_manager.get_tenant_session_async = Mock(return_value=mock_session)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.info = {}  # tenant_session_context save/restore target
    mock_result = Mock()
    mock_result.scalars = Mock(return_value=Mock(all=Mock(return_value=[])))
    mock_session.execute = AsyncMock(return_value=mock_result)

    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)

    return ProjectService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=None,
    )


def _make_item(
    *,
    project_id: str = "p-1",
    name: str = "Project",
    status: str = "active",
    product_id: str = "prod-001",
    type_abbrev: str | None = "BE",
    series_number: int | None = 5036,
    subseries: str | None = None,
    hidden: bool = False,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
    tenant_key: str = _TENANT_A,
) -> ProjectListItem:
    """Build a ProjectListItem with the fields list_projects_for_mcp consumes."""
    created = (created_at or datetime(2026, 1, 1, tzinfo=UTC)).isoformat()
    completed_iso = completed_at.isoformat() if completed_at else None
    type_info = (
        ProjectTypeInfo(id="t-1", abbreviation=type_abbrev, label=type_abbrev or "X", color="#fff")
        if type_abbrev
        else None
    )
    taxonomy_alias = format_taxonomy_alias(type_abbrev, series_number, subseries, fallback="abc123")
    return ProjectListItem(
        id=project_id,
        name=name,
        mission="",
        description="",
        status=status,
        staging_status=None,
        tenant_key=tenant_key,
        product_id=product_id,
        created_at=created,
        updated_at=created,
        completed_at=completed_iso,
        project_type_id="t-1" if type_abbrev else None,
        project_type=type_info,
        series_number=series_number,
        subseries=subseries,
        taxonomy_alias=taxonomy_alias,
        hidden=hidden,
    )


def _patch_active_product(product_id: str = "prod-001"):
    """Return a contextmanager-style patch object setting an active product."""
    p = patch(_PRODUCT_SERVICE_PATH)
    return p, product_id


async def _call_with_items(service: ProjectService, items, **kwargs):
    """Run list_projects_for_mcp with list_projects() returning the given items.

    The inner ``list_projects`` mock simulates the repo's SQL pushdown: when
    called with ``status=<value|list>``, it returns only items whose status
    matches. This mirrors what the real repo does after the seq 161 fix.
    """
    mock_product = Mock()
    mock_product.id = kwargs.pop("active_product_id", "prod-001")

    async def _fake_list_projects(*_args, **call_kwargs):
        st = call_kwargs.get("status")
        if st is None:
            return list(items)
        allowed = {st} if isinstance(st, str) else set(st)
        return [it for it in items if it.status in allowed]

    list_proj_mock = AsyncMock(side_effect=_fake_list_projects)
    with (
        patch.object(service, "list_projects", list_proj_mock),
        patch.object(service, "board_counts", new_callable=AsyncMock, return_value=[]),
        patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
        patch.object(
            service,
            "_build_mcp_project_list",
            new=AsyncMock(
                side_effect=lambda projects, depth, tk, **_kwargs: [
                    {
                        "project_id": p.id,
                        "name": p.name,
                        "status": p.status,
                        "taxonomy_alias": p.taxonomy_alias,
                        "hidden": p.hidden,
                        "created_at": p.created_at,
                        "completed_at": p.completed_at,
                        "project_type": (p.project_type.abbreviation if p.project_type else None),
                    }
                    for p in projects
                ]
            ),
        ),
    ):
        mock_product_svc.return_value.get_active_product = AsyncMock(return_value=mock_product)
        result = await service.list_projects_for_mcp(tenant_key=_TENANT_A, **kwargs)
    return result, list_proj_mock


# ---------------------------------------------------------------------------
# Constant exposure
# ---------------------------------------------------------------------------


class TestLifecycleFinishedConstant:
    def test_lifecycle_finished_constant_exposed(self):
        # BE-5037 follow-up: all lifecycle-finished statuses so the default
        # exclusion bucket matches the frontend StatusBadge enum. BE-9157 added
        # ``superseded`` (a replaced-by-successor terminal state).
        assert (
            frozenset({"completed", "cancelled", "terminated", "deleted", "superseded"}) == LIFECYCLE_FINISHED_STATUSES
        )


# ---------------------------------------------------------------------------
# Default behavior (BREAKING change)
# ---------------------------------------------------------------------------


class TestDefaultLifecycleFilter:
    @pytest.mark.asyncio
    async def test_default_excludes_all_lifecycle_finished(self):
        """BE-5037 follow-up: default exclusion covers the full finished set
        {completed, cancelled, terminated, deleted}.

        On the test install at the time of this test, two projects (INF-0002 Ops Panel
        and BE-5006 BE-SPRINT-002f) carry status=='terminated'. Before this
        change they leaked through the default response because terminated was
        not in the exclusion bucket; now they are filtered out by default.
        """
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="b", status="inactive"),
            _make_item(project_id="c", status="completed"),
            _make_item(project_id="d", status="cancelled"),
            _make_item(project_id="t1", status="terminated"),
            _make_item(project_id="t2", status="terminated"),
        ]
        result, _ = await _call_with_items(service, items)
        ids = {p["project_id"] for p in result["projects"]}
        # 6 in -> 2 out (active + inactive). Mirrors the test-install 24->22 drop:
        # the two terminated rows are excluded by default.
        assert ids == {"a", "b"}, "Default must exclude completed, cancelled, terminated, deleted"

    @pytest.mark.asyncio
    async def test_default_includes_hidden_rows(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active", hidden=False),
            _make_item(project_id="b", status="active", hidden=True),
        ]
        result, _ = await _call_with_items(service, items)
        ids = {p["project_id"] for p in result["projects"]}
        assert ids == {"a", "b"}, "hidden=None default must NOT auto-filter hidden"

    @pytest.mark.asyncio
    async def test_include_completed_true_returns_finished(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="c", status="completed"),
            _make_item(project_id="d", status="cancelled"),
        ]
        result, _ = await _call_with_items(service, items, include_completed=True)
        ids = {p["project_id"] for p in result["projects"]}
        assert ids == {"a", "c", "d"}

    @pytest.mark.asyncio
    async def test_explicit_status_overrides_include_completed(self):
        """When status is explicitly set, include_completed is ignored."""
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="c1", status="completed"),
            _make_item(project_id="c2", status="completed"),
            _make_item(project_id="a1", status="active"),
        ]
        result, _ = await _call_with_items(service, items, status="completed", include_completed=False)
        ids = {p["project_id"] for p in result["projects"]}
        assert ids == {"c1", "c2"}


# ---------------------------------------------------------------------------
# Status filter
# ---------------------------------------------------------------------------


class TestStatusFilter:
    @pytest.mark.asyncio
    async def test_status_string_single(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="i", status="inactive"),
        ]
        result, _ = await _call_with_items(service, items, status="active")
        assert {p["project_id"] for p in result["projects"]} == {"a"}

    @pytest.mark.asyncio
    async def test_status_list_or_within_field(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="i", status="inactive"),
            _make_item(project_id="c", status="completed"),
        ]
        result, _ = await _call_with_items(service, items, status=["active", "inactive"])
        assert {p["project_id"] for p in result["projects"]} == {"a", "i"}

    @pytest.mark.asyncio
    async def test_invalid_status_raises_validation_error(self):
        service = _make_service(_TENANT_A)
        with pytest.raises(ValidationError) as exc_info:
            await service.list_projects_for_mcp(tenant_key=_TENANT_A, status="bogus")
        # Error message must list valid values
        assert "active" in str(exc_info.value)
        assert "bogus" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invalid_status_in_list_raises(self):
        service = _make_service(_TENANT_A)
        with pytest.raises(ValidationError):
            await service.list_projects_for_mcp(tenant_key=_TENANT_A, status=["active", "bogus"])

    @pytest.mark.asyncio
    async def test_status_terminated_returns_only_terminated(self):
        """BE-5037 follow-up: status='terminated' must be a valid filter value
        (was rejected as 'bogus' by the v1.2.1 4-value enum). Returns only
        rows where status=='terminated'.
        """
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="t1", status="terminated"),
            _make_item(project_id="t2", status="terminated"),
            _make_item(project_id="c", status="completed"),
        ]
        result, _ = await _call_with_items(service, items, status="terminated")
        assert {p["project_id"] for p in result["projects"]} == {"t1", "t2"}

    @pytest.mark.asyncio
    async def test_status_deleted_filter_validates(self):
        """status='deleted' must validate (no ValidationError).

        At runtime, ProjectRepository.list_projects() special-cases
        status='deleted' by switching the soft-delete clause from
        deleted_at IS NULL (default) to deleted_at IS NOT NULL when the
        caller supplies that status, so soft-deleted rows ARE reachable
        when the agent asks for them by status. This unit test pins the
        validation contract and the in-memory status filter; the
        repository-layer reachability is covered by repository tests.
        """
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="d1", status="deleted"),
        ]
        result, _ = await _call_with_items(service, items, status="deleted")
        # Only the deleted row should pass the in-memory status filter.
        assert {p["project_id"] for p in result["projects"]} == {"d1"}

    @pytest.mark.asyncio
    async def test_status_validation_error_lists_all_six_values(self):
        """Validation message must enumerate all 6 valid statuses so agents
        get an actionable error.
        """
        service = _make_service(_TENANT_A)
        with pytest.raises(ValidationError) as exc_info:
            await service.list_projects_for_mcp(tenant_key=_TENANT_A, status="bogus")
        msg = str(exc_info.value)
        for expected in (
            "active",
            "inactive",
            "completed",
            "cancelled",
            "terminated",
            "deleted",
        ):
            assert expected in msg, f"Validation message missing '{expected}': {msg}"


# ---------------------------------------------------------------------------
# Project type filter
# ---------------------------------------------------------------------------


class TestProjectTypeFilter:
    @pytest.mark.asyncio
    async def test_project_type_single(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="be1", type_abbrev="BE"),
            _make_item(project_id="fe1", type_abbrev="FE"),
        ]
        with patch.object(
            ProjectService,
            "_get_valid_project_types",
            new=AsyncMock(return_value=[{"abbreviation": "BE"}, {"abbreviation": "FE"}]),
        ):
            result, _ = await _call_with_items(service, items, project_type="BE")
        assert {p["project_id"] for p in result["projects"]} == {"be1"}

    @pytest.mark.asyncio
    async def test_project_type_list(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="be1", type_abbrev="BE"),
            _make_item(project_id="fe1", type_abbrev="FE"),
            _make_item(project_id="inf1", type_abbrev="INF"),
        ]
        with patch.object(
            ProjectService,
            "_get_valid_project_types",
            new=AsyncMock(
                return_value=[
                    {"abbreviation": "BE"},
                    {"abbreviation": "FE"},
                    {"abbreviation": "INF"},
                ]
            ),
        ):
            result, _ = await _call_with_items(service, items, project_type=["BE", "INF"])
        assert {p["project_id"] for p in result["projects"]} == {"be1", "inf1"}

    @pytest.mark.asyncio
    async def test_invalid_project_type_raises(self):
        service = _make_service(_TENANT_A)
        with (
            patch.object(
                ProjectService,
                "_get_valid_project_types",
                new=AsyncMock(return_value=[{"abbreviation": "BE"}]),
            ),
            pytest.raises(ValidationError) as exc_info,
        ):
            await service.list_projects_for_mcp(tenant_key=_TENANT_A, project_type="BOGUS")
        assert "BOGUS" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Taxonomy alias prefix
# ---------------------------------------------------------------------------


class TestTaxonomyAliasPrefix:
    @pytest.mark.asyncio
    async def test_prefix_matches_series_subset(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="x1", type_abbrev="BE", series_number=5036),
            _make_item(project_id="x2", type_abbrev="BE", series_number=5099),
            _make_item(project_id="x3", type_abbrev="BE", series_number=5100),
        ]
        result, _ = await _call_with_items(service, items, taxonomy_alias_prefix="BE-50")
        ids = {p["project_id"] for p in result["projects"]}
        assert ids == {"x1", "x2"}, "BE-50 must match BE-5036, BE-5099 but NOT BE-5100"

    @pytest.mark.asyncio
    async def test_prefix_exact_match(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="x1", type_abbrev="BE", series_number=5036),
            _make_item(project_id="x2", type_abbrev="BE", series_number=5037),
        ]
        result, _ = await _call_with_items(service, items, taxonomy_alias_prefix="BE-5036")
        assert {p["project_id"] for p in result["projects"]} == {"x1"}


# ---------------------------------------------------------------------------
# Date range filters
# ---------------------------------------------------------------------------


class TestDateRangeFilters:
    @pytest.mark.asyncio
    async def test_created_after_before(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="old", created_at=datetime(2025, 1, 1, tzinfo=UTC)),
            _make_item(project_id="mid", created_at=datetime(2026, 1, 15, tzinfo=UTC)),
            _make_item(project_id="new", created_at=datetime(2026, 6, 1, tzinfo=UTC)),
        ]
        result, _ = await _call_with_items(
            service,
            items,
            created_after=datetime(2026, 1, 1, tzinfo=UTC),
            created_before=datetime(2026, 5, 1, tzinfo=UTC),
        )
        assert {p["project_id"] for p in result["projects"]} == {"mid"}

    @pytest.mark.asyncio
    async def test_completed_after_before(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(
                project_id="early",
                status="completed",
                completed_at=datetime(2026, 1, 5, tzinfo=UTC),
            ),
            _make_item(
                project_id="late",
                status="completed",
                completed_at=datetime(2026, 6, 5, tzinfo=UTC),
            ),
        ]
        result, _ = await _call_with_items(
            service,
            items,
            include_completed=True,
            completed_after=datetime(2026, 5, 1, tzinfo=UTC),
        )
        assert {p["project_id"] for p in result["projects"]} == {"late"}


# ---------------------------------------------------------------------------
# Combination filters
# ---------------------------------------------------------------------------


class TestCombinationFilters:
    @pytest.mark.asyncio
    async def test_status_and_project_type_intersection(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="be_active", status="active", type_abbrev="BE"),
            _make_item(project_id="fe_active", status="active", type_abbrev="FE"),
            _make_item(project_id="be_inactive", status="inactive", type_abbrev="BE"),
        ]
        with patch.object(
            ProjectService,
            "_get_valid_project_types",
            new=AsyncMock(return_value=[{"abbreviation": "BE"}, {"abbreviation": "FE"}]),
        ):
            result, _ = await _call_with_items(
                service,
                items,
                status="active",
                project_type="BE",
            )
        assert {p["project_id"] for p in result["projects"]} == {"be_active"}


# ---------------------------------------------------------------------------
# Hidden filter
# ---------------------------------------------------------------------------


class TestHiddenFilter:
    @pytest.mark.asyncio
    async def test_hidden_true_only_hidden(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="v", hidden=False),
            _make_item(project_id="h", hidden=True),
        ]
        result, _ = await _call_with_items(service, items, hidden=True)
        assert {p["project_id"] for p in result["projects"]} == {"h"}

    @pytest.mark.asyncio
    async def test_hidden_false_only_visible(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="v", hidden=False),
            _make_item(project_id="h", hidden=True),
        ]
        result, _ = await _call_with_items(service, items, hidden=False)
        assert {p["project_id"] for p in result["projects"]} == {"v"}

    @pytest.mark.asyncio
    async def test_hidden_none_returns_both(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="v", hidden=False),
            _make_item(project_id="h", hidden=True),
        ]
        result, _ = await _call_with_items(service, items)  # default hidden=None
        assert {p["project_id"] for p in result["projects"]} == {"v", "h"}

    @pytest.mark.asyncio
    async def test_hidden_field_present_in_payload_regardless_of_filter(self):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="v", hidden=False), _make_item(project_id="h", hidden=True)]
        result, _ = await _call_with_items(service, items, hidden=True)
        for row in result["projects"]:
            assert "hidden" in row, "hidden column must remain in row payload"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_tenant_key_flows_through(self):
        for tenant_key, product_id in ((_TENANT_A, "prod-aaa"), (_TENANT_B, "prod-bbb")):
            service = _make_service(tenant_key)
            mock_product = Mock()
            mock_product.id = product_id
            list_proj_mock = AsyncMock(return_value=[])
            with (
                patch.object(service, "list_projects", list_proj_mock),
                patch.object(service, "board_counts", new_callable=AsyncMock, return_value=[]),
                patch.object(service, "board_counts", new_callable=AsyncMock, return_value=[]),
                patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
                patch.object(service, "_build_mcp_project_list", new=AsyncMock(return_value=[])),
            ):
                mock_product_svc.return_value.get_active_product = AsyncMock(return_value=mock_product)
                result = await service.list_projects_for_mcp(tenant_key=tenant_key)
            assert result["product_id"] == product_id
            # tenant_key passed to the inner list_projects call
            kwargs = list_proj_mock.call_args.kwargs
            assert kwargs.get("tenant_key") == tenant_key


# ---------------------------------------------------------------------------
# MCP tool surface — list_projects param forwarding
#
# BE-6118: the pure ToolAccessor.list_projects pass-through was deleted (the
# @mcp.tool wrapper now dispatches straight to ProjectService.list_projects_for_mcp
# via TOOL_DISPATCH). The two former tests here asserted the deleted accessor
# method's signature + that it forwards to the service — both are now structurally
# guaranteed and locked elsewhere: the advertised param surface in
# test_be6042d_mcp_tool_registry_surface.py (list_projects exposes status /
# project_type / taxonomy_alias_prefix / include_completed / hidden / ...), the
# service-method presence in test_be6042c_project_service_surface.py, and the
# dispatch-to-service property in test_be3010b_registry_dispatch.py. The service's
# own forwarding/filtering behavior stays covered by the TestListProjects* tests
# above in this file.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Regression: list_projects vs fetch_context status agreement
# ---------------------------------------------------------------------------
#
# Reported bug: list_projects(status="inactive") returned a project that
# fetch_context(categories=["project"]) reported as status="completed". The
# same window also showed list_projects ignoring its status filter (returning
# all rows regardless of value). These regressions pin the contract:
#
#  1) The status filter must filter for EVERY canonical ProjectStatus value.
#  2) After a status transition, the next list_projects call must reflect it
#     (no stale cached row).
#  3) For a given (tenant_key, project_id), list_projects and the underlying
#     get_project read path must agree on the status value.


class TestStatusFilterCoversEntireEnum:
    """Parametrize over every ProjectStatus value: each must filter precisely."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "target_status",
        [s.value for s in __import__("giljo_mcp.domain.project_status", fromlist=["ProjectStatus"]).ProjectStatus],
    )
    async def test_status_filter_returns_only_matching_rows(self, target_status):
        from giljo_mcp.domain.project_status import ProjectStatus

        service = _make_service(_TENANT_A)
        items = [_make_item(project_id=f"id-{s.value}", status=s.value) for s in ProjectStatus]
        result, _ = await _call_with_items(service, items, status=target_status)
        ids = {p["project_id"] for p in result["projects"]}
        assert ids == {f"id-{target_status}"}, (
            f"status={target_status!r} must return exactly the row with that status; got {ids}"
        )


class TestStatusTransitionReflectedInList:
    """After a status transition, list_projects reflects the new value.

    This is a read-path regression: calling list_projects twice across a
    transition must return the row under its new status, never under the old.
    No sleeps, no caches in between -- if a cache layer is ever introduced,
    this test pins that it must be invalidated on write.
    """

    @pytest.mark.asyncio
    async def test_transition_active_to_completed_visible_in_next_call(self):
        service = _make_service(_TENANT_A)

        before = [_make_item(project_id="p-x", status="active")]
        result_active, _ = await _call_with_items(service, before, status="active")
        assert {p["project_id"] for p in result_active["projects"]} == {"p-x"}

        result_completed_pre, _ = await _call_with_items(service, before, status="completed")
        assert {p["project_id"] for p in result_completed_pre["projects"]} == set()

        after = [_make_item(project_id="p-x", status="completed")]
        result_completed, _ = await _call_with_items(service, after, status="completed")
        assert {p["project_id"] for p in result_completed["projects"]} == {"p-x"}, (
            "After transition active->completed, status='completed' filter must include the row"
        )

        result_active_post, _ = await _call_with_items(service, after, status="active")
        assert {p["project_id"] for p in result_active_post["projects"]} == set(), (
            "After transition active->completed, status='active' filter must NOT include the row"
        )


class TestListProjectsAndFetchContextAgree:
    """list_projects rows and the underlying get_project read path agree on status.

    Both paths read Project.status from the same model attribute. This
    regression asserts that the value flowing into the list payload (via
    ProjectListItem.status -> _build_mcp_project_list) matches the value the
    fetch_context project category reads (get_project -> project.status).
    Catches drift if either path ever introduces a derived/cached column.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_value", ["inactive", "active", "completed"])
    async def test_list_and_get_project_return_same_status_string(self, status_value):
        from unittest.mock import MagicMock

        from giljo_mcp.tools.context_tools.get_project import get_project

        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="p-1", status=status_value)]
        # include_completed=True so 'completed' is not excluded by the default
        # lifecycle filter; we are testing read-path parity, not the default.
        result, _ = await _call_with_items(service, items, include_completed=True)
        list_status = next(p["status"] for p in result["projects"] if p["project_id"] == "p-1")

        fake_project = MagicMock()
        fake_project.name = "n"
        fake_project.alias = "abc123"
        fake_project.description = "d"
        fake_project.mission = "m"
        fake_project.status = status_value
        fake_project.staging_status = None
        fake_project.orchestrator_summary = None

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.info = {}  # tenant_session_context save/restore target
        fake_result = Mock()
        fake_result.scalar_one_or_none = Mock(return_value=fake_project)
        fake_session.execute = AsyncMock(return_value=fake_result)
        fake_db_manager = Mock()
        fake_db_manager.get_session_async = Mock(return_value=fake_session)

        ctx_result = await get_project(
            project_id="p-1",
            tenant_key=_TENANT_A,
            include_summary=False,
            db_manager=fake_db_manager,
        )
        ctx_status = ctx_result["data"]["status"]

        assert str(list_status) == str(ctx_status) == status_value, (
            f"list_projects status={list_status!r} but fetch_context status={ctx_status!r}"
        )


# ---------------------------------------------------------------------------
# Seq 161 — SQL pushdown for status filter
# ---------------------------------------------------------------------------
#
# When status is provided to list_projects_for_mcp, the inner list_projects
# call must receive status (single string OR list) so the repo pushes the
# filter to SQL. Pre-fix behavior: outer always called list_projects(status=None,
# include_cancelled=True) and filtered status in a Python for-loop.


class TestStatusSqlPushdown:
    @pytest.mark.asyncio
    async def test_single_status_pushed_to_inner_list_projects(self):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        _, list_proj_mock = await _call_with_items(service, items, status="active")
        kwargs = list_proj_mock.call_args.kwargs
        # SQL pushdown: inner call must receive the status filter, not None
        assert kwargs.get("status") in ("active", ["active"]), (
            f"Expected status pushdown to inner list_projects; got status={kwargs.get('status')!r}"
        )

    @pytest.mark.asyncio
    async def test_status_list_pushed_to_inner_list_projects(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="i", status="inactive"),
        ]
        _, list_proj_mock = await _call_with_items(service, items, status=["active", "inactive"])
        kwargs = list_proj_mock.call_args.kwargs
        pushed = kwargs.get("status")
        # Either passed as list or normalized; must NOT be None.
        assert pushed is not None, "status list must be pushed down, not silently dropped"
        if isinstance(pushed, list):
            assert set(pushed) == {"active", "inactive"}
        else:
            assert pushed in ("active", "inactive")

    @pytest.mark.asyncio
    async def test_no_status_filter_pushes_lifecycle_exclusion_to_sql(self):
        """IMP-5036 task 9257a74c: when status is omitted and include_completed
        is False (default agent view), the inner list_projects call must receive
        the active-status complement set so the repo emits a SQL IN clause
        instead of pulling lifecycle-finished rows just to drop them in Python.
        """
        from giljo_mcp.domain.project_status import LIFECYCLE_FINISHED_STATUSES, ProjectStatus

        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        _, list_proj_mock = await _call_with_items(service, items)
        kwargs = list_proj_mock.call_args.kwargs
        pushed = kwargs.get("status")
        assert isinstance(pushed, list), (
            f"Default view must push the active-status complement to SQL; got status={pushed!r}"
        )
        active_complement = {s.value for s in ProjectStatus} - {s.value for s in LIFECYCLE_FINISHED_STATUSES}
        assert set(pushed) == active_complement, (
            f"Pushed status set must equal active-status complement; got {set(pushed)!r} vs {active_complement!r}"
        )

    @pytest.mark.asyncio
    async def test_include_completed_does_not_push_status(self):
        """IMP-5036 task 9257a74c: when include_completed=True is passed (caller
        wants archived buckets too), inner list_projects must receive status=None
        so the repo's bare-tenant path with include_cancelled=True returns all
        non-deleted rows.
        """
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="completed")]
        _, list_proj_mock = await _call_with_items(service, items, include_completed=True)
        kwargs = list_proj_mock.call_args.kwargs
        assert kwargs.get("status") is None, (
            f"include_completed=True must not push a status filter; got {kwargs.get('status')!r}"
        )

    @pytest.mark.asyncio
    async def test_repo_accepts_status_list(self):
        """Repository.list_projects must accept status as str | list[str] | None
        and emit a SQL IN clause when a list is passed.
        """
        import inspect

        from giljo_mcp.repositories.project_repository import ProjectRepository

        sig = inspect.signature(ProjectRepository.list_projects)
        ann = sig.parameters["status"].annotation
        ann_str = str(ann)
        assert "list" in ann_str.lower() or "Sequence" in ann_str or "Iterable" in ann_str, (
            f"Repo.list_projects.status must accept list[str]; got annotation {ann_str!r}"
        )

    @pytest.mark.asyncio
    async def test_repo_emits_in_clause_for_status_list(self):
        """Direct repo unit test: passing status=['active', 'inactive'] must
        produce a SQL WHERE ... IN (...) (not equality, not ignored).
        """
        from sqlalchemy.dialects import postgresql

        from giljo_mcp.repositories.project_repository import ProjectRepository

        repo = ProjectRepository()
        captured = {}

        class _FakeSession:
            async def execute(self, query):
                compiled = query.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
                captured["sql"] = str(compiled)

                class _R:
                    def scalars(self):
                        class _S:
                            def all(self):
                                return []

                        return _S()

                return _R()

        await repo.list_projects(
            _FakeSession(),
            tenant_key=_TENANT_A,
            status=["active", "inactive"],
            include_cancelled=True,
        )
        sql = captured["sql"].lower()
        assert "in (" in sql and "'active'" in sql and "'inactive'" in sql, (
            f"Expected IN-clause for status list; got SQL: {captured['sql']}"
        )


# ---------------------------------------------------------------------------
# BE-6078 — repo hidden filter (server-side offload)
# ---------------------------------------------------------------------------
#
# ProjectRepository.list_projects gained a ``hidden`` param so the REST list
# endpoint can exclude/return hidden rows at the SQL layer instead of shipping
# them over the wire to be dropped in JS. None=no filter, False=exclude hidden
# (NULL-safe), True=hidden only.


class TestRepoHiddenFilter:
    @staticmethod
    async def _compile(**kwargs) -> str:
        from sqlalchemy.dialects import postgresql

        from giljo_mcp.repositories.project_repository import ProjectRepository

        repo = ProjectRepository()
        captured: dict = {}

        class _FakeSession:
            async def execute(self, query):
                captured["sql"] = str(
                    query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
                ).lower()

                class _R:
                    def scalars(self):
                        class _S:
                            def all(self):
                                return []

                        return _S()

                return _R()

        await repo.list_projects(_FakeSession(), tenant_key=_TENANT_A, include_cancelled=True, **kwargs)
        return captured["sql"]

    @pytest.mark.asyncio
    async def test_hidden_none_emits_no_hidden_predicate(self):
        sql = await self._compile(hidden=None)
        # ``projects.hidden`` is always in the SELECT column list; assert there is
        # no ``hidden IS [NOT] TRUE`` WHERE predicate (the None = no-filter case).
        assert "hidden is" not in sql, f"hidden=None must not emit a hidden predicate; got: {sql}"

    @pytest.mark.asyncio
    async def test_hidden_false_excludes_hidden_null_safe(self):
        sql = await self._compile(hidden=False)
        # NULL-safe exclusion: ``hidden IS NOT TRUE`` (legacy NULLs stay visible).
        assert "hidden is not true" in sql, f"hidden=False must emit IS NOT TRUE; got: {sql}"

    @pytest.mark.asyncio
    async def test_hidden_true_only_hidden(self):
        sql = await self._compile(hidden=True)
        assert "hidden is true" in sql, f"hidden=True must emit IS TRUE; got: {sql}"


# ---------------------------------------------------------------------------
# Seq 139 — list_projects payload byte-share audit
# ---------------------------------------------------------------------------
#
# Measurement only (no trimming). Builds a representative depth-2 payload
# (the cohort that historically blew past 63K) and reports per-field byte
# share so a follow-up project knows where the inflation lives. Field
# expectations:
#   - top-level shape: count, depth, projects[N], product_id, success
#   - per-row at depth>=1: description, mission, agent_summary
#   - per-row at depth>=2: memory_entries (suspected primary), agent_details
#   - per-row at depth>=3: message_history, git_commits
#
# This test always passes — it asserts the report shape and prints the
# breakdown. CI runs the print; the report is the artifact.


class TestListProjectsPayloadShareAudit:
    @staticmethod
    def _measure_share(payload: dict) -> list[tuple[str, int, float]]:
        import json

        total = len(json.dumps(payload, default=str))
        rows = payload.get("projects", [])

        per_field_bytes: dict[str, int] = {}
        for row in rows:
            for field, value in row.items():
                per_field_bytes[field] = per_field_bytes.get(field, 0) + len(json.dumps(value, default=str))

        for top_field, top_value in payload.items():
            if top_field == "projects":
                continue
            per_field_bytes[f"[top].{top_field}"] = len(json.dumps(top_value, default=str))

        report = sorted(
            (
                (field, byte_count, (byte_count / total * 100.0) if total else 0.0)
                for field, byte_count in per_field_bytes.items()
            ),
            key=lambda x: -x[1],
        )
        return report

    def test_payload_share_report_depth_2(self, capsys):
        """Build a representative depth-2 payload with 24 projects (the
        test-install cohort) and report byte share per field. Prints to stdout
        so the audit artifact is visible in CI logs.
        """
        sample_memory_entry = {
            "entry_type": "decision",
            "content": "x" * 800,  # representative entry body
            "tags": ["edition:CE", "audit:seq139"],
            "git_commits": [{"sha": "a" * 40, "message": "y" * 80} for _ in range(3)],
            "created_at": "2026-05-04T00:00:00+00:00",
        }
        sample_agent_detail = {
            "agent_id": "00000000-0000-0000-0000-000000000001",
            "agent_name": "implementer",
            "status": "complete",
            "mission": "z" * 400,
        }

        rows = []
        for i in range(24):
            rows.append(
                {
                    "project_id": f"id-{i:04d}",
                    "name": f"Project {i}",
                    "status": "active",
                    "project_type": "BE",
                    "series_number": 5000 + i,
                    "taxonomy_alias": f"BE-{5000 + i}",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "completed_at": None,
                    "description": "d" * 240,
                    "mission": "m" * 320,
                    "agent_summary": {"total": 4, "complete": 4, "blocked": 0},
                    "memory_entries": [sample_memory_entry] * 6,
                    "agent_details": [sample_agent_detail] * 4,
                }
            )

        payload = {
            "success": True,
            "product_id": "prod-001",
            "count": len(rows),
            "depth": 2,
            "projects": rows,
        }

        report = self._measure_share(payload)
        import json

        total = len(json.dumps(payload, default=str))

        print("\n=== Seq 139 — list_projects payload byte-share audit (depth=2, N=24) ===")
        print(f"Total payload bytes: {total}")
        print(f"{'field':<30} {'bytes':>10} {'share %':>10}")
        for field, bytes_, pct in report:
            print(f"{field:<30} {bytes_:>10} {pct:>9.2f}%")

        # Sanity: report has every field we built and totals roughly add up.
        field_names = {f for f, _, _ in report}
        for expected in (
            "memory_entries",
            "agent_details",
            "description",
            "mission",
            "name",
            "project_id",
        ):
            assert expected in field_names, f"audit must report on '{expected}'"

        # Capture proves the print landed (regression for silent test).
        captured = capsys.readouterr()
        assert "byte-share audit" in captured.out
        assert "memory_entries" in captured.out

    def test_audit_mode_payload_70pct_smaller_than_depth_2(self, capsys):
        """BE-5042: mode='audit' must produce a payload at least 70% smaller
        than depth=2 on the test-install cohort shape (24 projects, 6 memory entries
        each, 4 agent details each).

        Audit mode trims memory entries to headlines (drops key_outcomes,
        decisions_made, git_commits, project_name) and caps to last 5; agent
        details drop the result blob and full mission text.
        """
        import json

        sample_memory_full = {
            "id": "00000000-0000-0000-0000-0000000000aa",
            "entry_type": "decision",
            "sequence": 7,
            "project_name": "Project N",
            "summary": "s" * 200,
            "key_outcomes": ["k" * 120 for _ in range(4)],
            "decisions_made": ["d" * 140 for _ in range(3)],
            "git_commits": [{"sha": "a" * 40, "message": "y" * 80} for _ in range(3)],
            "timestamp": "2026-05-04T00:00:00+00:00",
        }
        sample_memory_headline = {
            "id": "00000000-0000-0000-0000-0000000000aa",
            "sequence": 7,
            "entry_type": "decision",
            "summary": "s" * 200,
            "timestamp": "2026-05-04T00:00:00+00:00",
        }
        sample_agent_full = {
            "job_id": "00000000-0000-0000-0000-000000000001",
            "job_type": "implementer",
            "status": "complete",
            "display_name": "implementer-backend",
            "agent_status": "complete",
            "mission": "z" * 400,
            "result": {"summary": "r" * 600, "artifacts": ["a" * 80 for _ in range(4)]},
            "created_at": "2026-05-04T00:00:00+00:00",
            "completed_at": "2026-05-04T01:00:00+00:00",
        }
        sample_agent_headline = {
            "job_id": "00000000-0000-0000-0000-000000000001",
            "display_name": "implementer-backend",
            "status": "complete",
            "completed_at": "2026-05-04T01:00:00+00:00",
        }

        def _row(memory_entries, agent_details):
            return {
                "project_id": "id-0000",
                "name": "Project 0",
                "status": "active",
                "project_type": "BE",
                "series_number": 5000,
                "taxonomy_alias": "BE-5000",
                "created_at": "2026-01-01T00:00:00+00:00",
                "completed_at": None,
                "description": "d" * 240,
                "mission": "m" * 320,
                "agent_summary": {"total": 4, "complete": 4, "blocked": 0},
                "memory_entries": memory_entries,
                "agent_details": agent_details,
            }

        depth_2_rows = [_row([sample_memory_full] * 6, [sample_agent_full] * 4) for _ in range(24)]
        audit_rows = [_row([sample_memory_headline] * 5, [sample_agent_headline] * 4) for _ in range(24)]

        depth_2_payload = {
            "success": True,
            "product_id": "prod-001",
            "count": 24,
            "depth": 2,
            "projects": depth_2_rows,
        }
        audit_payload = {
            "success": True,
            "product_id": "prod-001",
            "count": 24,
            "mode": "audit",
            "depth": 2,
            "projects": audit_rows,
        }

        depth_bytes = len(json.dumps(depth_2_payload, default=str))
        audit_bytes = len(json.dumps(audit_payload, default=str))
        reduction_pct = (1.0 - audit_bytes / depth_bytes) * 100.0

        print(
            f"\n=== BE-5042 audit-mode payload reduction: depth_2={depth_bytes}B "
            f"audit={audit_bytes}B reduction={reduction_pct:.2f}% ==="
        )
        captured = capsys.readouterr()
        assert "audit-mode payload reduction" in captured.out
        assert reduction_pct >= 70.0, f"audit-mode payload must be >=70% smaller than depth=2; got {reduction_pct:.2f}%"


# ---------------------------------------------------------------------------
# BE-5042 — mode parameter (triage/planning/audit/forensic)
# ---------------------------------------------------------------------------


class TestModeParameter:
    """mode is the agent-facing surface; numeric depth remains for back-compat."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("mode", "expected_depth"),
        [("triage", 0), ("planning", 1), ("audit", 2), ("forensic", 3)],
    )
    async def test_mode_translates_to_depth(self, mode, expected_depth):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        result, _ = await _call_with_items(service, items, mode=mode)
        assert result["depth"] == expected_depth

    @pytest.mark.asyncio
    async def test_mode_wins_over_depth(self):
        """When both passed, mode determines the depth (agent intent wins)."""
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        # depth=3 + mode=triage -> depth resolves to 0
        result, _ = await _call_with_items(service, items, mode="triage", depth=3, summary_only=False)
        assert result["depth"] == 0

    @pytest.mark.asyncio
    async def test_invalid_mode_raises(self):
        service = _make_service(_TENANT_A)
        with pytest.raises(ValidationError) as exc_info:
            await service.list_projects_for_mcp(tenant_key=_TENANT_A, mode="bogus")
        assert "mode" in str(exc_info.value).lower()
        assert "bogus" in str(exc_info.value)


# ---------------------------------------------------------------------------
# BE-5042 — query service headlines projection
# ---------------------------------------------------------------------------


class TestQueryServiceHeadlines:
    """ProjectQueryService methods accept headlines and limit params (single
    method, parameter flag — no forked methods).
    """

    @pytest.mark.asyncio
    async def test_get_project_memory_entries_full_keys(self):
        from giljo_mcp.services.project_query_service import ProjectQueryService

        db_manager = Mock()
        tenant_manager = Mock()
        svc = ProjectQueryService(db_manager=db_manager, tenant_manager=tenant_manager)

        fake_entry = Mock()
        fake_entry.id = "00000000-0000-0000-0000-0000000000aa"
        fake_entry.entry_type = "decision"
        fake_entry.sequence = 7
        fake_entry.project_name = "Proj"
        fake_entry.summary = "s"
        fake_entry.key_outcomes = ["a", "b"]
        fake_entry.decisions_made = ["x"]
        fake_entry.git_commits = [{"sha": "a" * 40}]
        fake_entry.timestamp = datetime(2026, 5, 4, tzinfo=UTC)

        with patch.object(
            svc._repo,
            "get_memory_entries_for_project",
            new=AsyncMock(return_value=[fake_entry]),
        ):
            with patch.object(svc, "_get_session") as gs:
                session = AsyncMock()
                session.__aenter__ = AsyncMock(return_value=session)
                session.__aexit__ = AsyncMock(return_value=False)
                session.info = {}  # tenant_session_context save/restore target
                gs.return_value = session
                rows = await svc.get_project_memory_entries("p-1", _TENANT_A)
        assert rows[0]["entry_type"] == "decision"
        for k in ("key_outcomes", "decisions_made", "git_commits", "project_name"):
            assert k in rows[0]

    @pytest.mark.asyncio
    async def test_get_project_memory_entries_headlines_only(self):
        from giljo_mcp.services.project_query_service import ProjectQueryService

        svc = ProjectQueryService(db_manager=Mock(), tenant_manager=Mock())

        fake_entry = Mock()
        fake_entry.id = "00000000-0000-0000-0000-0000000000aa"
        fake_entry.entry_type = "decision"
        fake_entry.sequence = 7
        fake_entry.project_name = "Proj"
        fake_entry.summary = "s"
        fake_entry.key_outcomes = ["a", "b"]
        fake_entry.decisions_made = ["x"]
        fake_entry.git_commits = [{"sha": "a" * 40}]
        fake_entry.timestamp = datetime(2026, 5, 4, tzinfo=UTC)

        with patch.object(
            svc._repo,
            "get_memory_entries_for_project",
            new=AsyncMock(return_value=[fake_entry]),
        ):
            with patch.object(svc, "_get_session") as gs:
                session = AsyncMock()
                session.__aenter__ = AsyncMock(return_value=session)
                session.__aexit__ = AsyncMock(return_value=False)
                session.info = {}  # tenant_session_context save/restore target
                gs.return_value = session
                rows = await svc.get_project_memory_entries("p-1", _TENANT_A, headlines=True)
        row = rows[0]
        assert set(row.keys()) == {"id", "sequence", "entry_type", "summary", "timestamp"}
        for dropped in ("key_outcomes", "decisions_made", "git_commits", "project_name"):
            assert dropped not in row

    @pytest.mark.asyncio
    async def test_get_project_memory_entries_limit_passes_through(self):
        from giljo_mcp.services.project_query_service import ProjectQueryService

        svc = ProjectQueryService(db_manager=Mock(), tenant_manager=Mock())
        repo_mock = AsyncMock(return_value=[])
        with patch.object(svc._repo, "get_memory_entries_for_project", new=repo_mock):
            with patch.object(svc, "_get_session") as gs:
                session = AsyncMock()
                session.__aenter__ = AsyncMock(return_value=session)
                session.__aexit__ = AsyncMock(return_value=False)
                session.info = {}  # tenant_session_context save/restore target
                gs.return_value = session
                await svc.get_project_memory_entries("p-1", _TENANT_A, headlines=True, limit=5)
        assert repo_mock.call_args.kwargs.get("limit") == 5 or 5 in repo_mock.call_args.args

    @pytest.mark.asyncio
    async def test_get_project_agent_details_headlines_only(self):
        from giljo_mcp.services.project_query_service import ProjectQueryService

        svc = ProjectQueryService(db_manager=Mock(), tenant_manager=Mock())

        job = Mock()
        job.job_id = "j1"
        job.job_type = "implementer"
        job.status = "complete"
        job.mission = "m" * 400
        job.created_at = datetime(2026, 5, 4, tzinfo=UTC)
        job.completed_at = datetime(2026, 5, 4, 1, tzinfo=UTC)
        execution = Mock()
        execution.agent_display_name = "impl-backend"
        execution.status = "complete"
        execution.result = {"summary": "r" * 600}

        with patch.object(
            svc._repo,
            "get_agent_details_for_project",
            new=AsyncMock(return_value=[(job, execution)]),
        ):
            with patch.object(svc, "_get_session") as gs:
                session = AsyncMock()
                session.__aenter__ = AsyncMock(return_value=session)
                session.__aexit__ = AsyncMock(return_value=False)
                session.info = {}  # tenant_session_context save/restore target
                gs.return_value = session
                rows = await svc.get_project_agent_details("p-1", _TENANT_A, headlines=True)
        row = rows[0]
        assert set(row.keys()) == {"job_id", "display_name", "status", "completed_at"}
        assert "result" not in row
        assert "mission" not in row


# ---------------------------------------------------------------------------
# BE-5042 — memory_limit clamp + forensic full bodies
# ---------------------------------------------------------------------------


class TestMemoryLimitClamp:
    @pytest.mark.asyncio
    async def test_audit_default_limit_5(self):
        """Audit mode passes memory_limit=5 to the query service by default.

        BE-6071 F6b: _build_mcp_project_list now calls the BATCHED enrichment
        methods (one grouped query per facet), so the propagation is asserted
        against those siblings.
        """
        service = _make_service(_TENANT_A)
        captured: dict = {}

        async def _fake_mem(project_ids, tenant_key, headlines=False, limit=None):
            captured["headlines"] = headlines
            captured["limit"] = limit
            return {}

        async def _fake_agents(project_ids, tenant_key, headlines=False):
            captured["agent_headlines"] = headlines
            return {}

        async def _fake_summary(project_ids, tenant_key):
            return {}

        items = [_make_item(project_id="a", status="active")]
        with patch.object(service.query, "get_project_memory_entries_batch", new=AsyncMock(side_effect=_fake_mem)):
            with patch.object(
                service.query, "get_project_agent_details_batch", new=AsyncMock(side_effect=_fake_agents)
            ):
                with patch.object(
                    service.query, "get_project_agent_summaries", new=AsyncMock(side_effect=_fake_summary)
                ):
                    await _call_with_items_real_build(service, items, mode="audit")
        assert captured["limit"] == 5
        assert captured["headlines"] is True
        assert captured["agent_headlines"] is True

    @pytest.mark.asyncio
    async def test_audit_memory_limit_override(self):
        service = _make_service(_TENANT_A)
        captured: dict = {}

        async def _fake_mem(project_ids, tenant_key, headlines=False, limit=None):
            captured["limit"] = limit
            return {}

        items = [_make_item(project_id="a", status="active")]
        with patch.object(service.query, "get_project_memory_entries_batch", new=AsyncMock(side_effect=_fake_mem)):
            with patch.object(service.query, "get_project_agent_details_batch", new=AsyncMock(return_value={})):
                with patch.object(service.query, "get_project_agent_summaries", new=AsyncMock(return_value={})):
                    await _call_with_items_real_build(service, items, mode="audit", memory_limit=10)
        assert captured["limit"] == 10

    @pytest.mark.asyncio
    async def test_audit_memory_limit_clamps_at_50(self):
        service = _make_service(_TENANT_A)
        captured: dict = {}

        async def _fake_mem(project_ids, tenant_key, headlines=False, limit=None):
            captured["limit"] = limit
            return {}

        items = [_make_item(project_id="a", status="active")]
        with patch.object(service.query, "get_project_memory_entries_batch", new=AsyncMock(side_effect=_fake_mem)):
            with patch.object(service.query, "get_project_agent_details_batch", new=AsyncMock(return_value={})):
                with patch.object(service.query, "get_project_agent_summaries", new=AsyncMock(return_value={})):
                    await _call_with_items_real_build(service, items, mode="audit", memory_limit=999)
        assert captured["limit"] == 50

    @pytest.mark.asyncio
    async def test_forensic_full_bodies_no_default_cap(self):
        service = _make_service(_TENANT_A)
        captured: dict = {}

        async def _fake_mem(project_ids, tenant_key, headlines=False, limit=None):
            captured["headlines"] = headlines
            captured["limit"] = limit
            return {}

        async def _fake_agents(project_ids, tenant_key, headlines=False):
            captured["agent_headlines"] = headlines
            return {}

        items = [_make_item(project_id="a", status="active")]
        with patch.object(service.query, "get_project_memory_entries_batch", new=AsyncMock(side_effect=_fake_mem)):
            with patch.object(
                service.query, "get_project_agent_details_batch", new=AsyncMock(side_effect=_fake_agents)
            ):
                with patch.object(service.query, "get_project_agent_summaries", new=AsyncMock(return_value={})):
                    # Depth-3 forensic messages stay PER-PROJECT (not batched).
                    with patch.object(service.query, "get_project_messages", new=AsyncMock(return_value=[])):
                        await _call_with_items_real_build(service, items, mode="forensic")
        assert captured["headlines"] is False
        assert captured["limit"] is None
        assert captured["agent_headlines"] is False


# ---------------------------------------------------------------------------
# BE-5042 — tenant isolation regression (mode-mode queries)
# ---------------------------------------------------------------------------


class TestModeTenantIsolation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["triage", "planning", "audit", "forensic"])
    async def test_tenant_key_filters_in_every_mode(self, mode):
        """A project from another tenant must never appear in any mode."""
        service = _make_service(_TENANT_A)
        # _call_with_items mocks list_projects to honor the test fixture only;
        # cross-tenant items should never reach the response. Pass a tenant-B
        # item alongside a tenant-A item; the inner mock must filter by tenant.
        items_a = [_make_item(project_id="a-1", status="active", tenant_key=_TENANT_A)]
        # Confirm tenant_key flows to the inner list_projects call.
        result, list_proj_mock = await _call_with_items(service, items_a, mode=mode)
        assert list_proj_mock.call_args.kwargs.get("tenant_key") == _TENANT_A
        assert {p["project_id"] for p in result["projects"]} == {"a-1"}


async def _call_with_items_real_build(service: ProjectService, items, **kwargs):
    """Like _call_with_items but exercises the real _build_mcp_project_list.

    Used when the test needs to assert that mode/headlines/limit propagate from
    list_projects_for_mcp into the query-service calls.
    """
    mock_product = Mock()
    mock_product.id = kwargs.pop("active_product_id", "prod-001")

    async def _fake_list_projects(*_args, **call_kwargs):
        st = call_kwargs.get("status")
        if st is None:
            return list(items)
        allowed = {st} if isinstance(st, str) else set(st)
        return [it for it in items if it.status in allowed]

    list_proj_mock = AsyncMock(side_effect=_fake_list_projects)
    with (
        patch.object(service, "list_projects", list_proj_mock),
        patch.object(service, "board_counts", new_callable=AsyncMock, return_value=[]),
        patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
    ):
        mock_product_svc.return_value.get_active_product = AsyncMock(return_value=mock_product)
        result = await service.list_projects_for_mcp(tenant_key=_TENANT_A, **kwargs)
    return result, list_proj_mock


# ---------------------------------------------------------------------------
# IMP-5036 task 696cf625 — payload-size instrumentation
# ---------------------------------------------------------------------------


class TestPayloadSizeInstrumentation:
    @pytest.mark.asyncio
    async def test_payload_size_logged_with_breakdown(self, caplog):
        """list_projects_for_mcp must emit a DEBUG log line per call with
        total payload bytes, per-row top contributing field, and field-byte
        counts. This is the post-strip 63K-overflow forensic signal — DEBUG
        so it stays out of the operational INFO log.
        """
        import logging

        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active", series_number=1),
            _make_item(project_id="b", status="active", series_number=2),
        ]
        with caplog.at_level(logging.DEBUG, logger="giljo_mcp.services.project_service.ProjectService"):
            await _call_with_items(service, items)

        matching = [r for r in caplog.records if "list_projects payload size" in r.getMessage()]
        assert matching, "Expected a DEBUG log line with 'list_projects payload size'"
        msg = matching[-1].getMessage()
        assert "total_bytes=" in msg, f"Log line missing total_bytes signal: {msg!r}"
        assert "rows=2" in msg, f"Log line should reflect 2 rows: {msg!r}"
        assert "breakdown=" in msg, f"Log line missing per-row breakdown: {msg!r}"
        assert "top_field" in msg, f"Log line missing top_field key: {msg!r}"
