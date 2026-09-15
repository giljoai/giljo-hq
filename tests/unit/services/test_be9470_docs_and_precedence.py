# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from tests.unit.services.test_list_projects_filtering import (
    _TENANT_A,
    _call_with_items,
    _make_item,
    _make_service,
)



_ALL_LIST_PROJECTS_PARAMS = (
    "status",
    "project_type",
    "taxonomy_alias_prefix",
    "created_after",
    "created_before",
    "completed_after",
    "completed_before",
    "include_completed",
    "include_superseded",
    "hidden",
    "summary_only",
    "depth",
    "status_filter",
    "mode",
    "memory_limit",
    "query",
    "limit",
    "cursor",
    "product_id",
)


class TestListProjectsWireDeliversAllParameterDocs:
    @staticmethod
    def _list_projects_schema() -> dict:
        from api.endpoints.mcp_sdk_server import mcp

        for tool in mcp._tool_manager.list_tools():
            if tool.name == "list_projects":
                return tool.parameters
        raise AssertionError("list_projects not found in the live tool registry")

    def test_registry_still_declares_exactly_the_same_nineteen_parameters(self):
        schema = self._list_projects_schema()
        assert set(schema["properties"]) == set(_ALL_LIST_PROJECTS_PARAMS), (
            "the live registry's parameter NAME set must stay exactly what it was -- "
            "this fix delivers descriptions, it does not touch the surface"
        )

    def test_every_parameter_delivers_a_description_to_the_wire(self):
        schema = self._list_projects_schema()
        undelivered = [
            name
            for name in _ALL_LIST_PROJECTS_PARAMS
            if not (schema["properties"].get(name, {}).get("description") or "").strip()
        ]
        assert not undelivered, f"parameters with no wire-delivered description: {undelivered}"

    def test_depth_description_states_the_new_precedence_not_the_superseded_one(self):
        schema = self._list_projects_schema()
        description = schema["properties"]["depth"]["description"].lower()
        assert "when summary_only=false" not in description, (
            "depth's wire description still states the superseded 'only when summary_only=False' precedence"
        )

    def test_status_and_status_filter_descriptions_state_the_conflict_rule(self):
        schema = self._list_projects_schema()
        status_desc = schema["properties"]["status"]["description"].lower()
        status_filter_desc = schema["properties"]["status_filter"]["description"].lower()
        assert "conflict" in status_desc or "refus" in status_desc
        assert "conflict" in status_filter_desc or "refus" in status_filter_desc




@pytest.mark.asyncio
class TestStatusStatusFilterConflict:
    async def test_status_completed_status_filter_active_is_refused(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="c", status="completed"),
            _make_item(project_id="ac", status="active"),
        ]
        with pytest.raises(ValidationError) as excinfo:
            await _call_with_items(service, items, status="completed", status_filter="active")
        assert "completed" in str(excinfo.value)
        assert "active" in str(excinfo.value)

    async def test_status_inactive_status_filter_completed_is_refused_reversed(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="i", status="inactive"),
            _make_item(project_id="c", status="completed"),
        ]
        with pytest.raises(ValidationError) as excinfo:
            await _call_with_items(service, items, status="inactive", status_filter="completed")
        assert "inactive" in str(excinfo.value)
        assert "completed" in str(excinfo.value)

    async def test_status_filter_all_conflicts_with_any_explicit_status(self):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="i", status="inactive")]
        with pytest.raises(ValidationError) as excinfo:
            await _call_with_items(service, items, status="inactive", status_filter="all")
        assert "all" in str(excinfo.value)
        assert "inactive" in str(excinfo.value)

    async def test_identical_values_pass_without_conflict(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="c", status="completed"),
        ]
        result, _ = await _call_with_items(service, items, status="completed", status_filter="completed")
        assert {p["project_id"] for p in result["projects"]} == {"c"}

    async def test_status_filter_alone_still_works(self):
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="x", status="cancelled"),
        ]
        result, _ = await _call_with_items(service, items, status_filter="cancelled")
        assert {p["project_id"] for p in result["projects"]} == {"x"}

    async def test_invalid_status_filter_value_still_refused_when_status_also_set(self):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        with pytest.raises(ValidationError, match="bogus_status_filter_be9470"):
            await _call_with_items(service, items, status="active", status_filter="bogus_status_filter_be9470")

    async def test_vocabulary_refusal_wins_over_conflict_refusal(self):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        with pytest.raises(ValidationError) as excinfo:
            await _call_with_items(service, items, status="active", status_filter="bogus_be9470")
        message = str(excinfo.value)
        assert "Must be one of" in message, f"expected the vocabulary error, got: {message}"
        assert "disagree" not in message




@pytest.mark.asyncio
class TestDepthPrecedenceOverSummaryOnlyDefault:
    async def test_explicit_depth_overrides_summary_only_default(self):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        result, _ = await _call_with_items(service, items, depth=3)
        assert result["depth"] == 3

    async def test_default_depth_zero_is_unchanged(self):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        result, _ = await _call_with_items(service, items)
        assert result["depth"] == 0

    async def test_explicit_depth_with_explicit_summary_only_false_is_unchanged(self):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        result, _ = await _call_with_items(service, items, depth=2, summary_only=False)
        assert result["depth"] == 2

    async def test_mode_still_wins_over_explicit_depth_under_default_summary_only(self):
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        result, _ = await _call_with_items(service, items, mode="triage", depth=3)
        assert result["depth"] == 0
