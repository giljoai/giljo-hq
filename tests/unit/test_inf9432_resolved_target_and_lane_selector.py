# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9432 — the safety banner must name the RESOLVED database, and lane selectors
must carry the clone slot.

The incident
============
``tests/pytest_postgresql_plugin.py`` printed ``Target database:`` by interpolating
the module constant ``TEST_DB_NAME``. It therefore printed ``giljo_mcp_test`` on
every run of every tree. Measured before the fix, three runs whose real targets
were ``giljo_mcp_test2`` (a pinned clone), ``giljo_mcp_test`` (bare pytest) and
``giljo_test`` (CI's base) produced **byte-identical banner text**. The line was
not occasionally stale; it could only ever be right by coincidence on the
unnumbered default.

The cost was not the missing information — it was the *false* information. A lane
that pinned its base correctly read the banner, saw the shared base named, and
concluded the pin had not taken. The surrounding sprint's standing rule was
therefore "verify the target in ``pg_database``, never from the banner": every
lane was told to route around the instrument. An instrument nobody may believe
should be deleted or made true.

The root defect, which both halves of this file test
====================================================
On the shared unnumbered base, **"my databases" and "everyone's databases" are the
same string**, so lane identity is unrepresentable. A banner cannot name a lane it
cannot distinguish, and a ``LIKE`` selector cannot exclude one. That is why the
fix needed a SECOND derivation (``clone_dir_slot``, off the checkout directory)
beside the existing one (``clone_slot``, off the pinned base): a single derivation
cannot disagree with itself, which is exactly why nothing could detect a numbered
clone running on the shared base.

Parallel-safe: pure derivation and banner formatting, monkeypatched env only. No
database is contacted, created or dropped.
"""

from __future__ import annotations

import re

import pytest

from tests.helpers.test_db_helper import clone_dir_slot, clone_slot, lane_scratch_db_selector
from tests.pytest_postgresql_plugin import (
    SHARED_BASE_OVERRIDE_ENV_VAR,
    TEST_DB_NAME,
    _banner_lines,
    _shared_base_verdict,
    _xdist_active,
    resolved_target_database,
)


def _as_lane(monkeypatch: pytest.MonkeyPatch, base: str, worker: str | None = None) -> None:
    """Put this process in the lane whose pinned test-DB base is ``base``.

    Same helper shape as ``test_inf9387_scratch_db_clone_isolation`` — the local
    CI-faithful runner pins the clone-derived base by exporting ``DATABASE_URL``,
    so setting that variable IS how a lane identifies itself. Every case sets it
    explicitly rather than inheriting whichever lane runs this test.

    ``worker`` pins the xdist identity too, and that is NOT optional hygiene — it
    is a bug this helper had. ``resolve_test_db_name()`` appends ``_gwN`` from the
    ambient ``PYTEST_XDIST_WORKER``, so a case that set only ``DATABASE_URL``
    resolved to ``giljo_mcp_test2`` when run serially and ``giljo_mcp_test2_gw3``
    under ``-n 6``. These tests passed alone and failed in the CI-faithful sweep.
    Reading ambient process-global state is the same defect class as writing it:
    the INF-9432 guard catches the writes, and nothing catches the reads, so a test
    that depends on an env var must pin it in BOTH directions.
    """
    monkeypatch.setenv("DATABASE_URL", f"postgresql://postgres:pw@localhost:5432/{base}")
    if worker is None:
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    else:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)


def _target_row(lines: list[str]) -> str:
    """The database name the banner actually printed, read back out of the box."""
    row = next(line for line in lines if "Target database:" in line)
    return row.split("Target database:", 1)[1].strip().rstrip("║").strip()


# ---------------------------------------------------------------------------
# THE REGRESSION. Each case is RED against the constant-interpolating banner,
# which printed "giljo_mcp_test" for every one of them.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "base",
    [
        pytest.param("giljo_mcp_test2", id="pinned-clone-CI2"),
        pytest.param("giljo_mcp_test6", id="pinned-clone-CI6"),
        pytest.param("giljo_test", id="CI-base"),
        pytest.param("giljo_mcp_test", id="shared-default"),
    ],
)
@pytest.mark.parametrize(
    "worker",
    [pytest.param(None, id="serial"), pytest.param("gw3", id="xdist-worker")],
)
def test_banner_names_the_resolved_database(monkeypatch, base: str, worker: str | None):
    _as_lane(monkeypatch, base, worker)
    expected = base if worker is None else f"{base}_{worker}"

    target, source = resolved_target_database()
    lines = _banner_lines(True, "ok", target, source)

    assert target == expected
    assert _target_row(lines) == expected, (
        f"the banner printed {_target_row(lines)!r} while the run resolves to {expected!r}. "
        "A banner that names a database other than the one the suite connects to is "
        "counter-evidence: a correctly-pinned lane reads it and concludes its pin failed."
    )


def test_banner_reports_where_the_value_came_from(monkeypatch):
    """The half that would have settled it at a glance: pinned, or fallen back?

    ``giljo_mcp_test`` is BOTH the shared pool and the no-DATABASE_URL fallback, so
    the name alone cannot distinguish "I pinned the shared base" from "my pin never
    took". The source label is the only thing that can.
    """
    _as_lane(monkeypatch, "giljo_mcp_test2")  # worker=None: serial, so no _gwN suffix
    assert resolved_target_database()[1] == "DATABASE_URL"

    monkeypatch.delenv("DATABASE_URL", raising=False)
    target, source = resolved_target_database()
    assert target == TEST_DB_NAME
    assert "DEFAULT_CONFIG" in source and "unset" in source


def test_the_resolved_name_is_not_re_derived_from_database_url_here(monkeypatch):
    """It must come from the SAME call the suite's own connections go through.

    ``resolve_test_db_name`` applies the ``_gwN`` worker suffix. If the banner
    re-parsed ``DATABASE_URL`` itself it would print the controller's bare base
    inside a worker that is really connected to ``..._gw3`` — a second derivation
    free to drift from the first, i.e. the original bug with extra steps.
    """
    _as_lane(monkeypatch, "giljo_mcp_test2", worker="gw3")

    assert resolved_target_database()[0] == "giljo_mcp_test2_gw3"


# ---------------------------------------------------------------------------
# The refusal. Every clause of the condition is load-bearing, so each gets a case
# — including the ones that must NOT fire, which are what make it safe to ship.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("resolved", "xdist", "expected"),
    [
        pytest.param("giljo_mcp_test", True, "FAIL", id="THE-ACCIDENT-shared-base-under-xdist"),
        pytest.param("giljo_mcp_test_gw3", True, "FAIL", id="worker-suffix-stripped-before-judging"),
        pytest.param("giljo_mcp_test", False, None, id="serial-run-is-risky-not-corrupting"),
        pytest.param("giljo_mcp_test2", True, None, id="correctly-pinned-clone"),
        pytest.param("giljo_mcp_test2_gw0", True, None, id="correctly-pinned-clone-worker"),
        pytest.param("giljo_test", True, None, id="CI-BASE-CANNOT-TRIP-IT"),
        pytest.param("giljo_test_gw0", True, None, id="CI-worker-cannot-trip-it"),
    ],
)
def test_the_refusal_fires_on_exactly_one_arrangement(monkeypatch, resolved: str, xdist: bool, expected):
    """The truth table, in a numbered clone (which this tree is).

    ``giljo_test`` is the row that matters most for shipping: **CI's base is
    ``giljo_test``** — all four jobs in ``.github/workflows/ci.yml`` set
    ``…@postgres:5432/giljo_test`` — so CI is outside this gate by construction
    rather than by an exemption someone could delete. CI also gets a fresh empty
    Postgres per run, so a shared base there is correct, not dangerous.
    """
    monkeypatch.setattr("tests.helpers.test_db_helper.clone_dir_slot", lambda: "2")

    verdict = _shared_base_verdict(resolved, xdist)
    assert (verdict[0] if verdict else None) == expected, verdict


def test_an_unnumbered_tree_is_warned_and_not_refused(monkeypatch):
    """The primary checkout keeps its historical behaviour.

    It has no lane base of its own, so there is nothing to tell it to use instead;
    refusing would break a correct habit to enforce a rule that does not apply,
    which is the kind of collateral that gets a guard disabled rather than obeyed.

    THIS IS NOT A HYPOTHETICAL CASE. A deployed test box in this project runs the
    full suite from an unnumbered checkout, defaulting to ``giljo_mcp_test`` under
    ``-n auto``: the shared base WITH xdist, the exact arrangement the FAIL branch
    exists to stop. It is correct there, because that box holds a DEDICATED
    throwaway database and nothing else runs the suite against it, so "shared" has
    no one to share with. The narrowing to numbered clones is what keeps that path
    working, and this case is why the condition is not simply
    "shared base + xdist".
    """
    monkeypatch.setattr("tests.helpers.test_db_helper.clone_dir_slot", lambda: "")

    level, message = _shared_base_verdict(TEST_DB_NAME, True)
    assert level == "WARN"
    assert "not a numbered clone" in message


def test_the_refusal_message_names_the_base_the_clone_should_have_used(monkeypatch):
    """An actionable refusal, per the house rule that a rejection must be a remedy.

    The directory is right there, so the message can name ``giljo_mcp_test4``
    rather than telling the reader to go work it out.

    The remedy pinned here is ``DATABASE_URL``, deliberately, and not the name of
    this repo's private suite wrapper: ``tests/`` ships to the published CE tree
    while the operator tooling that wrapper lives in is stripped from it, so a
    refusal naming that script would hand a reader a fix that does not exist in
    their checkout — the same genre of untrue instrument this whole change exists
    to remove. ``export DATABASE_URL=...`` works in every tree.
    """
    monkeypatch.setattr("tests.helpers.test_db_helper.clone_dir_slot", lambda: "4")

    level, message = _shared_base_verdict(TEST_DB_NAME, True)
    assert level == "FAIL"
    assert "giljo_mcp_test4" in message
    assert "DATABASE_URL" in message
    assert SHARED_BASE_OVERRIDE_ENV_VAR in message


def test_xdist_is_detected_from_the_controller_and_from_a_worker(monkeypatch):
    """``pytest_configure`` runs in the controller AND in every worker.

    The controller knows only ``-n``; a worker knows only its own
    ``PYTEST_XDIST_WORKER``. Checking one gives a verdict that is right in one
    process and wrong in all the others, so both are checked.
    """
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    class _Config:
        def __init__(self, numprocesses):
            self.option = type("O", (), {"numprocesses": numprocesses})()

    assert _xdist_active(_Config(6)) is True
    assert _xdist_active(_Config("auto")) is True, (
        "-n auto is normalised by xdist's own pytest_configure, and plugin ordering "
        "between it and ours is not guaranteed — an unresolved string must still count"
    )
    assert _xdist_active(_Config(0)) is False
    assert _xdist_active(_Config(None)) is False

    # ...and a worker, which never sees -n at all.
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
    assert _xdist_active(_Config(None)) is True


def test_the_banner_headline_matches_what_the_run_then_does():
    """The first implementation of the refusal printed "✓ PASSED" and then aborted.

    That is this project's own defect class committed inside the fix for it: a
    banner whose headline contradicts the outcome. The header is derived from the
    verdict, so it cannot drift from it again.
    """
    fail = _banner_lines(True, "ok", "giljo_mcp_test", "DEFAULT_CONFIG", "because", "FAIL")
    assert any("ABORTED" in line for line in fail)
    assert not any("PASSED" in line for line in fail)

    warn = _banner_lines(True, "ok", "giljo_mcp_test", "DEFAULT_CONFIG", "because", "WARN")
    assert any("WARNING" in line for line in warn)

    clean = _banner_lines(True, "ok", "giljo_mcp_test2", "DATABASE_URL")
    assert any("PASSED" in line for line in clean)
    assert not any("ABORT" in line or "WARN" in line for line in clean)


def test_the_production_danger_banner_still_renders():
    """The path that must never be the one that breaks.

    INF-9432 restructured the banner builder, and the production-protection branch
    is the one nobody exercises in normal work — so a formatting error there would
    surface for the first time on a run actually pointed at production, replacing
    the safety message with a traceback about string formatting. Its real message is
    multi-line with embedded newlines, which is exactly what the wrapper has to
    handle.
    """
    real_message = (
        "DATABASE_URL points to production database 'giljo_mcp'!\n"
        "  Expected: URL containing 'giljo_mcp_test'\n"
        "\n"
        "To fix:\n"
        "  1. Unset DATABASE_URL: unset DATABASE_URL"
    )
    lines = _banner_lines(False, real_message, "giljo_mcp", "DATABASE_URL")

    assert any("ABORTED" in line for line in lines)
    assert any("giljo_mcp" in line for line in lines), "the banner must name the offending database"
    assert any("Unset DATABASE_URL" in line for line in lines), "the remedy must survive wrapping"
    widths = {len(line) for line in lines}
    assert len(widths) == 1, f"production banner rows have differing widths: {sorted(widths)}"


def test_the_banner_box_stays_aligned_for_a_long_database_name():
    """A value longer than the box must be truncated, not allowed to shear the frame.

    The banner is the one thing a lane reads under time pressure; a broken frame is
    read as a crash.
    """
    lines = _banner_lines(True, "ok", "giljo_mcp_test999999_gw11" * 4, "DATABASE_URL", "x" * 400, "WARN")
    widths = {len(line) for line in lines}
    assert len(widths) == 1, f"banner rows have differing widths: {sorted(widths)}"


# ---------------------------------------------------------------------------
# The selector law. clone_slot() already existed; what had no mechanism was the
# DROP/cleanup side, where a slot-less wildcard silently means "everyone".
# ---------------------------------------------------------------------------


def test_the_two_lane_derivations_agree_when_the_tree_is_pinned_correctly():
    """``clone_slot()`` (off the pinned base) vs ``clone_dir_slot()`` (off the directory).

    ``clone_slot``'s own docstring warns that "a second derivation is free to drift
    away from the first" — and nothing checked that the two answers agree. This is
    that check, run against the real tree and the real pin: in a correctly-pinned
    clone they must be equal, and their DISagreement is precisely what the refusal
    reports.

    ON THE SKIP BELOW, because a silently-skipping guard is the decorative-guard
    problem: this is an environmental precondition, not a muted failure. A tree
    with no directory slot (CI's workspace, the primary
    checkout) has no lane, so there is no second answer for the first to agree
    WITH — the property is undefined rather than violated. The agreement property
    itself is asserted UNCONDITIONALLY, on synthetic slots, by
    ``test_the_refusal_fires_on_exactly_one_arrangement`` and
    ``test_the_refusal_message_names_the_base_the_clone_should_have_used``, which
    monkeypatch ``clone_dir_slot`` and cover both agreement and disagreement. So
    this case adds real-tree coverage on a workstation clone and hides nothing
    where it skips.
    """
    dir_slot = clone_dir_slot()
    if not dir_slot:
        # Bound to a name rather than passed inline so that ``reason=`` lands on the
        # skip call's OWN line. The BE-5060 rationale gate in ci.yml scans ADDED DIFF
        # LINES one at a time, so a reason on the following line satisfies a human
        # reader and not the gate. Checking that the rationale exists and checking
        # that the gate can SEE it are two different checks.
        #
        # This comment also deliberately does not quote the skip call verbatim: the
        # gate matches source text, so prose ABOUT it reads as an instance OF it --
        # the same way a tombstone comment matched the env-mutation census.
        skip_reason = (
            "this tree is not a numbered clone (clone_CI<N>), so it has no "
            "directory-derived slot for the pinned base to agree with -- the property is "
            "undefined here, and it is asserted unconditionally on synthetic slots by the "
            "refusal truth-table cases in this file"
        )
        pytest.skip(reason=skip_reason)
    assert clone_slot() == dir_slot, (
        f"this tree's directory says lane {dir_slot!r} but its pinned test-DB base says "
        f"{clone_slot()!r}. Pin the base from the directory (this repo's local suite "
        "wrapper does it for you) so the two cannot disagree."
    )


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        pytest.param("giljo_mcp_test2", "giljo_test_bootstrap2%", id="CI2"),
        pytest.param("giljo_mcp_test4", "giljo_test_bootstrap4%", id="CI4"),
        pytest.param("giljo_mcp_test4_gw3", "giljo_test_bootstrap4%", id="worker-suffix-ignored"),
    ],
)
def test_the_selector_carries_the_lane_slot(monkeypatch, base: str, expected: str):
    _as_lane(monkeypatch, base)
    assert lane_scratch_db_selector("giljo_test_bootstrap") == expected


@pytest.mark.parametrize(
    "base",
    [
        pytest.param("giljo_mcp_test", id="shared-default"),
        pytest.param("giljo_test", id="CI-base"),
    ],
)
def test_the_selector_refuses_rather_than_widening_to_every_lane(monkeypatch, base: str):
    """The refusal is the mechanism; the string is only the convenience.

    With no slot, ``giljo_test_bootstrap%`` is not "my scratch databases" — it is
    everyone's. Returning it would be worse than raising, because the widened
    selector still appears to work and only reaches other people's databases. That
    is not hypothetical: it dropped 20 databases across four lanes on 2026-08-14.
    """
    _as_lane(monkeypatch, base)

    with pytest.raises(RuntimeError, match="refusing to build a slot-less selector"):
        lane_scratch_db_selector("giljo_test_bootstrap")


@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param("giljo_test_bootstrap2", id="already-slotted-would-double-the-digit"),
        pytest.param("giljo_test_bootstrap%", id="a-pattern-not-a-prefix"),
        pytest.param("", id="empty"),
    ],
)
def test_the_selector_refuses_a_malformed_prefix(monkeypatch, prefix: str):
    _as_lane(monkeypatch, "giljo_mcp_test2")

    with pytest.raises(RuntimeError):
        lane_scratch_db_selector(prefix)


def test_one_lanes_selector_cannot_match_another_lanes_databases(monkeypatch):
    """The property itself, stated across the lanes that actually exist.

    A ``LIKE`` pattern is checked here by translating ``%`` to a regex wildcard, so
    this asserts the containment relation rather than the string shape — the string
    shape is what the cases above pin.
    """
    lanes = {}
    for slot in range(1, 7):
        _as_lane(monkeypatch, f"giljo_mcp_test{slot}")
        lanes[slot] = lane_scratch_db_selector("giljo_test_bootstrap")

    assert len(set(lanes.values())) == 6, f"six lanes produced {len(set(lanes.values()))} selectors: {lanes}"

    for slot, pattern in lanes.items():
        matcher = re.compile("^" + re.escape(pattern).replace("%", ".*") + "$")
        # Matches every database this lane owns...
        for own in (f"giljo_test_bootstrap{slot}", *(f"giljo_test_bootstrap{slot}_gw{w}" for w in range(6))):
            assert matcher.match(own), f"lane {slot}'s selector {pattern!r} does not match its own {own!r}"
        # ...and none of any sibling's.
        for other in (s for s in range(1, 7) if s != slot):
            for foreign in (f"giljo_test_bootstrap{other}", f"giljo_test_bootstrap{other}_gw0"):
                assert not matcher.match(foreign), (
                    f"lane {slot}'s selector {pattern!r} reaches lane {other}'s database {foreign!r}"
                )
        # ...and not the unnumbered default set, which belongs to no lane.
        assert not matcher.match("giljo_test_bootstrap")
        assert not matcher.match("giljo_test_bootstrap_gw0")
