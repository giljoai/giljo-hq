# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    return make_url(_base_url()).set(drivername="postgresql", database=database).render_as_string(hide_password=False)


def _admin_exec(sql: str) -> None:
    admin_url = _db_url("postgres")
    eng = create_engine(admin_url, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn:
            conn.execute(text(sql))
    finally:
        eng.dispose()


def _admin_create_db(name: str) -> None:
    eng = create_engine(_db_url("postgres"), poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn, create_database_lock(conn):
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        eng.dispose()


@pytest.fixture
def throwaway_db():
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
    assert not _has_table(throwaway_db, "users")

    dbm = DatabaseManager(throwaway_db, is_async=True, use_null_pool=True)
    try:
        await dbm.create_tables_async()
    finally:
        await dbm.close_async()

    assert _has_table(throwaway_db, "users"), "create_all should bootstrap a fresh DB"


@pytest.mark.asyncio
async def test_create_tables_async_skips_when_alembic_managed(throwaway_db):
    eng = create_engine(throwaway_db, poolclass=pool.NullPool)
    try:
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL PRIMARY KEY)"))
    finally:
        eng.dispose()

    dbm = DatabaseManager(throwaway_db, is_async=True, use_null_pool=True)
    try:
        await dbm.create_tables_async()
    finally:
        await dbm.close_async()

    assert not _has_table(throwaway_db, "users"), "create_all must be skipped on an Alembic-managed DB"
