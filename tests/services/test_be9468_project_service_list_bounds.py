# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9468 -- unit coverage for the project_service list-bounds helpers.

``_mcp_list_bounds`` holds the caller-facing bounds for the agent-facing project list:
validation of the agent-supplied ``query`` and ``limit``, the row cut, and the response
assembly that decides WHICH bound a truncated response names. Every function here is
pure -- no database, no session, no ``self`` -- so the edge cases that actually bite are
cheap to pin directly, without a transport or a seeded tenant.

The boundary behaviour of these bounds is covered end-to-end over the real MCP transport
in ``tests/integration/test_be9468_list_projects_read_layer.py``. This module covers the
cases that integration test cannot reach economically: type traps, clamping arithmetic,
and the both-bounds-bind precedence rule.

Parallel-safe by construction: pure functions, no module-level mutable state, no
ordering dependencies, no I/O.

Edition Scope: Both.
"""

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
        """``search_memory``'s contract: clamp, never refuse.

        Refusing would break the "ask for everything" call the operator explicitly wants
        to keep working. Clamping keeps it working AND lets the response say it was
        bounded, which is the whole design.
        """
        assert resolve_row_limit(10_000) == LIST_PROJECTS_LIMIT_MAX

    def test_a_zero_or_negative_limit_floors_at_one(self):
        assert resolve_row_limit(0) == 1
        assert resolve_row_limit(-5) == 1

    def test_a_bool_limit_is_rejected(self):
        """THE type trap. ``bool`` is an ``int`` subclass in Python.

        Without an explicit check, ``limit=True`` passes ``isinstance(x, int)`` and
        resolves to a silent limit of 1 -- a caller would get one row back and no
        indication that its argument was nonsense. A silently wrong bound is exactly the
        defect class this surface is being corrected for.
        """
        with pytest.raises(ValidationError):
            resolve_row_limit(True)

    def test_a_non_integer_limit_is_rejected_at_the_boundary(self):
        """A 422 from the boundary, not a 500 from a DB constraint downstream."""
        with pytest.raises(ValidationError):
            resolve_row_limit("50")


class TestResolveSearchQuery:
    def test_an_absent_query_is_none(self):
        assert resolve_search_query(None) is None

    def test_a_whitespace_only_query_is_treated_as_absent(self):
        """THE matcher trap, and the reason this normalizes rather than passes through.

        An empty search term builds a ``%%`` LIKE pattern that matches every row, so a
        caller that passed whitespace by accident would silently receive the entire
        board -- the exact unbounded read this project exists to prevent.
        """
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
        """Exactness is the point of cutting here rather than in SQL.

        The defensive ceiling has to report conservatively (a count landing exactly on it
        cannot be distinguished from an over-run without a second query). Cutting after
        the filters means the true matched count is known, so a list of exactly ``limit``
        rows is complete and says so.
        """
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
        """The museum-rule guard on BE-9455 Symptom A.

        Rows arrive already ordered ``completed_at DESC NULLS FIRST`` on a
        completion-oriented read, which is what makes unfinished work un-droppable and
        confines a cut to the oldest completions. A head slice preserves that; any
        sorting here would re-open the wound BE-9455 closed, at a smaller number. This
        fails if the implementation ever starts ordering its own input.
        """
        rows = ["unfinished-1", "unfinished-2", "newest-completion", "oldest-completion"]
        kept, _matched, _truncated = apply_row_limit(rows, 3)
        assert kept == ["unfinished-1", "unfinished-2", "newest-completion"]
        assert "oldest-completion" not in kept


def _dt(day: str):
    from datetime import datetime

    return datetime.fromisoformat(f"{day}T12:00:00+00:00")


def _grouped(rows):
    """Shape rows the way ``ProjectRepository.board_counts`` returns them."""
    return [
        (status, abbr, _dt(c1), _dt(c2), _dt(d1) if d1 else None, _dt(d2) if d2 else None, n)
        for status, abbr, c1, c2, d1, d2, n in rows
    ]


class TestBuildCountsBlock:
    """The keystone block: what the caller learns about the board BEFORE it asks again."""

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
        """Absence must never be ambiguous on a vocabulary the caller can enumerate.

        Measured on the operator's real board, ``status='active'`` is 0. If zero-count
        statuses were omitted, an agent asking "is anything active?" could not tell
        "zero active" from "this server does not report that status" -- the exact
        absent-vs-false defect BE-9455 Symptom A fixed by making ``truncated`` always
        present rather than absent.
        """
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
        """The deliberate asymmetry with by_status, and why it is not a compromise.

        Taxonomy types are tenant-configured, so the caller cannot enumerate them and a
        missing key claims nothing. Emitting every configured type at zero would be
        noise, where the same treatment on the closed status enum would be ambiguity.
        """
        counts = build_counts_block(
            _grouped([("inactive", "BE", "2026-07-01", "2026-08-01", None, None, 7)]),
            returned=7,
            matched=7,
        )
        assert counts["by_type"] == {"BE": 7}

    def test_matched_is_omitted_when_it_cannot_be_computed_truthfully(self):
        """A missing number beats a confident wrong one.

        ``matched`` is derived after a fetch the defensive ceiling may already have
        bounded, so on a board over the ceiling it would report the ceiling rather than
        the truth -- understating, in the reassuring direction, on exactly the large
        boards this block exists to describe. The caller passes None in that case and
        the key must not appear at all; the response separately carries
        ``truncated: true`` with ``reason: "defensive_ceiling"``, which IS true.
        """
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
        """Without it, a bare total is ambiguous -- this list is product-scoped, not tenant-wide."""
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
        """The shipped BE-9455 contract, unchanged: the flag is ALWAYS present."""
        payload = _response()
        assert payload["truncated"] is False
        assert "truncation" not in payload

    def test_a_limit_cut_names_the_limit_as_the_reason(self):
        payload = _response(limit_truncated=True, effective_limit=3)
        assert payload["truncated"] is True
        assert payload["truncation"]["reason"] == "limit"
        assert payload["truncation"]["ceiling"] == 3

    def test_the_truncation_block_reuses_the_shipped_key_set_exactly(self):
        """Extend the vocabulary, never fork it.

        A second truncation shape would make one tool report two different structures
        depending on which bound happened to bind, and a caller that already understands
        the shipped block would silently fail to read the new one.
        """
        for kwargs in ({"limit_truncated": True}, {"ceiling_truncated": True}):
            note = _response(**kwargs)["truncation"]
            assert set(note) == {"reason", "ceiling", "rows_fetched", "dropped", "advice"}, (
                f"unexpected truncation keys for {kwargs}: {sorted(note)!r}"
            )

    def test_when_both_bounds_bind_the_defensive_ceiling_wins(self):
        """THE precedence rule, and the reason it is severity rather than order.

        A ``limit`` cut is the caller's own choice and is recoverable by asking for more.
        A ceiling cut means the underlying set was ITSELF truncated, so no value of
        ``limit`` will ever return a complete answer. Reporting the recoverable reason
        while the unrecoverable one is also true would send the caller to a remedy that
        cannot work -- a fresh instance of the silent-wrong-signal defect being fixed.
        """
        payload = _response(ceiling_truncated=True, ceiling_rows_fetched=2500, limit_truncated=True)
        assert payload["truncation"]["reason"] == "defensive_ceiling"
        assert payload["truncation"]["ceiling"] == 2500
        assert "raising limit will NOT complete it" in payload["truncation"]["advice"]

    def test_the_limit_advice_points_at_a_remedy_that_actually_works(self):
        """The mirror of the above: a recoverable cut must not tell the caller to give up."""
        advice = _response(limit_truncated=True)["truncation"]["advice"]
        assert "raising limit WILL return more" in advice

    def test_the_ceiling_is_reported_from_the_argument_not_a_module_global(self):
        """Why ``ceiling`` is an explicit parameter rather than a global read.

        BE-9455's regression suite reaches the defensive ceiling by monkeypatching the
        adapter module's constant. Had this helper read a global of its own after moving
        modules, it would have reported an unpatched value while the fetch used a patched
        one -- a suite staying green while asserting a ceiling the code never used. Taking
        it as an argument makes that class of drift impossible.
        """
        payload = _response(ceiling=4, ceiling_truncated=True, ceiling_rows_fetched=4)
        assert payload["truncation"]["ceiling"] == 4

    def test_mode_is_echoed_only_when_it_was_passed(self):
        assert "mode" not in _response()
        assert _response(mode="triage")["mode"] == "triage"

    def test_counts_returned_is_assigned_from_the_same_value_as_count(self):
        """One number, one place. Never two independent len() calls.

        ``count`` and ``counts.returned`` mean the same thing by construction, so the
        only way they can ever disagree is if they are computed separately at different
        points in the pipeline -- which is precisely how a redundant field drifts from
        its twin. This pins that they are assigned, not recomputed: the block arrives
        carrying a deliberately WRONG ``returned`` and the assembler must overwrite it.
        """
        payload = _response(
            projects_out=[{"project_id": "p1"}, {"project_id": "p2"}, {"project_id": "p3"}],
            counts={"scope": "product", "total": 99, "returned": 12345},
        )
        assert payload["count"] == 3
        assert payload["counts"]["returned"] == 3, (
            "counts.returned must be assigned from the same value as count, not carried in"
        )
