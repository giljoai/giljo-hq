# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services._mcp_wire_bounds import (
    MCP_LIST_CHAR_CEILING,
    TRANSPORT_ENVELOPE_ALLOWANCE,
    fit_rows_to_char_ceiling,
    wire_length,
)


def _row(n: int, pad: int = 0) -> dict:
    return {"id": f"row-{n:04d}", "name": f"project number {n}", "blob": "x" * pad}


class TestWireLength:
    def test_it_measures_the_compact_form_the_wire_actually_sends(self):
        import json

        payload = {"a": 1, "b": "x", "c": [1, 2, 3]}
        assert wire_length(payload) < len(json.dumps(payload)), (
            "the compact wire form must be shorter than json.dumps' spaced default"
        )
        assert wire_length({"a": 1}) == len('{"a":1}')

    def test_it_does_not_raise_on_values_json_cannot_encode(self):
        from datetime import UTC, datetime

        assert wire_length({"when": datetime(2026, 8, 18, tzinfo=UTC)}) > 0


class TestFitRowsToCharCeiling:
    def test_an_under_budget_list_is_returned_whole(self):
        rows = [_row(n) for n in range(5)]
        kept, dropped = fit_rows_to_char_ceiling(rows, envelope={"projects": []}, ceiling=10_000)
        assert kept == rows
        assert dropped == 0

    def test_it_drops_whole_rows_and_never_trims_fields(self):
        rows = [_row(n, pad=200) for n in range(40)]
        kept, dropped = fit_rows_to_char_ceiling(rows, envelope={"projects": []}, ceiling=3_000)

        assert 0 < len(kept) < len(rows), f"the ceiling should have bitten; kept {len(kept)} of {len(rows)}"
        assert dropped == len(rows) - len(kept)
        assert kept == rows[: len(kept)], "survivors must be the untouched HEAD of the input"
        for row in kept:
            assert set(row) == {"id", "name", "blob"}, f"a surviving row must be complete, got {sorted(row)!r}"

    def test_the_postcondition_holds_across_ceilings_with_the_envelope_charged(self):
        rows = [_row(n, pad=60) for n in range(60)]
        for ceiling in (600, 1_000, 2_500, 5_000, 12_000):
            envelope = {
                "projects": [],
                "count": 0,
                "truncated": True,
                "truncation": {"reason": "response_size", "ceiling": ceiling, "advice": "x" * 300},
            }
            kept, _dropped = fit_rows_to_char_ceiling(rows, envelope=envelope, ceiling=ceiling)
            delivered = dict(envelope)
            delivered["projects"] = kept
            assert wire_length(delivered) <= ceiling, (
                f"the ceiling must HOLD: {wire_length(delivered)} chars against {ceiling}, {len(kept)} rows kept"
            )

    def test_a_ceiling_smaller_than_the_envelope_drops_everything_rather_than_overshooting(self):
        rows = [_row(n) for n in range(5)]
        kept, dropped = fit_rows_to_char_ceiling(rows, envelope={"projects": [], "pad": "x" * 500}, ceiling=100)
        assert kept == []
        assert dropped == len(rows), "every row is accounted for even when none survives"

    def test_a_single_row_larger_than_the_whole_budget_yields_an_empty_page(self):
        kept, dropped = fit_rows_to_char_ceiling([_row(0, pad=5_000)], envelope={"projects": []}, ceiling=1_000)
        assert kept == []
        assert dropped == 1


class TestTheSharedConstants:
    def test_the_ceiling_is_the_value_both_lanes_measured(self):
        assert MCP_LIST_CHAR_CEILING == 48_000

    def test_the_transport_allowance_leaves_room_for_keys_added_after_the_service_returns(self):
        assert TRANSPORT_ENVELOPE_ALLOWANCE >= 64, (
            "the allowance must exceed the 64-char overshoot that the in-repo trimmer "
            "demonstrates is possible when metadata is written after the last size check"
        )
