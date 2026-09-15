# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    monkeypatch.setenv("DATABASE_URL", f"postgresql://postgres:pw@localhost:5432/{base}")
    if worker is None:
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    else:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)


def _target_row(lines: list[str]) -> str:
    row = next(line for line in lines if "Target database:" in line)
    return row.split("Target database:", 1)[1].strip().rstrip("║").strip()




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
    _as_lane(monkeypatch, "giljo_mcp_test2")
    assert resolved_target_database()[1] == "DATABASE_URL"

    monkeypatch.delenv("DATABASE_URL", raising=False)
    target, source = resolved_target_database()
    assert target == TEST_DB_NAME
    assert "DEFAULT_CONFIG" in source and "unset" in source


def test_the_resolved_name_is_not_re_derived_from_database_url_here(monkeypatch):
    _as_lane(monkeypatch, "giljo_mcp_test2", worker="gw3")

    assert resolved_target_database()[0] == "giljo_mcp_test2_gw3"




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
    monkeypatch.setattr("tests.helpers.test_db_helper.clone_dir_slot", lambda: "2")

    verdict = _shared_base_verdict(resolved, xdist)
    assert (verdict[0] if verdict else None) == expected, verdict


def test_an_unnumbered_tree_is_warned_and_not_refused(monkeypatch):
    monkeypatch.setattr("tests.helpers.test_db_helper.clone_dir_slot", lambda: "")

    level, message = _shared_base_verdict(TEST_DB_NAME, True)
    assert level == "WARN"
    assert "not a numbered clone" in message


def test_the_refusal_message_names_the_base_the_clone_should_have_used(monkeypatch):
    monkeypatch.setattr("tests.helpers.test_db_helper.clone_dir_slot", lambda: "4")

    level, message = _shared_base_verdict(TEST_DB_NAME, True)
    assert level == "FAIL"
    assert "giljo_mcp_test4" in message
    assert "DATABASE_URL" in message
    assert SHARED_BASE_OVERRIDE_ENV_VAR in message


def test_xdist_is_detected_from_the_controller_and_from_a_worker(monkeypatch):
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

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
    assert _xdist_active(_Config(None)) is True


def test_the_banner_headline_matches_what_the_run_then_does():
    fail = _banner_lines(True, "ok", "giljo_mcp_test", "DEFAULT_CONFIG", "because", "FAIL")
    assert any("ABORTED" in line for line in fail)
    assert not any("PASSED" in line for line in fail)

    warn = _banner_lines(True, "ok", "giljo_mcp_test", "DEFAULT_CONFIG", "because", "WARN")
    assert any("WARNING" in line for line in warn)

    clean = _banner_lines(True, "ok", "giljo_mcp_test2", "DATABASE_URL")
    assert any("PASSED" in line for line in clean)
    assert not any("ABORT" in line or "WARN" in line for line in clean)


def test_the_production_danger_banner_still_renders():
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
    lines = _banner_lines(True, "ok", "giljo_mcp_test999999_gw11" * 4, "DATABASE_URL", "x" * 400, "WARN")
    widths = {len(line) for line in lines}
    assert len(widths) == 1, f"banner rows have differing widths: {sorted(widths)}"




def test_the_two_lane_derivations_agree_when_the_tree_is_pinned_correctly():
    dir_slot = clone_dir_slot()
    if not dir_slot:
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
    lanes = {}
    for slot in range(1, 7):
        _as_lane(monkeypatch, f"giljo_mcp_test{slot}")
        lanes[slot] = lane_scratch_db_selector("giljo_test_bootstrap")

    assert len(set(lanes.values())) == 6, f"six lanes produced {len(set(lanes.values()))} selectors: {lanes}"

    for slot, pattern in lanes.items():
        matcher = re.compile("^" + re.escape(pattern).replace("%", ".*") + "$")
        for own in (f"giljo_test_bootstrap{slot}", *(f"giljo_test_bootstrap{slot}_gw{w}" for w in range(6))):
            assert matcher.match(own), f"lane {slot}'s selector {pattern!r} does not match its own {own!r}"
        for other in (s for s in range(1, 7) if s != slot):
            for foreign in (f"giljo_test_bootstrap{other}", f"giljo_test_bootstrap{other}_gw0"):
                assert not matcher.match(foreign), (
                    f"lane {slot}'s selector {pattern!r} reaches lane {other}'s database {foreign!r}"
                )
        assert not matcher.match("giljo_test_bootstrap")
        assert not matcher.match("giljo_test_bootstrap_gw0")
