# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9387 — the schema-drift guard's scratch DB must be isolated PER LANE.

The incident
============
``tests/helpers/test_be9288_schema_drift_guard.py`` named its throwaway scratch
DB with a bare literal, ``giljo_mcp_test9`` + the xdist worker suffix. The file's
own comment justified slot 9 as sitting outside the small slots real dev clones
use, combined with the worker suffix so concurrent xdist workers get distinct
names. That reasoning is correct and **incomplete**: it isolates workers within
one run and does nothing to isolate LANES from each other. Every clone hardcoded
the same 9, so CI1/CI3/CI4/CI5/CI6 all targeted ``giljo_mcp_test9_gw0..gwN`` at
the same time, while the ``scratch_db`` fixture force-drops and then creates.

Measured, not inferred: that file was run with the same ``-n 6`` twice from one
clone — alone it was ``5 passed in 12.52s``, and under concurrent activity from
sibling clones it went red, on a ``test9`` database belonging to nobody. A second
clone independently observed ``giljo_mcp_test9_gw4`` present while it was not
running that test, and a worker killed by a sibling's ``pg_terminate_backend``.

This is the SECOND bare literal of exactly this shape.
``test_db_helper.bootstrap_db_base`` was written for the first one (TSK-9381) and
says so: the migration scratch DB "was missed because its name is not derived
from ``DATABASE_URL`` at all — it was a bare literal". So the fix is not a new
mechanism, it is applying the existing one — and the derivation now lives in ONE
place, :func:`clone_slot`, which both scratch-DB names call.

What is asserted here
=====================
That the derived name actually DIFFERS per lane, which is the whole property, and
that the three things it must never collide with stay clear of it: the lane's own
per-worker test DB, the migration scratch DB, and a sibling lane's scratch DB.
Plus that it still satisfies the production-safety allowlist — a scratch name the
guard rejects would fail every BE-9288 test with an unrelated message.

A two-tree concurrency harness is deliberately NOT here: the collision is fully
determined by the names, so name derivation is the discriminating evidence, and a
timing harness would buy a slower, flakier version of the same answer.

Parallel-safe: pure derivation, monkeypatched env only, no database is contacted.
"""

from __future__ import annotations

import pytest

from tests.helpers.test_db_helper import (
    bootstrap_db_base,
    clone_slot,
    schema_guard_scratch_base,
    validate_database_name,
)


def _as_lane(monkeypatch: pytest.MonkeyPatch, base: str) -> None:
    """Put this process in the lane whose pinned test-DB base is ``base``.

    The local CI-faithful test runner pins the clone-derived base by exporting
    ``DATABASE_URL`` (``clone_CI6`` -> ``giljo_mcp_test6``), so setting that
    variable IS how a lane identifies itself. The suite itself runs under that
    export, so every case sets it explicitly rather than inheriting whichever lane
    happens to be running this test.
    """
    monkeypatch.setenv("DATABASE_URL", f"postgresql://postgres:pw@localhost:5432/{base}")


# ---------------------------------------------------------------------------
# THE REGRESSION — the scratch name must differ per lane.
# These cases are red against the bare `giljo_mcp_test9` literal.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        pytest.param("giljo_mcp_test6", "giljo_mcp_test96", id="CI6"),
        pytest.param("giljo_mcp_test5", "giljo_mcp_test95", id="CI5"),
        pytest.param("giljo_mcp_test42", "giljo_mcp_test942", id="two-digit-clone"),
    ],
)
def test_scratch_base_carries_the_clone_slot(monkeypatch, base: str, expected: str):
    """Lane CI6 gets its own scratch DB, not the one every other lane also drops."""
    _as_lane(monkeypatch, base)

    assert schema_guard_scratch_base() == expected, (
        f"lane on base {base!r} derived scratch base {schema_guard_scratch_base()!r}, not {expected!r}. "
        "A scratch name shared across lanes is force-dropped and recreated by whichever lane gets "
        "there first, which is what turned three lanes' gate runs red (INF-9387)."
    )


@pytest.mark.parametrize(
    "base",
    [
        pytest.param("giljo_mcp_test", id="unnumbered-primary-tree"),
        pytest.param("giljo_test", id="CI-base"),
    ],
)
def test_unnumbered_bases_keep_the_historical_name(monkeypatch, base: str):
    """Unchanged where it was already correct: no slot means plain ``giljo_mcp_test9``.

    The primary tree and CI each run one suite at a time against their own
    Postgres, so they never had the lane collision and must not be moved onto a
    new database name to fix someone else's.
    """
    _as_lane(monkeypatch, base)

    assert schema_guard_scratch_base() == "giljo_mcp_test9"


def test_lanes_do_not_share_a_scratch_name(monkeypatch):
    """The property itself, stated across the lanes that actually exist."""
    names = set()
    for slot in range(1, 7):
        _as_lane(monkeypatch, f"giljo_mcp_test{slot}")
        names.add(schema_guard_scratch_base())

    assert len(names) == 6, f"six lanes produced {len(names)} distinct scratch names: {sorted(names)}"


# ---------------------------------------------------------------------------
# The three names it must never collide with.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", [1, 2, 3, 4, 5, 6])
def test_scratch_name_collides_with_nothing_else_the_lane_uses(monkeypatch, slot: int):
    """Distinct from the lane's live per-worker DB and from its migration scratch DB.

    The guard force-drops its scratch DB, so a name equal to either of those would
    demolish the database the rest of the suite is running against.
    """
    _as_lane(monkeypatch, f"giljo_mcp_test{slot}")
    scratch = schema_guard_scratch_base()

    assert scratch != f"giljo_mcp_test{slot}", "the scratch DB IS the lane's own test database"
    assert scratch != bootstrap_db_base(), "the scratch DB collides with the migration bootstrap scratch DB"


def test_worker_suffixed_base_does_not_donate_its_worker_number(monkeypatch):
    """``giljo_mcp_test6_gw3`` is lane 6, not lane 3.

    ``resolve_test_db_name`` appends ``_gwN``, so a base read back after that step
    ends in the worker number. Taking the trailing digits naively would give every
    worker a different "lane" and re-scatter the names.
    """
    _as_lane(monkeypatch, "giljo_mcp_test6_gw3")

    assert clone_slot() == "6"
    assert schema_guard_scratch_base() == "giljo_mcp_test96"


# ---------------------------------------------------------------------------
# Safety allowlist. Every scratch name reaches get_test_db_url, which validates.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("base", ["giljo_mcp_test", "giljo_mcp_test6", "giljo_mcp_test42", "giljo_test"])
@pytest.mark.parametrize("suffix", ["", "_gw0", "_gw5"])
def test_derived_scratch_name_passes_the_production_safety_guard(monkeypatch, base: str, suffix: str):
    """A derived name the allowlist rejects would fail BE-9288 for an unrelated reason.

    ``validate_database_name`` admits only the two canonical test bases plus digits
    plus an optional ``_gwN`` — which is precisely why the clone slot is appended as
    bare digits with no separator.
    """
    _as_lane(monkeypatch, base)

    validate_database_name(f"{schema_guard_scratch_base()}{suffix}")
