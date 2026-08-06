# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9322 — direct contract tests for ``split_known``.

The two callers enforce the shared rule at different strengths:
``get_context`` raises, ``update_product_context`` reports into
``fields_skipped``. The ``get_context`` half is covered end-to-end through the
real MCP transport (``tests/integration/test_be9322_context_depth_mcp_transport.py``).

The ``update_product_context`` half **cannot** be covered that way, and the
audit was right to insist this file exist. Its unknown-field branch is
unreachable from every production caller: the grouped MCP models declare
``extra="forbid"``, FastMCP drops unknown top-level args before the tool is
entered, and ``vision_summaries``/``consolidated_vision`` are popped before the
check runs -- so the reachable field set is exactly ``FIELD_MAP``'s 21 names,
with an empty difference in both directions.

That makes an end-to-end test impossible to write honestly, and it is precisely
why the helper needs its own test: pinning the contract HERE specifies the
behaviour independently of FastMCP, so if that layer is ever relaxed to
``extra="allow"`` the semantics are already fixed rather than discovered at the
point of failure.

Parallel-safe: pure function, no DB, no module-level mutable state.
"""

from __future__ import annotations

import pytest

from giljo_mcp.tools._unknown_keys import split_known


def test_partitions_known_from_unknown():
    used, unknown = split_known({"a": 1, "zzz": 2, "b": 3}, {"a", "b"})
    assert used == {"a": 1, "b": 3}
    assert unknown == ["zzz"]


def test_unknown_names_are_sorted_for_a_stable_message():
    """Error text and fields_skipped ordering must not depend on dict order."""
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
    """The callers pass their live payload dict; splitting must not disturb it."""
    supplied = {"a": 1, "zzz": 2}
    before = dict(supplied)
    split_known(supplied, {"a"})
    assert supplied == before


def test_values_are_preserved_not_just_keys():
    """``used`` is fed straight into downstream writes, so values must survive."""
    used, _unknown = split_known({"a": {"nested": True}, "bad": 1}, {"a"})
    assert used["a"] == {"nested": True}


@pytest.mark.parametrize("known", [["a", "b"], ("a", "b"), {"a", "b"}, {"a": 1, "b": 2}])
def test_accepts_any_collection_as_the_vocabulary(known):
    """Callers pass a dict (FIELD_MAP) and a dict (CATEGORY_TOOLS); both are
    Collections whose membership is over keys. Pin that a list/tuple/set behave
    identically, so a future caller cannot get a surprising result."""
    used, unknown = split_known({"a": 1, "nope": 2}, known)
    assert used == {"a": 1}
    assert unknown == ["nope"]


def test_real_field_map_vocabulary_rejects_a_non_column_name():
    """The exact update_product_context shape: FIELD_MAP as the vocabulary."""
    from giljo_mcp.tools.vision_analysis import FIELD_MAP

    used, unknown = split_known({"product_name": "X", "not_a_column": "Y"}, FIELD_MAP)
    assert used == {"product_name": "X"}
    assert unknown == ["not_a_column"]


def test_real_category_vocabulary_rejects_the_db_column_spelling():
    """The exact get_context shape: the DB column name must not be recognised."""
    from giljo_mcp.tools.context_tools.fetch_context import CATEGORY_TOOLS

    _used, unknown = split_known({"memory_last_n_projects": 1, "memory_360": 3}, CATEGORY_TOOLS)
    assert unknown == ["memory_last_n_projects"]
