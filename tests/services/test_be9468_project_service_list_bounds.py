# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.project_service._mcp_list_bounds import (
    LIST_PROJECTS_LIMIT_DEFAULT,
    LIST_PROJECTS_LIMIT_MAX,
    apply_row_limit,
    build_counts_block,
    build_list_response,
    resolve_row_limit,
    resolve_search_query,
)


class TestResolveRowLimit:
    def test_an_absent_limit_takes_the_default(self):
        assert resolve_row_limit(None) == LIST_PROJECTS_LIMIT_DEFAULT

    def test_an_over_max_limit_is_clamped_not_rejected(self):
        assert resolve_row_limit(10_000) == LIST_PROJECTS_LIMIT_MAX

    def test_a_zero_or_negative_limit_floors_at_one(self):
        assert resolve_row_limit(0) == 1
        assert resolve_row_limit(-5) == 1

    def test_a_bool_limit_is_rejected(self):
        with pytest.raises(ValidationError):
            resolve_row_limit(True)

    def test_a_non_integer_limit_is_rejected_at_the_boundary(self):
        with pytest.raises(ValidationError):
            resolve_row_limit("50")


class TestResolveSearchQuery:
    def test_an_absent_query_is_none(self):
        assert resolve_search_query(None) is None

    def test_a_whitespace_only_query_is_treated_as_absent(self):
        assert resolve_search_query("   ") is None
        assert resolve_search_query("") is None

    def test_a_query_is_trimmed(self):
        assert resolve_search_query("  oauth  ") == "oauth"

    def test_an_over_length_query_is_rejected(self):
        with pytest.raises(ValidationError):
            resolve_search_query("x" * 201)

    def test_a_non_string_query_is_rejected(self):
        with pytest.raises(ValidationError):
            resolve_search_query(42)


class TestApplyRowLimit:
    def test_a_non_binding_limit_returns_every_row_untruncated(self):
        rows = ["a", "b", "c"]
        kept, matched, truncated = apply_row_limit(rows, 10)
        assert kept == rows
        assert matched == 3
        assert truncated is False

    def test_a_row_count_exactly_on_the_limit_is_not_truncated(self):
        kept, matched, truncated = apply_row_limit(["a", "b", "c"], 3)
        assert kept == ["a", "b", "c"]
        assert matched == 3
        assert truncated is False

    def test_a_binding_limit_reports_the_true_matched_count(self):
        kept, matched, truncated = apply_row_limit(list(range(100)), 10)
        assert len(kept) == 10
        assert matched == 100, "matched must be the pre-cut total, not the returned length"
        assert truncated is True

    def test_the_cut_takes_the_head_and_never_re_sorts(self):
        rows = ["unfinished-1", "unfinished-2", "newest-completion", "oldest-completion"]
        kept, _matched, _truncated = apply_row_limit(rows, 3)
        assert kept == ["unfinished-1", "unfinished-2", "newest-completion"]
        assert "oldest-completion" not in kept


def _dt(day: str):
    from datetime import datetime

    return datetime.fromisoformat(f"{day}T12:00:00+00:00")


def _grouped(rows):
    return [
        (status, abbr, _dt(c1), _dt(c2), _dt(d1) if d1 else None, _dt(d2) if d2 else None, n)
        for status, abbr, c1, c2, d1, d2, n in rows
    ]


class TestBuildCountsBlock:

    def test_totals_sum_across_every_group(self):
        counts = build_counts_block(
            _grouped(
                [
                    ("completed", "BE", "2026-01-01", "2026-06-01", "2026-02-01", "2026-07-01", 1069),
                    ("inactive", "BE", "2026-07-01", "2026-08-01", None, None, 7),
                    ("inactive", "FE", "2026-07-02", "2026-08-02", None, None, 5),
                ]
            ),
            returned=2,
            matched=12,
        )
        assert counts["total"] == 1081
        assert counts["by_status"]["completed"] == 1069
        assert counts["by_status"]["inactive"] == 12, "a status split across types must sum"
        assert counts["by_type"] == {"BE": 1076, "FE": 5}

    def test_by_status_carries_explicit_zeros_for_the_whole_closed_enum(self):
        counts = build_counts_block(
            _grouped([("inactive", "BE", "2026-07-01", "2026-08-01", None, None, 7)]),
            returned=7,
            matched=7,
        )
        assert set(counts["by_status"]) == {s.value for s in ProjectStatus}, (
            f"every status in the closed enum must appear, got {sorted(counts['by_status'])!r}"
        )
        assert counts["by_status"]["active"] == 0, "a status with no rows must read as an explicit zero"

    def test_by_type_omits_zeros_because_the_vocabulary_is_open(self):
        counts = build_counts_block(
            _grouped([("inactive", "BE", "2026-07-01", "2026-08-01", None, None, 7)]),
            returned=7,
            matched=7,
        )
        assert counts["by_type"] == {"BE": 7}

    def test_matched_is_omitted_when_it_cannot_be_computed_truthfully(self):
        counts = build_counts_block(
            _grouped([("completed", "BE", "2026-01-01", "2026-06-01", "2026-02-01", "2026-07-01", 9000)]),
            returned=50,
            matched=None,
        )
        assert "matched" not in counts, f"a number we cannot compute truthfully must be absent, got {counts!r}"
        assert counts["total"] == 9000, "the board-wide total is still exact and still reported"

    def test_the_date_span_reads_null_rather_than_missing_on_a_board_with_no_completions(self):
        counts = build_counts_block(
            _grouped([("inactive", "BE", "2026-07-01", "2026-08-01", None, None, 7)]),
            returned=7,
            matched=7,
        )
        span = counts["date_span"]
        assert span["created_first"].startswith("2026-07-01")
        assert span["created_last"].startswith("2026-08-01")
        assert span["completed_first"] is None, f"got {span!r}"
        assert span["completed_last"] is None, f"got {span!r}"

    def test_an_empty_board_still_produces_a_readable_block(self):
        counts = build_counts_block([], returned=0, matched=0)
        assert counts["total"] == 0
        assert counts["by_type"] == {}
        assert all(v == 0 for v in counts["by_status"].values())
        assert counts["date_span"]["created_first"] is None

    def test_scope_names_the_population_the_total_describes(self):
        assert build_counts_block([], returned=0, matched=0)["scope"] == "product"


def _response(**overrides):
    kwargs = {
        "projects_out": [{"project_id": "p1"}],
        "counts": {"scope": "product", "total": 1, "returned": 1},
        "product_id": "prod-1",
        "depth": 0,
        "mode": None,
        "ceiling": 2500,
        "ceiling_truncated": False,
        "ceiling_rows_fetched": 0,
        "limit_truncated": False,
        "effective_limit": 50,
        "completion_oriented": False,
    }
    kwargs.update(overrides)
    return build_list_response(**kwargs)


class TestBuildListResponse:
    def test_an_untruncated_response_reports_false_and_carries_no_block(self):
        payload = _response()
        assert payload["truncated"] is False
        assert "truncation" not in payload

    def test_a_limit_cut_names_the_limit_as_the_reason(self):
        payload = _response(limit_truncated=True, effective_limit=3)
        assert payload["truncated"] is True
        assert payload["truncation"]["reason"] == "limit"
        assert payload["truncation"]["ceiling"] == 3

    def test_the_truncation_block_reuses_the_shipped_key_set_exactly(self):
        for kwargs in ({"limit_truncated": True}, {"ceiling_truncated": True}):
            note = _response(**kwargs)["truncation"]
            assert set(note) == {"reason", "ceiling", "rows_fetched", "dropped", "advice"}, (
                f"unexpected truncation keys for {kwargs}: {sorted(note)!r}"
            )

    def test_when_both_bounds_bind_the_defensive_ceiling_wins(self):
        payload = _response(ceiling_truncated=True, ceiling_rows_fetched=2500, limit_truncated=True)
        assert payload["truncation"]["reason"] == "defensive_ceiling"
        assert payload["truncation"]["ceiling"] == 2500
        assert "raising limit will NOT complete it" in payload["truncation"]["advice"]

    def test_the_limit_advice_points_at_a_remedy_that_actually_works(self):
        advice = _response(limit_truncated=True)["truncation"]["advice"]
        assert "raising limit WILL return more" in advice

    def test_the_ceiling_is_reported_from_the_argument_not_a_module_global(self):
        payload = _response(ceiling=4, ceiling_truncated=True, ceiling_rows_fetched=4)
        assert payload["truncation"]["ceiling"] == 4

    def test_mode_is_echoed_only_when_it_was_passed(self):
        assert "mode" not in _response()
        assert _response(mode="triage")["mode"] == "triage"

    def test_counts_returned_is_assigned_from_the_same_value_as_count(self):
        payload = _response(
            projects_out=[{"project_id": "p1"}, {"project_id": "p2"}, {"project_id": "p3"}],
            counts={"scope": "product", "total": 99, "returned": 12345},
        )
        assert payload["count"] == 3
        assert payload["counts"]["returned"] == 3, (
            "counts.returned must be assigned from the same value as count, not carried in"
        )
