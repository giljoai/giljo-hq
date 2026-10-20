# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from giljo_mcp.db_url import normalize_database_url
from tests.helpers.test_db_helper import bootstrap_db_base, create_database_lock, worker_suffix


@pytest.fixture
def test_user():
    return


@pytest.fixture(autouse=True)
def set_tenant_context():
    return


_SCRATCH_READY: set[str] = set()


def _ensure_scratch_db_as_superuser(scratch_db: str) -> None:
    if scratch_db in _SCRATCH_READY:
        return
    superuser_pw = os.environ.get("POSTGRES_SUPERUSER_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", os.environ.get("DB_HOST", "localhost"))
    port = os.environ.get("POSTGRES_PORT", os.environ.get("DB_PORT", "5432"))
    owner = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
    if not superuser_pw:
        _ensure_scratch_db_as_owner(scratch_db, owner, host, port)
        _SCRATCH_READY.add(scratch_db)
        return
    admin_url = f"postgresql://postgres:{superuser_pw}@{host}:{port}/postgres"
    eng = sa.create_engine(
        normalize_database_url(admin_url, "sync"), poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        with eng.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": scratch_db},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch_db}"'))
            with create_database_lock(conn):
                conn.execute(text(f'CREATE DATABASE "{scratch_db}" OWNER "{owner}"'))
    finally:
        eng.dispose()
    _SCRATCH_READY.add(scratch_db)


def _ensure_scratch_db_as_owner(scratch_db: str, owner: str, host: str, port: str) -> None:
    owner_pw = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
    if not owner_pw:
        return
    admin_url = f"postgresql://{owner}:{owner_pw}@{host}:{port}/postgres"
    eng = sa.create_engine(
        normalize_database_url(admin_url, "sync"), poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        try:
            conn_ctx = eng.connect()
        except sa.exc.OperationalError:
            return
        with conn_ctx as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": scratch_db}
            ).scalar()
            if exists:
                return
            try:
                with create_database_lock(conn):
                    conn.execute(text(f'CREATE DATABASE "{scratch_db}" OWNER "{owner}"'))
            except sa.exc.ProgrammingError as exc:
                if "permission denied" in str(exc).lower():
                    return
                raise
    finally:
        eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def _provision_worker_scratch_db():
    _ensure_scratch_db_as_superuser(f"{bootstrap_db_base()}{worker_suffix()}")
