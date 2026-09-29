# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services import debounce


@pytest.fixture(autouse=True)
def _clean_debounce():
    debounce.reset()
    yield
    debounce.reset()


def test_first_call_always_fires():
    assert debounce.should_run("ns", "k", 30.0) is True


def test_second_call_within_window_is_suppressed():
    assert debounce.should_run("ns", "k", 30.0) is True
    assert debounce.should_run("ns", "k", 30.0) is False


def test_distinct_keys_are_independent():
    assert debounce.should_run("ns", "a", 30.0) is True
    assert debounce.should_run("ns", "b", 30.0) is True


def test_distinct_namespaces_are_independent():
    assert debounce.should_run("ns1", "k", 30.0) is True
    assert debounce.should_run("ns2", "k", 30.0) is True


def test_zero_interval_never_suppresses():
    assert debounce.should_run("ns", "k", 0.0) is True
    assert debounce.should_run("ns", "k", 0.0) is True


def test_reset_namespace_clears_only_that_bucket():
    assert debounce.should_run("ns1", "k", 30.0) is True
    assert debounce.should_run("ns2", "k", 30.0) is True
    debounce.reset("ns1")
    assert debounce.should_run("ns1", "k", 30.0) is True
    assert debounce.should_run("ns2", "k", 30.0) is False


def test_reset_all_clears_everything():
    assert debounce.should_run("ns1", "k", 30.0) is True
    assert debounce.should_run("ns2", "k", 30.0) is True
    debounce.reset()
    assert debounce.should_run("ns1", "k", 30.0) is True
    assert debounce.should_run("ns2", "k", 30.0) is True




def test_bucket_is_capped_after_many_distinct_keys():
    for i in range(10_000):
        debounce.should_run("ns", f"key-{i}", 30.0)

    bucket = debounce._LAST_FIRED["ns"]
    assert len(bucket) <= debounce._MAX_KEYS_PER_NAMESPACE
    assert len(bucket) < 10_000


def test_bucket_cap_evicts_oldest_first():
    cap = debounce._MAX_KEYS_PER_NAMESPACE
    for i in range(cap):
        debounce.should_run("ns", f"key-{i}", 30.0)
    debounce.should_run("ns", "key-new", 30.0)

    bucket = debounce._LAST_FIRED["ns"]
    assert len(bucket) == cap
    assert "key-0" not in bucket, "the oldest entry must be the one evicted"
    assert "key-new" in bucket
