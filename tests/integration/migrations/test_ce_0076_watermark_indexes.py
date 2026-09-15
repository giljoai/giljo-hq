# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from tests.helpers.test_db_helper import bootstrap_db_base, worker_suffix


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SCRATCH_DB = f"{bootstrap_db_base()}{worker_suffix()}"
ADMIN_USER = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
ADMIN_PASSWORD = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

PRODUCTION_DB_NAME = "giljo_mcp"

_PRE = "ce_0075_projects_ever_launched_at"
_TARGET = "ce_0076_watermark_tenant_updated_indexes"

_DISCOVERY_SQL = (
    "SELECT table_name FROM information_schema.columns"
    " WHERE table_schema = 'public' AND column_name = 'updated_at'"
    " INTERSECT "
    "SELECT table_name FROM information_schema.columns"
    " WHERE table_schema = 'public' AND column_name = 'tenant_key'"
)


def _scratch_db_url() -> str:
    if SCRATCH_DB == PRODUCTION_DB_NAME:
        raise RuntimeError(
            "SAFETY GUARD: Refusing to run migration regression tests against "
            "the production DB name 'giljo_mcp'. Override GILJO_BOOTSTRAP_TEST_DB."
        )
    pw = ADMIN_PASSWORD
    if not pw:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("POSTGRES_OWNER_PASSWORD="):
                    pw = line.split("=", 1)[1].strip()
                    break
    if not pw:
        raise RuntimeError("POSTGRES_OWNER_PASSWORD is not set; cannot connect to scratch DB.")
    return f"postgresql://{ADMIN_USER}:{pw}@{DB_HOST}:{DB_PORT}/{SCRATCH_DB}"


def _scratch_engine() -> sa.Engine:
    return sa.create_engine(_scratch_db_url(), poolclass=sa.pool.NullPool)


def _drop_all_objects(engine: sa.Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text(f"GRANT ALL ON SCHEMA public TO {ADMIN_USER}"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        conn.commit()


def _build_env(mode: str) -> dict[str, str]:
    env = os.environ.copy()
    url = _scratch_db_url()
    env["DATABASE_URL"] = url
    env["POSTGRES_HOST"] = DB_HOST
    env["POSTGRES_PORT"] = DB_PORT
    env["POSTGRES_DB"] = SCRATCH_DB
    env["POSTGRES_USER"] = ADMIN_USER
    pwd = url.split("//", 1)[1].split("@", 1)[0].split(":", 1)[1]
    env["POSTGRES_PASSWORD"] = pwd
    if mode:
        env["GILJO_MODE"] = mode
    else:
        env.pop("GILJO_MODE", None)
    return env


def _run_alembic(*args: str, mode: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/alembic_cli.py", *args],
        cwd=str(PROJECT_ROOT),
        env=_build_env(mode),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _discover_sources(engine: sa.Engine) -> list[str]:
    with engine.connect() as conn:
        return sorted(r[0] for r in conn.execute(text(_DISCOVERY_SQL)).fetchall())


def _tenant_updated_indexed_tables(engine: sa.Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tablename, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND indexdef ILIKE '%(tenant_key, updated_at%'"
            )
        ).fetchall()
    return {t for t, _ in rows}


def _tenant_updated_index_count(engine: sa.Engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' "
                    "AND indexname LIKE 'idx_%_tenant_updated'"
                )
            ).scalar()
        )


@pytest.fixture(scope="module")
def scratch_engine():
    prefix, _, _ = _scratch_db_url().rpartition("/")
    admin_url = f"{prefix}/postgres"
    eng = sa.create_engine(admin_url, poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn:
            existing = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": SCRATCH_DB}
            ).scalar()
            if not existing:
                conn.execute(text(f'CREATE DATABASE "{SCRATCH_DB}" OWNER "{ADMIN_USER}"'))
    finally:
        eng.dispose()
    engine = _scratch_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield engine
    engine.dispose()


@pytest.fixture
def empty_scratch_db(scratch_engine: sa.Engine):
    _drop_all_objects(scratch_engine)
    yield scratch_engine
    _drop_all_objects(scratch_engine)


@pytest.mark.integration
class TestCe0076WatermarkIndexes:
    def test_pre_migration_has_no_watermark_indexes(self, empty_scratch_db: sa.Engine) -> None:
        assert _run_alembic("upgrade", _PRE).returncode == 0
        assert _tenant_updated_index_count(empty_scratch_db) == 0, (
            "precondition: no idx_*_tenant_updated index should exist before ce_0076"
        )

    def test_head_indexes_every_watermark_source(self, empty_scratch_db: sa.Engine) -> None:
        up = _run_alembic("upgrade", _TARGET)
        assert up.returncode == 0, f"upgrade {_TARGET} failed:\n{up.stdout}\n{up.stderr}"

        sources = _discover_sources(empty_scratch_db)
        assert sources, "discovery returned no watermark sources — schema not migrated?"

        indexed = _tenant_updated_indexed_tables(empty_scratch_db)
        uncovered = [t for t in sources if t not in indexed]
        assert not uncovered, (
            "watermark source tables missing a (tenant_key, updated_at) index "
            f"(drift — they would seq-scan the sweep): {uncovered}"
        )

    def test_migration_is_idempotent(self, empty_scratch_db: sa.Engine) -> None:
        assert _run_alembic("upgrade", _TARGET).returncode == 0
        first = _tenant_updated_index_count(empty_scratch_db)
        assert first > 0
        assert _run_alembic("stamp", _PRE).returncode == 0
        rerun = _run_alembic("upgrade", _TARGET)
        assert rerun.returncode == 0, f"idempotent re-run failed:\n{rerun.stdout}\n{rerun.stderr}"
        assert _tenant_updated_index_count(empty_scratch_db) == first

    def test_downgrade_drops_the_indexes(self, empty_scratch_db: sa.Engine) -> None:
        assert _run_alembic("upgrade", _TARGET).returncode == 0
        assert _tenant_updated_index_count(empty_scratch_db) > 0
        assert _run_alembic("downgrade", _PRE).returncode == 0
        assert _tenant_updated_index_count(empty_scratch_db) == 0

    def test_saas_chain_indexes_saas_only_sources(self, empty_scratch_db: sa.Engine) -> None:
        up = _run_alembic("upgrade", "heads", mode="saas")
        assert up.returncode == 0, f"saas upgrade heads failed:\n{up.stdout}\n{up.stderr}"
        indexed = _tenant_updated_indexed_tables(empty_scratch_db)
        assert {"organization_plans", "tenant_trials"} <= indexed, (
            f"SaaS-only watermark sources not indexed by saas_028: got {sorted(indexed)}"
        )
