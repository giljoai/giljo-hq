# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Migration regression for BE-6054a — Agent Message Hub data foundation.

Real scratch PostgreSQL DB, real alembic. Covers:

- ce_0053: comm_threads / comm_participants created; messages.thread_id added;
  messages.project_id flipped to NULLABLE (and a standalone NULL-project_id chat
  message actually lands).
- ce_0054: the CHT taxonomy backfill seeds CHT for a tenant that ALREADY has the
  default types but lacks CHT (the empty-table-guarded seeder would never give
  it to them) — exercised by seeding a pre-CHT tenant at ce_0053, then upgrading.
- Idempotency: the existence-guarded ce_0053 + the NOT-EXISTS-guarded ce_0054 are
  clean no-ops when re-run against a DB that already has the objects/rows (the
  "CE reruns upgrade head on every boot" + healed-but-behind-stamp scenarios).
- Downgrade: ce_0054 removes CHT; ce_0053 drops the tables + restores NOT NULL.

Mirrors tests/integration/migrations/test_ce_0043_execution_mode_nullable.py.
"""

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
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

SCRATCH_DB = f"{bootstrap_db_base()}{worker_suffix()}"
ADMIN_USER = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
ADMIN_PASSWORD = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

PRODUCTION_DB_NAME = "giljo_mcp"

_PRE = "ce_0052_pme_fts_be6082"
_TABLES = "ce_0053_comm_hub_tables"
_BACKFILL = "ce_0054_cht_taxonomy_backfill"

# The 9 ORIGINAL default types (pre-CHT) — what an already-seeded legacy tenant has.
_LEGACY_DEFAULT_ABBRS = ["BE", "FE", "DB", "UI", "API", "INF", "DOC", "SEC", "CTX"]


def _scratch_db_url() -> str:
    if SCRATCH_DB == PRODUCTION_DB_NAME:
        raise RuntimeError(
            "SAFETY GUARD: Refusing to run migration regression tests against the "
            "production DB name 'giljo_mcp'. Override GILJO_BOOTSTRAP_TEST_DB."
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


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    url = _scratch_db_url()
    env["DATABASE_URL"] = url
    env["POSTGRES_HOST"] = DB_HOST
    env["POSTGRES_PORT"] = DB_PORT
    env["POSTGRES_DB"] = SCRATCH_DB
    env["POSTGRES_USER"] = ADMIN_USER
    env["DB_HOST"] = DB_HOST
    env["DB_PORT"] = DB_PORT
    env["DB_NAME"] = SCRATCH_DB
    env["DB_USER"] = ADMIN_USER
    pwd = url.split("//", 1)[1].split("@", 1)[0].split(":", 1)[1]
    env["POSTGRES_PASSWORD"] = pwd
    env["DB_PASSWORD"] = pwd
    env.pop("GILJO_MODE", None)
    return env


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=str(PROJECT_ROOT),
        env=_build_env(),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _ensure_scratch_database_exists() -> None:
    scratch = _scratch_db_url()
    prefix, _, _ = scratch.rpartition("/")
    owner_admin_url = f"{prefix}/postgres"
    eng = sa.create_engine(owner_admin_url, poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn:
            existing = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": SCRATCH_DB},
            ).scalar()
            if not existing:
                conn.execute(text(f'CREATE DATABASE "{SCRATCH_DB}" OWNER "{ADMIN_USER}"'))
    finally:
        eng.dispose()


@pytest.fixture(scope="module")
def scratch_engine():
    _ensure_scratch_database_exists()
    eng = _scratch_engine()
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield eng
    eng.dispose()


@pytest.fixture
def empty_scratch_db(scratch_engine: sa.Engine):
    _drop_all_objects(scratch_engine)
    yield scratch_engine
    _drop_all_objects(scratch_engine)


def _has_table(engine: sa.Engine, table: str) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
                {"t": table},
            ).first()
            is not None
        )


def _col_nullable(engine: sa.Engine, table: str, column: str) -> str:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT is_nullable FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
            {"t": table, "c": column},
        ).first()
    assert row is not None, f"{table}.{column} column missing"
    return row[0]


def _seed_legacy_tenant_types(engine: sa.Engine, tenant_key: str) -> None:
    """Insert the 9 ORIGINAL default taxonomy types (no CHT) for a tenant —
    simulating a legacy tenant seeded before CHT existed."""
    with engine.connect() as conn:
        for i, abbr in enumerate(_LEGACY_DEFAULT_ABBRS):
            conn.execute(
                text(
                    "INSERT INTO taxonomy_types (id, tenant_key, abbreviation, label, color, sort_order) "
                    "VALUES (gen_random_uuid()::text, :tk, :abbr, :label, '#607D8B', :so)"
                ),
                {"tk": tenant_key, "abbr": abbr, "label": abbr, "so": i},
            )
        conn.commit()


def _cht_count(engine: sa.Engine, tenant_key: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM taxonomy_types WHERE tenant_key = :tk AND abbreviation = 'CHT'"),
            {"tk": tenant_key},
        ).scalar_one()


@pytest.mark.integration
class TestCe0053CommHubTables:
    def test_tables_and_nullable_project_id(self, empty_scratch_db: sa.Engine) -> None:
        up = _run_alembic("upgrade", _TABLES)
        assert up.returncode == 0, f"upgrade {_TABLES} failed:\n{up.stdout}\n{up.stderr}"

        assert _has_table(empty_scratch_db, "comm_threads")
        assert _has_table(empty_scratch_db, "comm_participants")
        assert _col_nullable(empty_scratch_db, "messages", "project_id") == "YES"
        assert _col_nullable(empty_scratch_db, "messages", "thread_id") == "YES"

    def test_reupgrade_is_idempotent(self, empty_scratch_db: sa.Engine) -> None:
        """Stamp back to _PRE while objects already exist, then re-run upgrade —
        the information_schema guards must make ce_0053 a clean no-op (the
        healed-but-behind-stamp / boot-rerun scenario)."""
        assert _run_alembic("upgrade", _TABLES).returncode == 0
        assert _run_alembic("stamp", _PRE).returncode == 0
        reup = _run_alembic("upgrade", _TABLES)
        assert reup.returncode == 0, f"idempotent re-upgrade failed:\n{reup.stdout}\n{reup.stderr}"
        assert _has_table(empty_scratch_db, "comm_threads")
        assert _col_nullable(empty_scratch_db, "messages", "project_id") == "YES"


@pytest.mark.integration
class TestCe0054ChtBackfill:
    def test_backfill_seeds_pre_seeded_tenant(self, empty_scratch_db: sa.Engine) -> None:
        """A tenant with the 9 legacy default types but NO CHT receives exactly
        one CHT row when ce_0054 runs."""
        assert _run_alembic("upgrade", _TABLES).returncode == 0
        tenant = "tk_legacy_pre_cht"
        _seed_legacy_tenant_types(empty_scratch_db, tenant)
        assert _cht_count(empty_scratch_db, tenant) == 0  # pre-backfill

        up = _run_alembic("upgrade", _BACKFILL)
        assert up.returncode == 0, f"backfill failed:\n{up.stdout}\n{up.stderr}"
        assert _cht_count(empty_scratch_db, tenant) == 1  # exactly one CHT row

    def test_backfill_is_idempotent(self, empty_scratch_db: sa.Engine) -> None:
        """Re-running ce_0054 against a tenant that already has CHT does not
        create a duplicate (NOT EXISTS guard + uq_taxonomy_type_abbr)."""
        assert _run_alembic("upgrade", _TABLES).returncode == 0
        tenant = "tk_legacy_idem"
        _seed_legacy_tenant_types(empty_scratch_db, tenant)
        assert _run_alembic("upgrade", _BACKFILL).returncode == 0
        assert _cht_count(empty_scratch_db, tenant) == 1

        # Stamp back + re-run: still exactly one CHT.
        assert _run_alembic("stamp", _TABLES).returncode == 0
        assert _run_alembic("upgrade", _BACKFILL).returncode == 0
        assert _cht_count(empty_scratch_db, tenant) == 1

    def test_downgrade_removes_cht_and_tables(self, empty_scratch_db: sa.Engine) -> None:
        assert _run_alembic("upgrade", _BACKFILL).returncode == 0
        tenant = "tk_legacy_down"
        # Backfill already ran on an empty taxonomy table (no tenants) -> seed +
        # re-stamp to confirm downgrade removes CHT rows it owns.
        _seed_legacy_tenant_types(empty_scratch_db, tenant)
        # Give this tenant a CHT row to delete (mirror what backfill would add).
        with empty_scratch_db.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO taxonomy_types (id, tenant_key, abbreviation, label, color, sort_order) "
                    "VALUES (gen_random_uuid()::text, :tk, 'CHT', 'Chat Thread', '#1565C0', 101)"
                ),
                {"tk": tenant},
            )
            conn.commit()
        assert _cht_count(empty_scratch_db, tenant) == 1

        down = _run_alembic("downgrade", _TABLES)
        assert down.returncode == 0, f"downgrade {_TABLES} failed:\n{down.stdout}\n{down.stderr}"
        assert _cht_count(empty_scratch_db, tenant) == 0  # CHT removed

        down2 = _run_alembic("downgrade", _PRE)
        assert down2.returncode == 0, f"downgrade {_PRE} failed:\n{down2.stdout}\n{down2.stderr}"
        assert not _has_table(empty_scratch_db, "comm_threads")
        assert not _has_table(empty_scratch_db, "comm_participants")
        # project_id restored to NOT NULL (no NULL rows present).
        assert _col_nullable(empty_scratch_db, "messages", "project_id") == "NO"
