# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9470 findings 1+2+3 (the ``list_projects`` side) -- black-box QA units
U68/U70/U71 reproduced at the layer each defect actually lives at.

Finding 1 (U71-F1) -- ``list_projects`` delivered only 6 of its 18 parameter
descriptions to the wire (measured live against the FastMCP tool registry,
the same schema an agent reads before it ever calls); the other twelve are
bare defaults whose accurate ``Args:`` docstring prose never reaches an
agent. Fix: ``Annotated[..., Field(description=...)]`` on all eighteen.

Finding 2 (U68-F1) -- ``status`` silently won over ``status_filter`` even
when their effective meanings disagreed, including the worst case
(``status_filter='all'`` -- the only spelling of "the whole board" --
silently defeated by a lingering ``status``). Fix: refuse on a genuine
disagreement; identical/compatible values still pass.

Finding 3 (U9-F2/U70-F1) -- an explicit ``depth`` lost to the
``summary_only=True`` default while ``mode`` -- same tool, same call shape --
won. Fix: give ``depth`` the same precedence ``mode`` already has: an
explicit nonzero ``depth`` overrides the ``summary_only`` default; ``mode``
still wins over ``depth`` when both are passed (unchanged, already tested by
``test_list_projects_filtering.py::TestModeParameter::test_mode_wins_over_depth``).

Edition Scope: Both.
"""

from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from tests.unit.services.test_list_projects_filtering import (
    _TENANT_A,
    _call_with_items,
    _make_item,
    _make_service,
)


# ---------------------------------------------------------------------------
# Finding 1 (U71-F1) -- every list_projects parameter must deliver a
# description to the live MCP schema, the same wire an agent reads.
# ---------------------------------------------------------------------------

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
    # BE-9499a: explicit product to scope to.
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
        """U71-F1: no parameter added, removed or renamed by this fix (BE-9499a's
        product_id is accounted for in _ALL_LIST_PROJECTS_PARAMS above, so this
        still locks the surface -- it just locks 19, not 18)."""
        schema = self._list_projects_schema()
        assert set(schema["properties"]) == set(_ALL_LIST_PROJECTS_PARAMS), (
            "the live registry's parameter NAME set must stay exactly what it was -- "
            "this fix delivers descriptions, it does not touch the surface"
        )

    def test_every_parameter_delivers_a_description_to_the_wire(self):
        """U71-F1: 18/18, not 6/18 -- every Args: line must reach the agent."""
        schema = self._list_projects_schema()
        undelivered = [
            name
            for name in _ALL_LIST_PROJECTS_PARAMS
            if not (schema["properties"].get(name, {}).get("description") or "").strip()
        ]
        assert not undelivered, f"parameters with no wire-delivered description: {undelivered}"

    def test_depth_description_states_the_new_precedence_not_the_superseded_one(self):
        """The stranded docstring line ('depth ... when summary_only=False') must be
        corrected, not just relocated -- it described the OLD, now-superseded
        behavior (museum-rule check: no incident pins the old wording, see PR body)."""
        schema = self._list_projects_schema()
        description = schema["properties"]["depth"]["description"].lower()
        assert "when summary_only=false" not in description, (
            "depth's wire description still states the superseded 'only when summary_only=False' precedence"
        )

    def test_status_and_status_filter_descriptions_state_the_conflict_rule(self):
        """Both Field descriptions must state the refusal rule (per the project text)."""
        schema = self._list_projects_schema()
        status_desc = schema["properties"]["status"]["description"].lower()
        status_filter_desc = schema["properties"]["status_filter"]["description"].lower()
        assert "conflict" in status_desc or "refus" in status_desc
        assert "conflict" in status_filter_desc or "refus" in status_filter_desc


# ---------------------------------------------------------------------------
# Finding 2 (U68-F1) -- status/status_filter conflict -> structured refusal;
# identical/compatible values still pass.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStatusStatusFilterConflict:
    async def test_status_completed_status_filter_active_is_refused(self):
        """QA's exact probe, direction 1: status='completed' + status_filter='active'
        silently returned the `completed` rows (`status` winning) with no warning.
        Routed through ``_call_with_items`` (repo/product calls stubbed) so a
        pre-fix run demonstrates the REAL silent-success defect -- not a harness
        crash from an unmocked repo call -- and only the fix makes this raise."""
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
        """QA's exact probe, direction 2 (rules out coincidence): reversing which
        value is on which parameter must refuse the same way, not just one way."""
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
        """QA's WORST CASE: status_filter='all' is the only spelling of "the whole
        board" (status does not accept 'all') -- any lingering status must not
        silently defeat it. This is the row that used to come back success:true
        with 67/471 instead of everything."""
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="i", status="inactive")]
        with pytest.raises(ValidationError) as excinfo:
            await _call_with_items(service, items, status="inactive", status_filter="all")
        assert "all" in str(excinfo.value)
        assert "inactive" in str(excinfo.value)

    async def test_identical_values_pass_without_conflict(self):
        """Control: status and status_filter naming the SAME status must NOT be
        refused -- only a genuine disagreement is a conflict."""
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="c", status="completed"),
        ]
        result, _ = await _call_with_items(service, items, status="completed", status_filter="completed")
        assert {p["project_id"] for p in result["projects"]} == {"c"}

    async def test_status_filter_alone_still_works(self):
        """Control (already-working path, U68-F1 named it 'live, not vestigial'):
        status_filter passed alone, with no status, must be unaffected."""
        service = _make_service(_TENANT_A)
        items = [
            _make_item(project_id="a", status="active"),
            _make_item(project_id="x", status="cancelled"),
        ]
        result, _ = await _call_with_items(service, items, status_filter="cancelled")
        assert {p["project_id"] for p in result["projects"]} == {"x"}

    async def test_invalid_status_filter_value_still_refused_when_status_also_set(self):
        """status_filter's own vocabulary must still be validated even when status
        is also present -- previously this branch never even looked at
        status_filter, so a garbage value alongside a real status passed silently."""
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        with pytest.raises(ValidationError, match="bogus_status_filter_be9470"):
            await _call_with_items(service, items, status="active", status_filter="bogus_status_filter_be9470")

    async def test_vocabulary_refusal_wins_over_conflict_refusal(self):
        """An invalid status_filter value must be caught by the VOCABULARY check
        before the disagreement check ever runs -- otherwise status='active'+
        status_filter='bogus' would be refused as a "disagree" conflict naming a
        value that was never legal in the first place, which teaches the wrong
        lesson. Pin the actual error text, not just that SOME ValidationError
        was raised."""
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        with pytest.raises(ValidationError) as excinfo:
            await _call_with_items(service, items, status="active", status_filter="bogus_be9470")
        message = str(excinfo.value)
        assert "Must be one of" in message, f"expected the vocabulary error, got: {message}"
        assert "disagree" not in message


# ---------------------------------------------------------------------------
# Finding 3 (U9-F2/U70-F1) -- depth gets mode's precedence over summary_only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDepthPrecedenceOverSummaryOnlyDefault:
    async def test_explicit_depth_overrides_summary_only_default(self):
        """QA's exact probe: depth=3, summary_only left at its True default -- must
        resolve to depth 3 (forensic-equivalent), not silently fall to depth 0."""
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        result, _ = await _call_with_items(service, items, depth=3)
        assert result["depth"] == 3

    async def test_default_depth_zero_is_unchanged(self):
        """Control: no depth passed at all (depth=0 default) must still resolve to
        depth 0 -- this fix must not change the default, bare-call behavior."""
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        result, _ = await _call_with_items(service, items)
        assert result["depth"] == 0

    async def test_explicit_depth_with_explicit_summary_only_false_is_unchanged(self):
        """Control: the already-working combination (summary_only=False passed
        explicitly) must still resolve depth exactly as before."""
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        result, _ = await _call_with_items(service, items, depth=2, summary_only=False)
        assert result["depth"] == 2

    async def test_mode_still_wins_over_explicit_depth_under_default_summary_only(self):
        """mode continues to beat depth when both are passed (already documented,
        already pinned for the summary_only=False case by
        test_list_projects_filtering.py::TestModeParameter::test_mode_wins_over_depth)
        -- this pins the SAME precedence under the summary_only DEFAULT (True), the
        combination that had no test before this fix."""
        service = _make_service(_TENANT_A)
        items = [_make_item(project_id="a", status="active")]
        result, _ = await _call_with_items(service, items, mode="triage", depth=3)
        assert result["depth"] == 0
