# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [SAAS] SaaS Edition.

"""
Local conftest for migration-bootstrap tests.

These tests run alembic against a separate scratch DB and do NOT need the
parent ``tests/integration/conftest.py`` autouse fixtures (test_user,
set_tenant_context) which would force a connection to ``giljo_mcp_test``
and require the schema to be present there. We override those fixtures
here as harmless no-ops so the parent autouse fires but does nothing.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from tests.helpers.test_db_helper import bootstrap_db_base, create_database_lock, worker_suffix


@pytest.fixture
def test_user():
    """Override parent's test_user fixture -- bootstrap tests don't need it."""
    return


@pytest.fixture(autouse=True)
def set_tenant_context():
    """Override parent's autouse tenant-context fixture with a no-op."""
    return


# Per-worker scratch DB names already created this process (created once per
# xdist worker). Each migration test file derives its own SCRATCH_DB with the
# same ``{base}{worker_suffix()}`` rule, so the names line up.
_SCRATCH_READY: set[str] = set()
# Serialization for the CREATE below is THE shared ``create_database_lock`` from
# tests/helpers/test_db_helper.py, not a key of this module's own. It used to be
# 7281643 while the main bootstrap held 7281642 — different keys on the one
# resource both paths contend for (the ``template1`` copy), so the lock excluded
# nothing and a scratch create could race a per-worker create. TSK-9381.


def _ensure_scratch_db_as_superuser(scratch_db: str) -> None:
    """Provision a PRISTINE per-worker scratch DB as the postgres superuser.

    Two problems this solves under pytest-xdist:

    1. The migration tests connect as ``giljo_owner`` (no CREATEDB) and only do
       a check-then-create. When every worker needs its OWN scratch DB, that
       non-privileged path fails with "permission denied to create database".
    2. Migration tests assume a clean scratch DB. Reusing a warm DB from a prior
       session leaks alembic-version / schema state and makes a "warm" scenario
       test fail nondeterministically. So we DROP + CREATE once per worker per
       session for a deterministic clean slate (matching a cold run).

    The DB is owned by ``giljo_owner`` so the tests' own connections work. If no
    superuser password is available we fall back to the test file's own creator.
    """
    if scratch_db in _SCRATCH_READY:
        return
    superuser_pw = os.environ.get("POSTGRES_SUPERUSER_PASSWORD", "")
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    owner = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
    if not superuser_pw:
        # No superuser creds: leave creation to the test file's own fallback.
        _SCRATCH_READY.add(scratch_db)
        return
    admin_url = f"postgresql://postgres:{superuser_pw}@{host}:{port}/postgres"
    eng = sa.create_engine(admin_url, poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn:
            # Terminate any stragglers, then drop, BEFORE taking the lock
            # (INF-9406). `DROP DATABASE` forces a CLUSTER-WIDE immediate
            # checkpoint and waits for it, so its cost is a function of every
            # other worker's dirty buffers -- measured at 6.31s inside this very
            # lock during a concurrent two-tree `-n 6` pair. The scratch name is
            # per-worker AND per-clone unique (bootstrap_db_base + worker_suffix),
            # so the drop touches nothing shared and needs no serialization; the
            # `template1` copy below is the only thing that does. Serializing the
            # drop as well made this critical section as long as the rest of the
            # box's write volume, twelve times per pair.
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": scratch_db},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch_db}"'))
            # Serialize: concurrent template1 copies across workers otherwise
            # collide with "source database is being accessed by other users".
            with create_database_lock(conn):
                conn.execute(text(f'CREATE DATABASE "{scratch_db}" OWNER "{owner}"'))
    finally:
        eng.dispose()
    _SCRATCH_READY.add(scratch_db)


@pytest.fixture(scope="session", autouse=True)
def _provision_worker_scratch_db():
    """Ensure this worker's per-worker migration scratch DB exists (BE-6014).

    Session-scoped + autouse so it runs before the module-scoped
    ``scratch_engine`` fixtures in the individual migration test files.
    """
    _ensure_scratch_db_as_superuser(f"{bootstrap_db_base()}{worker_suffix()}")
