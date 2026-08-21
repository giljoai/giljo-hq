# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9288 -- regression tests for the test-DB schema-drift guard.

``PostgreSQLTestHelper.ensure_test_database_exists`` only CREATEd the
per-worker DB when absent; a DB left over from an earlier run silently kept
its OLD schema (``Base.metadata.create_all`` never adds a column to a table
that already exists), so a model column added since went missing and tests
failed far from the real cause.

These tests exercise the REAL database against a throwaway scratch DB
(``SCRATCH_DB`` below), never the live per-worker DB a sibling test in this
same process is using. Parallel-safe in BOTH directions: the name carries
this process's own xdist ``worker_suffix()``, so two real xdist workers never
target the same name, AND this clone's slot, so two concurrent LANES never do
either (INF-9387). Tests within one worker run sequentially (pytest never runs
two tests in one worker concurrently), and each test drops+recreates the
scratch DB itself via the ``scratch_db`` fixture, so there is no cross-test
ordering dependency.

(1) is the fail-first regression proof: a deliberately-stale DB must be
recreated by ``ensure_test_database_exists``, not silently left in place.
(2)-(5) pin the four narrow-detection false-positive sources the guard's
docstring calls out -- each MUST NOT be flagged as drift.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from giljo_mcp.models import Base
from tests.helpers.test_db_helper import (
    PostgreSQLTestHelper,
    create_database_lock_async,
    schema_guard_scratch_base,
    worker_suffix,
)


# Two independent axes of isolation, both required (INF-9387):
#   base  -- slot 9 keeps this DB outside the small slots (2, 3, 4 ...) real
#            simultaneous dev clones use, PLUS this clone's own slot so sibling
#            LANES get distinct names (CI6 -> giljo_mcp_test96). The bare literal
#            this replaced isolated workers and not lanes, so every clone
#            force-dropped and recreated the SAME giljo_mcp_test9_gwN.
#   suffix -- this process's own xdist worker, so concurrent workers within one
#            run get distinct names.
# The derivation itself lives in test_db_helper.schema_guard_scratch_base(),
# beside the migration scratch DB's, so "which lane am I" has ONE answer.
SCRATCH_DB = f"{schema_guard_scratch_base()}{worker_suffix()}"

# ONE table is the whole manufacture, deliberately (INF-9406). Every scenario
# below needs a table that EXISTS in the DB so ``_missing_columns`` will look at
# it; none of them needs a second table, and building the full ``Base.metadata``
# to get one cost 38-40s per test under two concurrent -n 6 suites -- past the
# 30s ``--timeout`` in pyproject.toml, whose ``--timeout-method=thread`` kills
# the process outright (``os._exit(1)``), taking the xdist WORKER down and the
# whole suite with it. ``taxonomy_types`` has no FK dependencies, so it stands
# alone (unlike ``projects``, which FKs to ``products``).
#
# DO NOT reintroduce a whole-``Base.metadata`` build here to make a scenario
# "more realistic". The realism is free elsewhere -- the per-worker bootstrap
# runs ``_missing_columns`` against a full create_all schema on every single
# run -- and here it buys nothing these assertions test, at the price of a
# suite that cannot survive a second lane.
DRIFT_TABLE = "taxonomy_types"
# Named in neither uq_taxonomy_type_abbr (tenant_key, abbreviation) nor
# idx_taxonomy_types_tenant_updated (tenant_key, updated_at), so dropping it
# manufactures drift without disturbing a constraint or an index.
DRIFT_COLUMN = "label"


async def _admin_engine():
    return create_async_engine(
        PostgreSQLTestHelper.get_test_db_url(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )


async def _force_drop(name: str) -> None:
    """Best-effort drop so a prior failed run never poisons this one."""
    engine = await _admin_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pg_stat_activity.pid)
                    FROM pg_stat_activity
                    WHERE pg_stat_activity.datname = :name
                    AND pid <> pg_backend_pid()
                    """
                ),
                {"name": name},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        await engine.dispose()


async def _create_empty(name: str) -> None:
    engine = await _admin_engine()
    try:
        async with engine.connect() as conn:
            # The per-worker name keeps siblings off THIS database, but the
            # ``template1`` copy underneath is shared with every other create in
            # the suite — and this one fires inside tests, not once at bootstrap.
            # Take the one shared lock (TSK-9381).
            async with create_database_lock_async(conn):
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def _create_tables(name: str, table_names: list[str]) -> None:
    """Build only the named subset of ``Base.metadata`` tables in ``name``."""
    tables = [Base.metadata.tables[t] for t in table_names]
    engine = create_async_engine(PostgreSQLTestHelper.get_test_db_url(database=name))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=tables)
    finally:
        await engine.dispose()


async def _execute(name: str, sql: str) -> None:
    engine = create_async_engine(PostgreSQLTestHelper.get_test_db_url(database=name))
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


async def _table_count(name: str) -> int:
    engine = create_async_engine(PostgreSQLTestHelper.get_test_db_url(database=name))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            )
            return result.scalar()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def scratch_db(monkeypatch):
    """Pin ``resolve_test_db_name`` to the shared scratch slot for this test,
    starting from a guaranteed-clean (absent) DB and dropping it afterward."""
    monkeypatch.setattr(PostgreSQLTestHelper, "resolve_test_db_name", staticmethod(lambda: SCRATCH_DB))
    await _force_drop(SCRATCH_DB)
    yield SCRATCH_DB
    await _force_drop(SCRATCH_DB)


# ---------------------------------------------------------------------------
# (1) Fail-first: a stale DB (missing column) is dropped and recreated.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_schema_is_recreated_not_silently_kept(scratch_db):
    """A DB left over from an earlier run, missing a column the model now
    declares, must be recreated (empty) by ensure_test_database_exists --
    the old bug silently kept the stale schema in place."""
    await _create_empty(scratch_db)
    await _create_tables(scratch_db, [DRIFT_TABLE])
    await _execute(scratch_db, f"ALTER TABLE {DRIFT_TABLE} DROP COLUMN {DRIFT_COLUMN}")

    # Precondition: the drift detector sees it before we call the guard.
    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)
    assert drift.get(DRIFT_TABLE) == [DRIFT_COLUMN]

    await PostgreSQLTestHelper.ensure_test_database_exists()

    # THE regression assertion: the stale schema is gone -- the DB was
    # dropped and recreated empty (tables are rebuilt by the caller's own
    # create_test_tables step, not by this call).
    assert await _table_count(scratch_db) == 0


# ---------------------------------------------------------------------------
# (2)-(5) No-false-positive sources -- unit-level against _missing_columns.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_false_positive_table_absent_from_db(scratch_db):
    """A Base.metadata table that doesn't exist in the DB at all (normal
    CE-vs-SaaS split) must NOT be flagged as drift."""
    await _create_empty(scratch_db)
    # No FK dependencies -- safe to create standalone (unlike "projects",
    # which FKs to "products"). One table present and the rest of
    # Base.metadata absent IS the scenario: the absent ones must not be flagged.
    await _create_tables(scratch_db, [DRIFT_TABLE])

    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)

    assert drift == {}


@pytest.mark.asyncio
async def test_no_false_positive_extra_table_in_db(scratch_db):
    """A table in the DB that Base.metadata doesn't declare (alembic
    bookkeeping, leftover SaaS tables) must NOT be flagged as drift."""
    await _create_empty(scratch_db)
    await _create_tables(scratch_db, [DRIFT_TABLE])
    await _execute(scratch_db, "CREATE TABLE alembic_bookkeeping_leftover (id integer)")

    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)

    assert drift == {}


@pytest.mark.asyncio
async def test_no_false_positive_extra_column_in_db(scratch_db):
    """An extra column the DB has that the model no longer declares must NOT
    be flagged as drift."""
    await _create_empty(scratch_db)
    await _create_tables(scratch_db, [DRIFT_TABLE])
    await _execute(scratch_db, f"ALTER TABLE {DRIFT_TABLE} ADD COLUMN retired_field_test text")

    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)

    assert drift == {}


@pytest.mark.asyncio
async def test_no_false_positive_type_mismatch(scratch_db):
    """A column present under the same name but a different type/nullability
    must NOT be flagged -- detection compares column NAME presence only."""
    await _create_empty(scratch_db)
    await _create_tables(scratch_db, [DRIFT_TABLE])
    # Same shape as before: one type change and one nullability change.
    await _execute(scratch_db, f"ALTER TABLE {DRIFT_TABLE} ALTER COLUMN {DRIFT_COLUMN} TYPE varchar(10)")
    await _execute(scratch_db, f"ALTER TABLE {DRIFT_TABLE} ALTER COLUMN sort_order SET NOT NULL")

    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)

    assert drift == {}
