# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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


SCRATCH_DB = f"{schema_guard_scratch_base()}{worker_suffix()}"

DRIFT_TABLE = "taxonomy_types"
DRIFT_COLUMN = "label"


async def _admin_engine():
    return create_async_engine(
        PostgreSQLTestHelper.get_test_db_url(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )


async def _force_drop(name: str) -> None:
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
            async with create_database_lock_async(conn):
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def _create_tables(name: str, table_names: list[str]) -> None:
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
    monkeypatch.setattr(PostgreSQLTestHelper, "resolve_test_db_name", staticmethod(lambda: SCRATCH_DB))
    await _force_drop(SCRATCH_DB)
    yield SCRATCH_DB
    await _force_drop(SCRATCH_DB)




@pytest.mark.asyncio
async def test_stale_schema_is_recreated_not_silently_kept(scratch_db):
    await _create_empty(scratch_db)
    await _create_tables(scratch_db, [DRIFT_TABLE])
    await _execute(scratch_db, f"ALTER TABLE {DRIFT_TABLE} DROP COLUMN {DRIFT_COLUMN}")

    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)
    assert drift.get(DRIFT_TABLE) == [DRIFT_COLUMN]

    await PostgreSQLTestHelper.ensure_test_database_exists()

    assert await _table_count(scratch_db) == 0




@pytest.mark.asyncio
async def test_no_false_positive_table_absent_from_db(scratch_db):
    await _create_empty(scratch_db)
    await _create_tables(scratch_db, [DRIFT_TABLE])

    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)

    assert drift == {}


@pytest.mark.asyncio
async def test_no_false_positive_extra_table_in_db(scratch_db):
    await _create_empty(scratch_db)
    await _create_tables(scratch_db, [DRIFT_TABLE])
    await _execute(scratch_db, "CREATE TABLE alembic_bookkeeping_leftover (id integer)")

    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)

    assert drift == {}


@pytest.mark.asyncio
async def test_no_false_positive_extra_column_in_db(scratch_db):
    await _create_empty(scratch_db)
    await _create_tables(scratch_db, [DRIFT_TABLE])
    await _execute(scratch_db, f"ALTER TABLE {DRIFT_TABLE} ADD COLUMN retired_field_test text")

    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)

    assert drift == {}


@pytest.mark.asyncio
async def test_no_false_positive_type_mismatch(scratch_db):
    await _create_empty(scratch_db)
    await _create_tables(scratch_db, [DRIFT_TABLE])
    await _execute(scratch_db, f"ALTER TABLE {DRIFT_TABLE} ALTER COLUMN {DRIFT_COLUMN} TYPE varchar(10)")
    await _execute(scratch_db, f"ALTER TABLE {DRIFT_TABLE} ALTER COLUMN sort_order SET NOT NULL")

    drift = await PostgreSQLTestHelper._missing_columns(scratch_db)

    assert drift == {}
