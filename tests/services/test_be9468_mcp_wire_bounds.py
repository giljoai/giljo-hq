# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9468 -- the shared MCP wire-bound helpers, tested as a contract between two services.

``services/_mcp_wire_bounds`` is used by BOTH ``list_tasks`` and ``list_projects``. It
was written for tasks first and extracted when projects needed the identical rule --
importing it across sibling domain services would have made ``task_service`` a runtime
dependency of ``project_service``, through a private module, for a helper that has
nothing to do with tasks.

**A shared helper needs its own tests, not only its callers'.** Each caller exercises the
paths it happens to hit; the postcondition below is a property of the helper, and if it
is only ever asserted through two consumers then neither is testing the contract -- they
are testing their own use of it.

The load-bearing property is the POSTCONDITION: the response the client receives lands
under the ceiling, not approximately under it. The in-repo
``tools/context_tools/_response_ceiling`` writes its truncation metadata after its last
size check and overshoots its own ceiling by exactly 64 chars while reporting success.
**A bound that does not hold is worse than no bound, because it reports success.**

Parallel-safe by construction: pure functions, no module-level mutable state, no I/O.

Edition Scope: Both.
"""

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
        """``json.dumps`` defaults count separator whitespace that never crosses the wire.

        Measuring with the wrong ruler inflates the number, which lets a size check pass
        on bytes that do not exist -- and the error is in the dangerous direction only
        when the two rulers disagree about which side has slack.
        """
        import json

        payload = {"a": 1, "b": "x", "c": [1, 2, 3]}
        assert wire_length(payload) < len(json.dumps(payload)), (
            "the compact wire form must be shorter than json.dumps' spaced default"
        )
        assert wire_length({"a": 1}) == len('{"a":1}')

    def test_it_does_not_raise_on_values_json_cannot_encode(self):
        """``fallback=str`` is what the real serializer uses; a size check must never be
        the thing that breaks a response."""
        from datetime import UTC, datetime

        assert wire_length({"when": datetime(2026, 8, 18, tzinfo=UTC)}) > 0


class TestFitRowsToCharCeiling:
    def test_an_under_budget_list_is_returned_whole(self):
        rows = [_row(n) for n in range(5)]
        kept, dropped = fit_rows_to_char_ceiling(rows, envelope={"projects": []}, ceiling=10_000)
        assert kept == rows
        assert dropped == 0

    def test_it_drops_whole_rows_and_never_trims_fields(self):
        """THE design distinction, and the reason the in-repo trimmer was refuted.

        That trimmer strips attributes off every row until the total fits. Its protected
        set covers the display label and NOT the identifier, so a list caller is handed
        rows it can read and cannot act on. **A list tool needs fewer rows, not thinner
        ones -- a half-row is not a usable answer.** Every row that survives here must be
        byte-identical to the one that went in.
        """
        rows = [_row(n, pad=200) for n in range(40)]
        kept, dropped = fit_rows_to_char_ceiling(rows, envelope={"projects": []}, ceiling=3_000)

        assert 0 < len(kept) < len(rows), f"the ceiling should have bitten; kept {len(kept)} of {len(rows)}"
        assert dropped == len(rows) - len(kept)
        assert kept == rows[: len(kept)], "survivors must be the untouched HEAD of the input"
        for row in kept:
            assert set(row) == {"id", "name", "blob"}, f"a surviving row must be complete, got {sorted(row)!r}"

    def test_the_postcondition_holds_across_ceilings_with_the_envelope_charged(self):
        """The property the whole helper exists to provide, checked at several values.

        A postcondition that holds at one ceiling and not another is not a
        postcondition. The envelope is charged up front INCLUDING the truncation block a
        cut will add, because measuring the budget and only then adding metadata is
        exactly how a ceiling silently stops holding.
        """
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
        """The degenerate case must fail CLOSED, not ship a breach.

        If the envelope alone already exceeds the budget there is no honest number of
        rows to return, and returning one anyway would break the postcondition the
        caller is relying on. An empty page plus a truthful signal beats a bound that
        quietly stopped applying.
        """
        rows = [_row(n) for n in range(5)]
        kept, dropped = fit_rows_to_char_ceiling(rows, envelope={"projects": [], "pad": "x" * 500}, ceiling=100)
        assert kept == []
        assert dropped == len(rows), "every row is accounted for even when none survives"

    def test_a_single_row_larger_than_the_whole_budget_yields_an_empty_page(self):
        """Reachable on the project list, where `mission` is capped at 100,000 chars and
        ships in full at depth >= 1. The caller's remedy is a leaner projection, which is
        what the response advises."""
        kept, dropped = fit_rows_to_char_ceiling([_row(0, pad=5_000)], envelope={"projects": []}, ceiling=1_000)
        assert kept == []
        assert dropped == 1


class TestTheSharedConstants:
    def test_the_ceiling_is_the_value_both_lanes_measured(self):
        """Pinned so it cannot drift without the reasoning that chose it.

        48,000 chars is MEASURED margin below a bisected client-refusal bracket
        (49,595-50,060 chars, live client, 2026-08-19) -- not a token-budget estimate.
        It supersedes two prior, weaker rulers in order: 80,000 chars (~15% of a 200k
        context window) and 60,000 chars (an inferred ~25,000-token client cap). See the
        module for the full history of why each one moved.
        """
        assert MCP_LIST_CHAR_CEILING == 48_000

    def test_the_transport_allowance_leaves_room_for_keys_added_after_the_service_returns(self):
        """``_meta`` (~37 chars today) is appended by the transport AFTER a service
        returns, so a ceiling that did not reserve for it would be breached by the very
        act of delivery. Measured slack on real responses with the counts block present
        runs 240-377 chars against this 256-char reservation."""
        assert TRANSPORT_ENVELOPE_ALLOWANCE >= 64, (
            "the allowance must exceed the 64-char overshoot that the in-repo trimmer "
            "demonstrates is possible when metadata is written after the last size check"
        )
