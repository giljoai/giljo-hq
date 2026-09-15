# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.tools._unknown_keys import split_known


def test_partitions_known_from_unknown():
    used, unknown = split_known({"a": 1, "zzz": 2, "b": 3}, {"a", "b"})
    assert used == {"a": 1, "b": 3}
    assert unknown == ["zzz"]


def test_unknown_names_are_sorted_for_a_stable_message():
    _used, unknown = split_known({"delta": 1, "alpha": 2, "charlie": 3}, set())
    assert unknown == ["alpha", "charlie", "delta"]


def test_all_known_yields_no_unknown():
    used, unknown = split_known({"a": 1, "b": 2}, {"a", "b", "c"})
    assert used == {"a": 1, "b": 2}
    assert unknown == []


def test_empty_supplied_is_empty_both_ways():
    used, unknown = split_known({}, {"a"})
    assert used == {}
    assert unknown == []


def test_does_not_mutate_the_caller_mapping():
    supplied = {"a": 1, "zzz": 2}
    before = dict(supplied)
    split_known(supplied, {"a"})
    assert supplied == before


def test_values_are_preserved_not_just_keys():
    used, _unknown = split_known({"a": {"nested": True}, "bad": 1}, {"a"})
    assert used["a"] == {"nested": True}


@pytest.mark.parametrize("known", [["a", "b"], ("a", "b"), {"a", "b"}, {"a": 1, "b": 2}])
def test_accepts_any_collection_as_the_vocabulary(known):
    used, unknown = split_known({"a": 1, "nope": 2}, known)
    assert used == {"a": 1}
    assert unknown == ["nope"]


def test_real_field_map_vocabulary_rejects_a_non_column_name():
    from giljo_mcp.tools.vision_analysis import FIELD_MAP

    used, unknown = split_known({"product_name": "X", "not_a_column": "Y"}, FIELD_MAP)
    assert used == {"product_name": "X"}
    assert unknown == ["not_a_column"]


def test_real_category_vocabulary_rejects_the_db_column_spelling():
    from giljo_mcp.tools.context_tools.fetch_context import CATEGORY_TOOLS

    _used, unknown = split_known({"memory_last_n_projects": 1, "memory_360": 3}, CATEGORY_TOOLS)
    assert unknown == ["memory_last_n_projects"]
