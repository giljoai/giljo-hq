# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-3002a regression — create_tables_async is gated by Alembic ownership.

Schema source of truth: Alembic is the authoritative schema writer. The boot-time
``create_all`` must NOT run against an Alembic-managed database (one that has an
``alembic_version`` table), so a model table/column added without a migration can
never silently materialise via create_all. A fresh, un-migrated DB (the test
bootstrap) still gets create_all so test schema provisioning is unaffected.

These tests exercise the guard at its layer (``DatabaseManager.create_tables_async``)
against a real, isolated throwaway database — the layer the BE-3002a change lives in.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, pool, text
from sqlalchemy.engine import make_url

from giljo_mcp.database import DatabaseManager
from tests.helpers.test_db_helper import create_database_lock, worker_suffix


def _base_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(reason="DATABASE_URL not set — cannot provision a throwaway DB")
    return url


def _db_url(database: str) -> str:
    # Force the bare ``postgresql`` driver (drop any ``+psycopg2``/``+asyncpg``):
    # DatabaseManager converts ``postgresql://`` -> asyncpg for its async engine,
    # while the sync create_engine() calls here default to psycopg2 — both work
    # only from a driverless URL. render_as_string(hide_password=False) because
    # str(URL) masks the password as "***".
    return make_url(_base_url()).set(drivername="postgresql", database=database).render_as_string(hide_password=False)


def _admin_exec(sql: str) -> None:
    # Connect to the maintenance DB to CREATE/DROP the throwaway DB. The CI role
    # (giljo_test) and local superuser both have CREATEDB on the `postgres` DB.
    admin_url = _db_url("postgres")
    eng = create_engine(admin_url, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn:
            conn.execute(text(sql))
    finally:
        eng.dispose()


def _admin_create_db(name: str) -> None:
    """CREATE a throwaway DB under the suite-wide template1 lock (TSK-9381).

    Unlike every other create in the tree this one runs PER TEST, so it is the
    busiest ``template1`` copier in the suite — a uniquely-named target still
    contends on the shared source with any other worker mid-create.
    """
    eng = create_engine(_db_url("postgres"), poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn, create_database_lock(conn):
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        eng.dispose()


@pytest.fixture
def throwaway_db():
    """A pristine, per-test, per-worker throwaway database; dropped at teardown."""
    name = f"giljo_be3002a{worker_suffix()}_{uuid.uuid4().hex[:8]}"
    _admin_exec(f'DROP DATABASE IF EXISTS "{name}"')
    _admin_create_db(name)
    try:
        yield _db_url(name)
    finally:
        _admin_exec(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{name}' AND pid <> pg_backend_pid()"
        )
        _admin_exec(f'DROP DATABASE IF EXISTS "{name}"')


def _has_table(url: str, table: str) -> bool:
    eng = create_engine(url, poolclass=pool.NullPool)
    try:
        return inspect(eng).has_table(table)
    finally:
        eng.dispose()


@pytest.mark.asyncio
async def test_create_tables_async_bootstraps_fresh_db(throwaway_db):
    """Un-migrated DB (no alembic_version) → create_all runs → schema created."""
    assert not _has_table(throwaway_db, "users")

    dbm = DatabaseManager(throwaway_db, is_async=True, use_null_pool=True)
    try:
        await dbm.create_tables_async()
    finally:
        await dbm.close_async()

    assert _has_table(throwaway_db, "users"), "create_all should bootstrap a fresh DB"


@pytest.mark.asyncio
async def test_create_tables_async_skips_when_alembic_managed(throwaway_db):
    """Alembic-managed DB (alembic_version present) → create_all is SKIPPED.

    This is the BE-3002a invariant: zero DDL on a managed DB, so a model table
    with no migration can never appear via create_all.
    """
    # Simulate an Alembic-managed DB carrying ONLY the version table.
    eng = create_engine(throwaway_db, poolclass=pool.NullPool)
    try:
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL PRIMARY KEY)"))
    finally:
        eng.dispose()

    dbm = DatabaseManager(throwaway_db, is_async=True, use_null_pool=True)
    try:
        await dbm.create_tables_async()  # guard must short-circuit before create_all
    finally:
        await dbm.close_async()

    # Zero DDL: no domain tables were created.
    assert not _has_table(throwaway_db, "users"), "create_all must be skipped on an Alembic-managed DB"
