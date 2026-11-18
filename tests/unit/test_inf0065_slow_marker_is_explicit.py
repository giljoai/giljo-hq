# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.pytest_postgresql_plugin import pytest_collection_modifyitems


REPO_ROOT = Path(__file__).resolve().parents[2]

CI_MARKER_EXPRESSION = "not slow and not e2e and not stress and not network and not server_mode"

FAST_TESTS_WITH_SLOW_IN_THEIR_NAMES = [
    "tests/api/test_be9815_cimd_oauth_endpoints.py::TestCimdAuthorizeAndToken::test_a_slow_document_host_times_out",
    "tests/integration/test_be9558_longpoll_ceiling_mcp_transport.py::test_ceiling_cancels_slow_tool_call_and_frees_its_pool_connection",
    "tests/services/test_be9815_oauth_cimd.py::TestFetchOverTheWire::test_slow_server_times_out",
    "tests/services/test_be9815_oauth_cimd.py::TestDnsLookupsStayOffTheDefaultPool::test_slow_lookups_do_not_stall_to_thread_and_excess_is_refused",
    "tests/scripts/test_inf9594_promote_pipefail_and_ci_wait.py::test_ci_wait_ceiling_outlasts_the_slowest_observed_check",
    "tests/saas/auth/test_sec9759_access_log_service.py::test_a_backlog_of_slow_writes_is_dropped_not_queued_and_does_not_use_up_the_window",
]

STRIPPED_FROM_CE_EXPORT = ("tests/saas/", "tests/scripts/")


class _FakeItem:
    def __init__(self, nodeid: str, explicit_markers: tuple[str, ...] = ()) -> None:
        self.nodeid = nodeid
        self.marker_names: list[str] = list(explicit_markers)

    def add_marker(self, marker) -> None:
        self.marker_names.append(marker.name)


@pytest.mark.parametrize(
    "nodeid",
    [
        "tests/services/test_be9815_oauth_cimd.py::TestFetchOverTheWire::test_slow_server_times_out",
        "tests/scripts/test_inf9594_promote_pipefail_and_ci_wait.py::test_ci_wait_ceiling_outlasts_the_slowest_observed_check",
        "tests/SLOW/test_anything.py::test_x",
    ],
)
def test_a_name_containing_slow_does_not_deselect_the_test(nodeid):
    item = _FakeItem(nodeid)

    pytest_collection_modifyitems(config=None, items=[item])

    assert "slow" not in item.marker_names
    assert "postgresql" in item.marker_names


def test_an_explicit_slow_marker_is_kept():
    item = _FakeItem("tests/unit/test_x.py::test_walks_the_tree", explicit_markers=("slow",))

    pytest_collection_modifyitems(config=None, items=[item])

    assert item.marker_names.count("slow") == 1


def test_ci_marker_expression_selects_the_six_fast_tests_named_slow():
    present = [n for n in FAST_TESTS_WITH_SLOW_IN_THEIR_NAMES if (REPO_ROOT / n.split("::")[0]).is_file()]
    unexpectedly_missing = [
        n for n in FAST_TESTS_WITH_SLOW_IN_THEIR_NAMES if n not in present and not n.startswith(STRIPPED_FROM_CE_EXPORT)
    ]
    assert not unexpectedly_missing, f"test files missing from this tree: {unexpectedly_missing}"

    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            "-m",
            CI_MARKER_EXPRESSION,
            *present,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )

    selected = {line.strip() for line in collected.stdout.splitlines()}
    missing = [nodeid for nodeid in present if nodeid not in selected]
    assert not missing, f"deselected by CI's marker expression: {missing}\n{collected.stdout[-2000:]}"
