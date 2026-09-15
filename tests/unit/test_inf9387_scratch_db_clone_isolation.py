# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from tests.helpers.test_db_helper import (
    bootstrap_db_base,
    clone_slot,
    schema_guard_scratch_base,
    validate_database_name,
)


def _as_lane(monkeypatch: pytest.MonkeyPatch, base: str) -> None:
    monkeypatch.setenv("DATABASE_URL", f"postgresql://postgres:pw@localhost:5432/{base}")




@pytest.mark.parametrize(
    ("base", "expected"),
    [
        pytest.param("giljo_mcp_test6", "giljo_mcp_test96", id="CI6"),
        pytest.param("giljo_mcp_test5", "giljo_mcp_test95", id="CI5"),
        pytest.param("giljo_mcp_test42", "giljo_mcp_test942", id="two-digit-clone"),
    ],
)
def test_scratch_base_carries_the_clone_slot(monkeypatch, base: str, expected: str):
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
    _as_lane(monkeypatch, base)

    assert schema_guard_scratch_base() == "giljo_mcp_test9"


def test_lanes_do_not_share_a_scratch_name(monkeypatch):
    names = set()
    for slot in range(1, 7):
        _as_lane(monkeypatch, f"giljo_mcp_test{slot}")
        names.add(schema_guard_scratch_base())

    assert len(names) == 6, f"six lanes produced {len(names)} distinct scratch names: {sorted(names)}"




@pytest.mark.parametrize("slot", [1, 2, 3, 4, 5, 6])
def test_scratch_name_collides_with_nothing_else_the_lane_uses(monkeypatch, slot: int):
    _as_lane(monkeypatch, f"giljo_mcp_test{slot}")
    scratch = schema_guard_scratch_base()

    assert scratch != f"giljo_mcp_test{slot}", "the scratch DB IS the lane's own test database"
    assert scratch != bootstrap_db_base(), "the scratch DB collides with the migration bootstrap scratch DB"


def test_worker_suffixed_base_does_not_donate_its_worker_number(monkeypatch):
    _as_lane(monkeypatch, "giljo_mcp_test6_gw3")

    assert clone_slot() == "6"
    assert schema_guard_scratch_base() == "giljo_mcp_test96"




@pytest.mark.parametrize("base", ["giljo_mcp_test", "giljo_mcp_test6", "giljo_mcp_test42", "giljo_test"])
@pytest.mark.parametrize("suffix", ["", "_gw0", "_gw5"])
def test_derived_scratch_name_passes_the_production_safety_guard(monkeypatch, base: str, suffix: str):
    _as_lane(monkeypatch, base)

    validate_database_name(f"{schema_guard_scratch_base()}{suffix}")
