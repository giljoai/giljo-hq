# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9470 (tasks side) -- black-box QA units U67 and U69 found two defects in
``TaskService.list_tasks_for_mcp``'s filter/projection resolution.

Finding 4 (U69-F1) -- an explicit ``mode`` lost to the legacy ``summary_only``
flag whenever both were passed: ``mode='index', summary_only=True`` silently
returned the 'summary' projection, and ``mode='full', memory_limit=40,
summary_only=True`` silently returned 'summary' with BOTH supplied parameters
voided. ``list_projects`` already resolves this correctly (mode wins over
depth/summary_only); this module reproduces the QA probes at the service
layer -- ``resolve_list_mode``'s call site -- the layer the bug lived at.

Finding 5 (U67-F1) -- ``task_type`` had an EMPTY DOMAIN: the one value that
matches every task ('TSK', BE-6049c) was refused as a reserved tag, while
every accepted value (the 11 real project-taxonomy abbreviations) matched
zero rows -- the same response's ``counts.by_type`` reading ``{"TSK": 173}``
in flat contradiction. Reproduced at the service layer, where the reserved-
tag refusal (``TaxonomyService.validate``) and the filter resolution
(``validate_task_type_filter``) both live.

Edition Scope: Both.
"""

from __future__ import annotations

import pytest

from api.endpoints.mcp_tools import _task_tools
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.taxonomy_service import TaxonomyService


async def _seed_be_taxonomy(db_session, tenant_key: str, db_manager) -> None:
    service = TaxonomyService(db_manager=db_manager, session=db_session)
    existing = {row.abbreviation for row in await service.list_types(tenant_key)}
    if "BE" not in existing:
        await service.create_type(tenant_key=tenant_key, abbreviation="BE", label="Backend", sort_order=0)
    await db_session.commit()


async def _create_task(two_tenant_service_setup, db_session, *, description: str = "seed") -> str:
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.create_task_for_mcp(
        title="BE-9470 tasks-side seed task",
        description=description,
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    return response["task_id"]


# ---------------------------------------------------------------------------
# Finding 4 (U69-F1) -- an explicit mode must WIN over the legacy
# summary_only flag, and memory_limit must not be silently voided with it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListTasksModeWinsOverSummaryOnly:
    async def test_index_mode_wins_over_summary_only_true(self, db_session, two_tenant_service_setup):
        """QA's exact probe: mode='index' + summary_only=True must return the
        lean index row -- before the fix summary_only silently discarded the
        explicit mode and the response reported mode='summary'."""
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", summary_only=True)
        assert response["mode"] == "index"
        row = response["tasks"][0]
        assert "name" in row
        assert "description" not in row
        assert "title" not in row

    async def test_full_mode_and_memory_limit_win_over_summary_only_true(self, db_session, two_tenant_service_setup):
        """QA's exact probe: mode='full' + memory_limit=40 + summary_only=True
        must return the full row with description truncated at 40 chars --
        before the fix BOTH supplied parameters were silently voided."""
        long_description = "x" * 60
        await _create_task(two_tenant_service_setup, db_session, description=long_description)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        response = await task_service_a.list_tasks_for_mcp(
            tenant_key=tenant_a, mode="full", summary_only=True, memory_limit=40
        )
        assert response["mode"] == "full"
        row = response["tasks"][0]
        assert row["description"] == ("x" * 40) + "..."

    async def test_precedence_pinned_at_index_end_with_summary_only_false(self, db_session, two_tenant_service_setup):
        """The already-working corner must not regress."""
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", summary_only=False)
        assert response["mode"] == "index"

    async def test_precedence_pinned_at_full_end_with_summary_only_false(self, db_session, two_tenant_service_setup):
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="full", summary_only=False)
        assert response["mode"] == "full"

    async def test_summary_only_alone_still_resolves_the_legacy_precedence(self, db_session, two_tenant_service_setup):
        """A caller passing ONLY summary_only (mode omitted) must stay
        byte-identical to the pre-BE-9470 behaviour -- summary_only still
        governs when there is no explicit mode to defer to."""
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        summary_response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, summary_only=True)
        assert summary_response["mode"] == "summary"

        full_response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, summary_only=False)
        assert full_response["mode"] == "full"


# ---------------------------------------------------------------------------
# Wire-layer pin (cross-layer reconciliation, 2026-08-19): QA's U69 row 3
# (mode='index', summary_only=false -> index, PASS) measured the WIRE, where
# the @mcp.tool wrapper's ``if summary_only: kwargs["summary_only"] = True``
# guard never forwards a falsy summary_only at all -- mode was ALREADY
# honored at that layer pre-fix. The widened finding above (mode='index' +
# summary_only=False clobbering mode) is a SERVICE-layer-only latent branch,
# reachable only by a caller that passes summary_only=False explicitly to
# list_tasks_for_mcp directly (as the service-layer tests above do) -- never
# reachable through this wrapper before the fix. Both observations are true,
# at different layers; QA did not miss anything. This test pins the WRAPPER
# semantics directly so a future edit to its kwargs-building cannot silently
# start forwarding summary_only=False and resurrect that latent branch here.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListTasksWireWrapperKwargsSemantics:
    async def test_false_summary_only_is_never_forwarded_mode_passes_through(self, monkeypatch):
        captured = {}

        async def fake_call_tool(ctx, method_name, kwargs):
            captured["kwargs"] = kwargs
            return {}

        monkeypatch.setattr(_task_tools, "_call_tool", fake_call_tool)

        await _task_tools.list_tasks(mode="index", summary_only=False)
        assert "summary_only" not in captured["kwargs"]
        assert captured["kwargs"]["mode"] == "index"

    async def test_true_summary_only_is_forwarded_alongside_an_explicit_mode(self, monkeypatch):
        captured = {}

        async def fake_call_tool(ctx, method_name, kwargs):
            captured["kwargs"] = kwargs
            return {}

        monkeypatch.setattr(_task_tools, "_call_tool", fake_call_tool)

        await _task_tools.list_tasks(mode="index", summary_only=True)
        assert captured["kwargs"]["summary_only"] is True
        assert captured["kwargs"]["mode"] == "index"

    async def test_omitted_mode_forwards_none_not_the_wire_sentinel(self, monkeypatch):
        """BE-9470: the wire default changed from the literal "summary" to the
        "" sentinel, forwarded as None -- the service layer needs a real
        omitted-vs-explicit signal to let mode win only when actually passed."""
        captured = {}

        async def fake_call_tool(ctx, method_name, kwargs):
            captured["kwargs"] = kwargs
            return {}

        monkeypatch.setattr(_task_tools, "_call_tool", fake_call_tool)

        await _task_tools.list_tasks()
        assert captured["kwargs"]["mode"] is None
        assert "summary_only" not in captured["kwargs"]


# ---------------------------------------------------------------------------
# Finding 5 (U67-F1) -- task_type's only legal value is the reserved 'TSK'
# tag; it must be ACCEPTED (not refused as reserved), and every other value
# must be REFUSED (not silently answer matched:0 beside a nonzero by_type).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListTasksTaskTypeDomain:
    async def test_tsk_is_accepted_and_matches_the_seeded_task(self, db_session, two_tenant_service_setup):
        """QA's exact probe (U67-F1): task_type='TSK' used to be REFUSED as a
        reserved tag while it is the only value that can ever match a task."""
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", task_type="TSK")
        assert response["counts"]["matched"] >= 1
        assert response["count"] >= 1

    async def test_matched_agrees_with_by_type_for_tsk(self, db_session, two_tenant_service_setup):
        """The self-contradiction QA measured -- matched:0 beside a nonzero
        counts.by_type.TSK for an ACCEPTED task_type -- can no longer arise."""
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", task_type="TSK")
        assert response["counts"]["matched"] == response["counts"]["by_type"]["TSK"]

    async def test_real_taxonomy_abbreviation_is_refused_not_silently_empty(self, db_session, two_tenant_service_setup):
        """A real project-taxonomy abbreviation ('BE') structurally cannot
        match a task -- refuse it rather than answer matched:0 (U61
        precedent), the exact shape QA measured for all 11 accepted values."""
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        db_manager = two_tenant_service_setup["db_manager"]
        task_service_a = two_tenant_service_setup["task_service_a"]
        await _seed_be_taxonomy(db_session, tenant_a, db_manager)

        with pytest.raises(ValidationError, match="TSK"):
            await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", task_type="BE")

    async def test_typo_value_is_refused_the_same_way_as_a_real_type(self, db_session, two_tenant_service_setup):
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        with pytest.raises(ValidationError, match="bogus_type_be9470"):
            await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", task_type="bogus_type_be9470")

    async def test_lowercase_tsk_is_refused_case_sensitive(self, db_session, two_tenant_service_setup):
        """Taxonomy abbreviations are case-sensitive throughout this codebase
        (BE/FE/INF convention, TaxonomyService.validate's own docstring) --
        lowercase 'tsk' does not get a pass just because uppercase does."""
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        with pytest.raises(ValidationError, match="tsk"):
            await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", task_type="tsk")
