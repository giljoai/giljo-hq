# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from tests.helpers.test_db_helper import (
    PostgreSQLTestHelper,
    bootstrap_db_base,
    validate_database_name,
)


ACCEPTED = [
    "giljo_mcp_test",
    "giljo_mcp_test_gw0",
    "giljo_mcp_test_gw1",
    "giljo_mcp_test_gw15",
    "giljo_test",
    "postgres",
    "giljo_mcp_test2",
    "giljo_mcp_test3",
    "giljo_mcp_test2_gw0",
    "giljo_mcp_test4_gw11",
    "giljo_test2",
]

REJECTED = [
    "giljo_mcp",
    "giljo_mcp_saas",
    "giljo",
    "giljo_mcp_testx",
    "giljo_mcp_test_gw",
    "giljo_mcp_test_gwx",
    "giljo_mcp_test_extra",
    "production",
    "",
]


@pytest.mark.parametrize("name", ACCEPTED)
def test_validator_accepts_test_databases(name):
    validate_database_name(name)


@pytest.mark.parametrize("name", REJECTED)
def test_validator_rejects_non_test_databases(name):
    with pytest.raises(RuntimeError):
        validate_database_name(name)


def test_validator_hard_rejects_production_by_name():
    for prod in ("giljo_mcp", "giljo_mcp_saas"):
        with pytest.raises(RuntimeError):
            validate_database_name(prod)


def test_resolve_test_db_name_plain_run(monkeypatch):
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert PostgreSQLTestHelper.resolve_test_db_name() == "giljo_mcp_test"


@pytest.mark.parametrize(
    ("worker", "expected"),
    [
        ("gw0", "giljo_mcp_test_gw0"),
        ("gw7", "giljo_mcp_test_gw7"),
        ("gw13", "giljo_mcp_test_gw13"),
    ],
)
def test_resolve_test_db_name_per_worker(monkeypatch, worker, expected):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
    resolved = PostgreSQLTestHelper.resolve_test_db_name()
    assert resolved == expected
    validate_database_name(resolved)


@pytest.mark.parametrize(
    ("base", "worker", "expected"),
    [
        ("giljo_mcp_test2", "gw0", "giljo_mcp_test2_gw0"),
        ("giljo_mcp_test3", "gw11", "giljo_mcp_test3_gw11"),
        ("giljo_test2", "gw4", "giljo_test2_gw4"),
    ],
)
def test_resolve_numbered_clone_base_gets_worker_suffix(monkeypatch, base, worker, expected):
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:p@localhost:5432/{base}")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
    resolved = PostgreSQLTestHelper.resolve_test_db_name()
    assert resolved == expected
    validate_database_name(resolved)


def test_resolve_numbered_clone_base_serial_stays_bare(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/giljo_mcp_test2")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert PostgreSQLTestHelper.resolve_test_db_name() == "giljo_mcp_test2"


def test_resolve_ignores_non_worker_token(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "master")
    assert PostgreSQLTestHelper.resolve_test_db_name() == "giljo_mcp_test"


def test_get_test_db_url_rejects_production():
    with pytest.raises(RuntimeError):
        PostgreSQLTestHelper.get_test_db_url(database="giljo_mcp")




@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("giljo_test", "giljo_test_bootstrap"),
        ("giljo_mcp_test", "giljo_test_bootstrap"),
        ("giljo_mcp_test1", "giljo_test_bootstrap1"),
        ("giljo_mcp_test6", "giljo_test_bootstrap6"),
        ("giljo_test4", "giljo_test_bootstrap4"),
        ("giljo_mcp_test6_gw3", "giljo_test_bootstrap6"),
    ],
)
def test_bootstrap_base_carries_the_clone_slot(monkeypatch, base, expected):
    monkeypatch.delenv("GILJO_BOOTSTRAP_TEST_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:p@localhost:5432/{base}")
    assert bootstrap_db_base() == expected


def test_bootstrap_base_without_database_url_is_unchanged(monkeypatch):
    monkeypatch.delenv("GILJO_BOOTSTRAP_TEST_DB", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert bootstrap_db_base() == "giljo_test_bootstrap"


def test_explicit_bootstrap_override_still_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/giljo_mcp_test6")
    monkeypatch.setenv("GILJO_BOOTSTRAP_TEST_DB", "giljo_test_bootstrap_explicit")
    assert bootstrap_db_base() == "giljo_test_bootstrap_explicit"


def test_two_clones_never_derive_the_same_scratch_db(monkeypatch):
    monkeypatch.delenv("GILJO_BOOTSTRAP_TEST_DB", raising=False)

    def resolved(base: str) -> str:
        monkeypatch.setenv("DATABASE_URL", f"postgresql://u:p@localhost:5432/{base}")
        return bootstrap_db_base()

    names = {resolved(f"giljo_mcp_test{slot}") for slot in range(1, 7)}
    assert len(names) == 6, f"clones share a migration scratch DB: {sorted(names)}"
