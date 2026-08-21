# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9471 follow-up -- ``counts.advice`` quotes the whole-board number, which is a LIE
whenever a second filter narrows the result (QA units U79/U80/U81).

The shipped BE-9471 advice compares ``matched`` against ``counts.by_type[TYPE]`` -- a
whole-board tally, correct ONLY when ``project_type`` is the sole narrowing predicate.
QA reproduced this live and measured false remedies:

- ``project_type='DOC'+query='zzzznotarealword'`` -> advice claims 11 exist board-wide;
  following the remedy (``include_completed=true``) returns 0 (U80-A).
- ``project_type='DOC'+query='documentation'`` -> advice claims 11; remedy returns 3
  (U80-B).
- ``project_type='DOC'+created_after=...`` -> advice claims "the rest" are hidden;
  remedy returns the SAME single row, zero additional (U80-C).
- ``project_type='DOC'+taxonomy_alias_prefix='DOC-6167'`` (an EXACT single-alias
  lookup) -> advice tells the agent its complete, correct answer is incomplete (U81-B).
- A ``query``-only call with NO ``project_type`` and a fully lifecycle-hidden match
  (0 shown, 33 exist) gets NO advice at all -- the trigger required ``project_type``
  (U79-A).

FAIL-FIRST: every assertion below that reads a NUMBER out of ``counts.advice`` fails
against the pre-follow-up shape, because that code always spoke ``counts.by_type`` --
the whole-board figure -- regardless of any other filter in the same call.

Transport: the real ``@mcp.tool`` path via ``create_connected_server_and_client_session``
against the real Postgres test DB, reusing the BE-9468/BE-9471 fixtures so the transport
and seeding are byte-identical to the modules those QA units already trust.

Edition Scope: Both.
"""

from __future__ import annotations

import pytest

from tests.integration.test_be9468_list_projects_read_layer import (
    _content_text,
    _list_projects,
    _payload,
    mcp_client,  # noqa: F401 -- re-exported fixture, pytest discovers it by name
)
from tests.integration.test_be9471_project_service_lifecycle_hidden_advice import (
    _purge,
    _row,
    _seed_typed,
)


pytestmark = pytest.mark.asyncio


async def _seed_doc_board(db_manager, tenant_key: str) -> str:
    """QA's U80/U81 board shape: 11 DOC projects, 10 completed + 1 inactive.

    3 of the 10 completed rows carry ``target`` in their name (the co-filter QA used
    to prove the over-claim); the other 7 and the visible inactive row do not. All 10
    completed rows are created BEFORE 2026-06-01; the inactive row is created AFTER
    it -- mirrors U80-C's ``created_after`` case exactly (the "rest" that does not
    exist).
    """
    completed = [
        _row(f"DOC completed target {n}", "completed", f"2026-01-{n:02d}", f"2026-02-{n:02d}") for n in range(1, 4)
    ]
    completed += [
        _row(f"DOC completed plain {n}", "completed", f"2026-01-{n:02d}", f"2026-02-{n:02d}") for n in range(4, 11)
    ]
    inactive = [_row("DOC-6167 inactive current", "inactive", "2026-07-03")]
    return await _seed_typed(db_manager, tenant_key, "DOC", completed + inactive)


class TestEmptyVariantSpeaksTheTruthfulCountNotByType:
    """U80-A / U80-B -- matched:0, a co-filter present. The old code claimed 11 either way."""

    async def test_nonsense_query_gets_no_advice_not_a_false_eleven(self, mcp_client, db_manager):  # noqa: F811
        """U80-A verbatim: query matches nothing anywhere. Truth is 0 -- advice must be silent."""
        client, tenant_key = mcp_client
        await _seed_doc_board(db_manager, tenant_key)
        try:
            result = await _list_projects(client, project_type="DOC", query="zzzznotarealword", mode="triage", limit=5)
            assert not result.is_error, f"must not error: {_content_text(result)!r}"
            payload = _payload(result)
            assert payload["counts"]["matched"] == 0

            # Ground truth, measured the same way U80-A did: follow the remedy literally.
            remedy = await _list_projects(
                client,
                project_type="DOC",
                query="zzzznotarealword",
                mode="triage",
                limit=5,
                include_completed=True,
            )
            assert _payload(remedy)["counts"]["matched"] == 0, "remedy must confirm truly nothing hides here"

            assert "advice" not in payload["counts"], (
                "advice must stay silent when the truthful hidden count is 0 -- "
                f"got: {payload['counts'].get('advice')!r}"
            )
        finally:
            await _purge(db_manager, tenant_key)

    async def test_real_query_gets_the_true_three_not_the_whole_board_eleven(self, mcp_client, db_manager):  # noqa: F811
        """U80-B verbatim shape: query narrows 11 -> 3. Advice must say 3, never 11."""
        client, tenant_key = mcp_client
        await _seed_doc_board(db_manager, tenant_key)
        try:
            result = await _list_projects(client, project_type="DOC", query="target", mode="triage", limit=5)
            payload = _payload(result)
            assert payload["counts"]["matched"] == 0
            assert payload["counts"]["by_type"].get("DOC") == 11, "the (irrelevant) whole-board tally is still 11"

            remedy = await _list_projects(
                client, project_type="DOC", query="target", mode="triage", limit=5, include_completed=True
            )
            remedy_matched = _payload(remedy)["counts"]["matched"]
            assert remedy_matched == 3, f"ground truth: exactly 3 DOC rows carry 'target', got {remedy_matched}"

            advice = payload["counts"].get("advice")
            assert advice is not None, "a real hidden population under this filter set must get advice"
            assert "3" in advice, f"advice must name the TRUE count (3), not by_type: {advice!r}"
            # The over-claimed whole-board figure must not appear as the promised count.
            assert "11 " not in advice and "11 such project" not in advice, (
                f"advice must NOT quote the whole-board by_type figure: {advice!r}"
            )
        finally:
            await _purge(db_manager, tenant_key)


class TestPartialVariantArmsOnByTypeButSpeaksTheRelaxedCount:
    """U80-C / U81-B -- matched>0, by_type over-promises "the rest". Truth is zero additional."""

    async def test_created_after_leaves_no_rest_advice_stays_silent(self, mcp_client, db_manager):  # noqa: F811
        """U80-C verbatim: created_after narrows to the SAME 1 row already shown. No 'rest' exists."""
        client, tenant_key = mcp_client
        await _seed_doc_board(db_manager, tenant_key)
        try:
            result = await _list_projects(
                client,
                project_type="DOC",
                created_after="2026-06-01T00:00:00Z",
                mode="triage",
                limit=5,
            )
            payload = _payload(result)
            assert payload["counts"]["matched"] == 1
            assert payload["counts"]["by_type"].get("DOC") == 11, "free pre-trigger arms on the raw by_type gap"

            remedy = await _list_projects(
                client,
                project_type="DOC",
                created_after="2026-06-01T00:00:00Z",
                mode="triage",
                limit=5,
                include_completed=True,
            )
            assert _payload(remedy)["counts"]["matched"] == 1, (
                "ground truth: zero additional rows behind the date bound"
            )

            assert "advice" not in payload["counts"], (
                "the free by_type check may ARM the relaxed count, but a zero truthful delta "
                f"must stay silent, not repeat the false 'the rest' claim: {payload['counts'].get('advice')!r}"
            )
        finally:
            await _purge(db_manager, tenant_key)


class TestQueryOnlyEmptyGetsAdviceNow:
    """U79-A -- the silent half of the same bug: no project_type meant no trigger at all."""

    async def test_query_only_fully_hidden_now_gets_advice(self, mcp_client, db_manager):  # noqa: F811
        """A query with NO project_type, entirely lifecycle-hidden, must now speak up."""
        client, tenant_key = mcp_client
        await _seed_doc_board(db_manager, tenant_key)
        try:
            result = await _list_projects(client, query="target", mode="triage", limit=5)
            payload = _payload(result)
            assert payload["counts"]["matched"] == 0

            remedy = await _list_projects(client, query="target", mode="triage", limit=5, include_completed=True)
            remedy_matched = _payload(remedy)["counts"]["matched"]
            assert remedy_matched == 3

            advice = payload["counts"].get("advice")
            assert advice is not None, "U79's gap: query alone must now trigger the advice when it hides rows"
            assert "3" in advice
            assert "include_completed" in advice
        finally:
            await _purge(db_manager, tenant_key)


class TestPartialWithoutProjectTypeStaysSilentByDesign:
    """Item 3's accepted limit: partial-hide + no project_type never pays the COUNT."""

    async def test_partial_hide_query_only_no_project_type_stays_silent(self, mcp_client, db_manager):  # noqa: F811
        """query='DOC' matches the visible row AND ten hidden ones. No project_type -> no advice."""
        client, tenant_key = mcp_client
        await _seed_doc_board(db_manager, tenant_key)
        try:
            result = await _list_projects(client, query="DOC", mode="triage", limit=5)
            payload = _payload(result)
            assert payload["counts"]["matched"] == 1, "the one visible inactive row matches 'DOC' too"

            remedy = await _list_projects(client, query="DOC", mode="triage", limit=20, include_completed=True)
            assert _payload(remedy)["counts"]["matched"] == 11, "a real hidden population exists behind this query"

            assert "advice" not in payload["counts"], (
                "partial-hide with no project_type is the documented, deliberate silent gap -- "
                f"got: {payload['counts'].get('advice')!r}"
            )
        finally:
            await _purge(db_manager, tenant_key)


class TestTaxonomyAliasPrefixCoFilter:
    """U81-B -- the sharpest instance: an exact single-alias lookup told an agent its
    complete answer was incomplete. Partial-variant path (matched:1): the free
    by_type-vs-matched pre-check arms (11 > 1), but the truthful relaxed count under
    this exact alias prefix is also 1 -- there is no "rest" -- so advice must stay
    silent."""

    async def test_exact_alias_prefix_match_gets_no_false_rest_claim(self, mcp_client, db_manager):  # noqa: F811
        client, tenant_key = mcp_client
        await _seed_doc_board(db_manager, tenant_key)
        try:
            # The seeded rows get taxonomy_alias assigned by series_number at creation
            # time (DOC-0001..DOC-0011); the 11th (index 11) is the visible inactive row.
            result = await _list_projects(
                client, project_type="DOC", taxonomy_alias_prefix="DOC-0011", mode="triage", limit=5
            )
            payload = _payload(result)
            assert payload["counts"]["matched"] == 1, "the exact-alias row is the visible inactive one"
            assert payload["counts"]["by_type"].get("DOC") == 11, "free pre-trigger arms on the raw by_type gap"

            remedy = await _list_projects(
                client,
                project_type="DOC",
                taxonomy_alias_prefix="DOC-0011",
                mode="triage",
                limit=5,
                include_completed=True,
            )
            remedy_matched = _payload(remedy)["counts"]["matched"]
            assert remedy_matched == 1, (
                f"ground truth: an exact single-alias lookup has nothing left to hide, got {remedy_matched}"
            )

            assert "advice" not in payload["counts"], (
                "a truthful delta of 0 must stay silent even though by_type=11 would have armed the "
                f"old free check: {payload['counts'].get('advice')!r}"
            )
        finally:
            await _purge(db_manager, tenant_key)
