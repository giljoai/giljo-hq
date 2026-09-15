# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.template_validation import MAX_NAME_SUFFIX, crew_suffixed_names, slugify_name


CREW = ["implementer", "tester", "analyzer", "reviewer", "documenter"]


def test_a_free_crew_is_unsuffixed():
    names, n = crew_suffixed_names(CREW, set())
    assert names == CREW
    assert n == 1, "the first product must get the plain names"


def test_order_is_preserved():
    names, _n = crew_suffixed_names(CREW, set())
    assert names == CREW


def test_one_taken_name_moves_the_whole_crew():
    taken = set(CREW) | {"tester-2"}

    names, n = crew_suffixed_names(CREW, taken)

    assert n == 3, f"one occupied name at -2 must push the whole crew to -3, got -{n}"
    assert names == [f"{base}-3" for base in CREW]
    assert "tester-2" not in names


def test_the_blocking_name_need_not_be_in_the_crew_at_the_same_depth():
    taken = set(CREW) | {"documenter-2", "documenter-3"}

    names, n = crew_suffixed_names(CREW, taken)

    assert n == 4
    assert names == [f"{base}-4" for base in CREW]


def test_a_single_agent_crew_still_works():
    names, n = crew_suffixed_names(["tester"], {"tester", "tester-2"})
    assert names == ["tester-3"]
    assert n == 3


def test_an_empty_crew_is_free():
    assert crew_suffixed_names([], {"anything"}) == ([], 1)


def test_exhaustion_returns_none_rather_than_raising():
    taken = {"tester"} | {f"tester-{n}" for n in range(2, MAX_NAME_SUFFIX + 1)}

    assert crew_suffixed_names(["tester"], taken) is None


def test_the_ceiling_matches_the_per_name_loop():
    assert MAX_NAME_SUFFIX == 20

    taken = {"tester"} | {f"tester-{n}" for n in range(2, MAX_NAME_SUFFIX)}
    names, n = crew_suffixed_names(["tester"], taken)
    assert n == MAX_NAME_SUFFIX, "the last usable suffix must be reachable"
    assert names == [f"tester-{MAX_NAME_SUFFIX}"]


@pytest.mark.parametrize("n", [2, 3, 10, 20])
def test_the_suffix_is_a_hyphen_and_a_decimal(n: int):
    taken = {"tester"} | {f"tester-{i}" for i in range(2, n)}
    names, chosen = crew_suffixed_names(["tester"], taken)

    assert chosen == n
    assert names == [f"tester-{n}"]
    assert "_" not in names[0]
    assert slugify_name("tester", f"{n}") == f"tester-{n}"
