# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-6014 — regression tests for the test-database safety validator.

The validator (``validate_database_name``) is a PRODUCTION-SAFETY guard: it is
the gate that prevents the test suite from ever connecting to / creating /
dropping a real database. BE-6014 loosened it to accept per-worker xdist
databases (``giljo_mcp_test_gwN``); the parallel-clone work widened it again to
accept NUMBERED bases (``giljo_mcp_test2``, ``giljo_test3_gwN``, ...) so
simultaneous dev clones on one Postgres don't collide. These tests pin that the
widening is EXACTLY ``^(giljo_mcp_test\\d*|giljo_test\\d*)(_gw\\d+)?$`` plus the
static allowlist — and nothing looser. Production names (``giljo_mcp``,
``giljo_mcp_saas``) and near-misses (``giljo_mcp_testx``) MUST still hard-fail.

Pure-function tests: no database connection required.
"""

import pytest

from tests.helpers.test_db_helper import (
    PostgreSQLTestHelper,
    bootstrap_db_base,
    validate_database_name,
)


# Names the validator MUST accept (test databases only).
ACCEPTED = [
    "giljo_mcp_test",  # canonical local/CI test DB
    "giljo_mcp_test_gw0",  # xdist worker 0
    "giljo_mcp_test_gw1",
    "giljo_mcp_test_gw15",  # double-digit worker index
    "giljo_test",  # CI alias (static allowlist)
    "postgres",  # admin DB for CREATE/DROP DATABASE
    # Parallel-clone numbered bases (simultaneous dev clones on one Postgres):
    "giljo_mcp_test2",  # clone CI2 base
    "giljo_mcp_test3",  # clone CI3 base
    "giljo_mcp_test2_gw0",  # numbered base + xdist worker
    "giljo_mcp_test4_gw11",
    "giljo_test2",  # CI-alias numbered variant
]

# Names the validator MUST reject — production, near-misses, and junk.
REJECTED = [
    "giljo_mcp",  # PRODUCTION
    "giljo_mcp_saas",  # PRODUCTION (SaaS)
    "giljo",
    "giljo_mcp_testx",  # suffix not matching _gwN
    "giljo_mcp_test_gw",  # _gw with no number
    "giljo_mcp_test_gwx",  # _gw with non-digit
    "giljo_mcp_test_extra",
    "production",
    "",
]


@pytest.mark.parametrize("name", ACCEPTED)
def test_validator_accepts_test_databases(name):
    # Must not raise.
    validate_database_name(name)


@pytest.mark.parametrize("name", REJECTED)
def test_validator_rejects_non_test_databases(name):
    with pytest.raises(RuntimeError):
        validate_database_name(name)


def test_validator_hard_rejects_production_by_name():
    """The two real production databases must never validate."""
    for prod in ("giljo_mcp", "giljo_mcp_saas"):
        with pytest.raises(RuntimeError):
            validate_database_name(prod)


def test_resolve_test_db_name_plain_run(monkeypatch):
    """Without an xdist worker, the bare canonical name is used."""
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
    """Under xdist the worker id is appended — and the result still validates."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
    resolved = PostgreSQLTestHelper.resolve_test_db_name()
    assert resolved == expected
    validate_database_name(resolved)  # the resolved name must always be allowed


@pytest.mark.parametrize(
    ("base", "worker", "expected"),
    [
        ("giljo_mcp_test2", "gw0", "giljo_mcp_test2_gw0"),
        ("giljo_mcp_test3", "gw11", "giljo_mcp_test3_gw11"),
        ("giljo_test2", "gw4", "giljo_test2_gw4"),
    ],
)
def test_resolve_numbered_clone_base_gets_worker_suffix(monkeypatch, base, worker, expected):
    """BE-9373: a numbered parallel-clone base must get the per-worker suffix.

    The module comment always promised ``giljo_mcp_test2 -> giljo_mcp_test2_gwN``,
    but the resolver only suffixed the two canonical bases — so a clone that set a
    numbered base handed ONE shared DB to all xdist workers, and clones in practice
    ran on the default base, corrupting each other's concurrent suite runs.
    """
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:p@localhost:5432/{base}")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
    resolved = PostgreSQLTestHelper.resolve_test_db_name()
    assert resolved == expected
    validate_database_name(resolved)  # the resolved name must always be allowed


def test_resolve_numbered_clone_base_serial_stays_bare(monkeypatch):
    """Off-xdist a numbered clone base is used as-is (mirrors canonical behavior)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/giljo_mcp_test2")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert PostgreSQLTestHelper.resolve_test_db_name() == "giljo_mcp_test2"


def test_resolve_ignores_non_worker_token(monkeypatch):
    """A non-``gwN`` value (e.g. xdist controller 'master') yields the bare name."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "master")
    assert PostgreSQLTestHelper.resolve_test_db_name() == "giljo_mcp_test"


def test_get_test_db_url_rejects_production():
    """The URL builder must refuse an explicit production database name."""
    with pytest.raises(RuntimeError):
        PostgreSQLTestHelper.get_test_db_url(database="giljo_mcp")


# ---------------------------------------------------------------------------
# TSK-9381: the OTHER half of clone isolation — the migration scratch DB
# ---------------------------------------------------------------------------
# BE-9373 (above) isolated the per-worker test DBs, which are named from
# DATABASE_URL. The migration-bootstrap scratch DB was missed because its name
# was never derived from DATABASE_URL at all: every one of the 18 migration test
# files hard-coded ``os.environ.get('GILJO_BOOTSTRAP_TEST_DB',
# 'giljo_test_bootstrap')``, and NOTHING in the tree ever set that override. So
# a lane could set its numbered base, isolate its test DBs, and still share one
# global scratch DB with every other clone — a DB the migration conftest DROPS
# and RECREATES per worker and the tests run upgrade/downgrade/drop_all against.
#
# Reproduced before the fix, two clones on DIFFERENT numbered bases running the
# same two migration files concurrently: base test6 -> 6 failed, base test5 ->
# 4 failed / 2 passed, with UniqueViolation on pg_type_typname_nsp_index and
# UndefinedTable on tables the other process had just dropped. After the fix,
# same experiment, same instant: 6 passed and 6 passed, with
# giljo_test_bootstrap5_gw* and giljo_test_bootstrap6_gw* provisioned as
# genuinely separate databases.


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        # Unchanged where it was already correct — CI has ONE clone per postgres
        # service, so the bare name was never a problem there.
        ("giljo_test", "giljo_test_bootstrap"),
        ("giljo_mcp_test", "giljo_test_bootstrap"),
        # The broken case: a numbered clone now gets its own scratch DB.
        ("giljo_mcp_test1", "giljo_test_bootstrap1"),
        ("giljo_mcp_test6", "giljo_test_bootstrap6"),
        ("giljo_test4", "giljo_test_bootstrap4"),
        # A base that already carries a worker suffix must not contribute the
        # WORKER number as the clone slot (that would put every worker of clone 6
        # in a different scratch DB from its own conftest's).
        ("giljo_mcp_test6_gw3", "giljo_test_bootstrap6"),
    ],
)
def test_bootstrap_base_carries_the_clone_slot(monkeypatch, base, expected):
    monkeypatch.delenv("GILJO_BOOTSTRAP_TEST_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:p@localhost:5432/{base}")
    assert bootstrap_db_base() == expected


def test_bootstrap_base_without_database_url_is_unchanged(monkeypatch):
    """A plain local run (no DATABASE_URL) keeps the historical name."""
    monkeypatch.delenv("GILJO_BOOTSTRAP_TEST_DB", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert bootstrap_db_base() == "giljo_test_bootstrap"


def test_explicit_bootstrap_override_still_wins(monkeypatch):
    """``GILJO_BOOTSTRAP_TEST_DB`` remains the escape hatch it always was.

    It is also the zero-patch stopgap for a clone running an older tree, so it
    must keep beating the derived name rather than being quietly ignored.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/giljo_mcp_test6")
    monkeypatch.setenv("GILJO_BOOTSTRAP_TEST_DB", "giljo_test_bootstrap_explicit")
    assert bootstrap_db_base() == "giljo_test_bootstrap_explicit"


def test_two_clones_never_derive_the_same_scratch_db(monkeypatch):
    """THE invariant, stated directly: different clone -> different scratch DB.

    The parametrized cases above pin individual resolutions; this pins the
    property that actually matters, so it survives someone "simplifying" the
    derivation into something that no longer separates clones.
    """
    monkeypatch.delenv("GILJO_BOOTSTRAP_TEST_DB", raising=False)

    def resolved(base: str) -> str:
        monkeypatch.setenv("DATABASE_URL", f"postgresql://u:p@localhost:5432/{base}")
        return bootstrap_db_base()

    names = {resolved(f"giljo_mcp_test{slot}") for slot in range(1, 7)}
    assert len(names) == 6, f"clones share a migration scratch DB: {sorted(names)}"
