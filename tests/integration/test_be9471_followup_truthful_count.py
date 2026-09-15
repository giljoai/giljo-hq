# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    completed = [
        _row(f"DOC completed target {n}", "completed", f"2026-01-{n:02d}", f"2026-02-{n:02d}") for n in range(1, 4)
    ]
    completed += [
        _row(f"DOC completed plain {n}", "completed", f"2026-01-{n:02d}", f"2026-02-{n:02d}") for n in range(4, 11)
    ]
    inactive = [_row("DOC-6167 inactive current", "inactive", "2026-07-03")]
    return await _seed_typed(db_manager, tenant_key, "DOC", completed + inactive)


class TestEmptyVariantSpeaksTheTruthfulCountNotByType:

    async def test_nonsense_query_gets_no_advice_not_a_false_eleven(self, mcp_client, db_manager):  # noqa: F811
        client, tenant_key = mcp_client
        await _seed_doc_board(db_manager, tenant_key)
        try:
            result = await _list_projects(client, project_type="DOC", query="zzzznotarealword", mode="triage", limit=5)
            assert not result.is_error, f"must not error: {_content_text(result)!r}"
            payload = _payload(result)
            assert payload["counts"]["matched"] == 0

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
            assert "11 " not in advice and "11 such project" not in advice, (
                f"advice must NOT quote the whole-board by_type figure: {advice!r}"
            )
        finally:
            await _purge(db_manager, tenant_key)


class TestPartialVariantArmsOnByTypeButSpeaksTheRelaxedCount:

    async def test_created_after_leaves_no_rest_advice_stays_silent(self, mcp_client, db_manager):  # noqa: F811
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

    async def test_query_only_fully_hidden_now_gets_advice(self, mcp_client, db_manager):  # noqa: F811
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

    async def test_partial_hide_query_only_no_project_type_stays_silent(self, mcp_client, db_manager):  # noqa: F811
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

    async def test_exact_alias_prefix_match_gets_no_false_rest_claim(self, mcp_client, db_manager):  # noqa: F811
        client, tenant_key = mcp_client
        await _seed_doc_board(db_manager, tenant_key)
        try:
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
