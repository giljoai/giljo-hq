# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Migration regression for ce_0043_projects_execution_mode_nullable.

Verifies the execution-mode NULL-state migration against a real scratch
PostgreSQL DB:

1. Before ce_0043 (at ce_0042): ``projects.execution_mode`` is NOT NULL with a
   server default of ``'multi_terminal'``.
2. After ce_0043: the column is NULLABLE with NO server default, and a project
   inserted WITHOUT an execution_mode lands a real NULL (the "not yet selected"
   state) instead of a fabricated 'multi_terminal'.
3. Downgrade to ce_0042: any NULL row is backfilled to 'multi_terminal' BEFORE
   the NOT NULL constraint is re-imposed, and the server default is restored.
4. Re-upgrade is idempotent (column nullable + default-less again).

This is the failing-layer regression for the NULL-state redesign at the schema
layer (CLAUDE.md mandate). Mirrors tests/integration/migrations/
test_ce_0033_vision_analysis_complete.py.
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

_PRE = "ce_0042_staged_agent_mailboxes"
_TARGET = "ce_0043_projects_execution_mode_nullable"


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


def _column_meta(engine: sa.Engine) -> tuple[str, str | None]:
    """Return (is_nullable, column_default) for projects.execution_mode."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'projects' AND column_name = 'execution_mode'"
            )
        ).first()
    assert row is not None, "projects.execution_mode column missing"
    return row[0], row[1]


def _insert_project(engine: sa.Engine, *, pid: str, execution_mode: str | None, set_mode: bool) -> None:
    """Insert a minimal project (plus its required parent product). When set_mode
    is False, execution_mode is omitted entirely so the column default
    (post-ce_0043: none -> NULL) decides what lands."""
    product_id = pid + "-prod"
    cols = ["id", "tenant_key", "product_id", "name", "alias", "description", "mission"]
    placeholders = [":id", ":tenant_key", ":product_id", ":name", ":alias", ":description", ":mission"]
    params: dict[str, str | None] = {
        "id": pid,
        "tenant_key": "tk_" + pid,
        "product_id": product_id,
        "name": "ce0043 " + pid,
        # alias is varchar(6); each test inserts ONE project into its own reset
        # scratch DB, so a constant short alias is collision-free.
        "alias": "proj01",
        "description": "x",
        "mission": "x",
    }
    if set_mode:
        cols.append("execution_mode")
        placeholders.append(":execution_mode")
        params["execution_mode"] = execution_mode
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO products (id, tenant_key, name, is_active) VALUES (:id, :tk, :name, FALSE)"),
            {"id": product_id, "tk": "tk_" + pid, "name": "ce0043 product " + pid},
        )
        conn.execute(
            text(f"INSERT INTO projects ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"),
            params,
        )
        conn.commit()


def _mode_value(engine: sa.Engine, pid: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT execution_mode FROM projects WHERE id = :id"),
            {"id": pid},
        ).first()
    assert row is not None, f"project row {pid} missing"
    return row[0]


@pytest.mark.integration
class TestCe0043ExecutionModeNullable:
    def test_fresh_chain_head_is_nullable_no_default(self, empty_scratch_db: sa.Engine) -> None:
        """A fresh chain (baseline parity) lands at nullable + no default, and a
        default-less insert produces a real NULL (the 'not yet selected' state).

        Note: the baseline already creates the column nullable (baseline parity
        with ce_0043), so on a fresh chain ce_0043 is an idempotent no-op — that
        no-op is itself part of the contract under test (it must not error)."""
        up = _run_alembic("upgrade", _TARGET)
        assert up.returncode == 0, f"upgrade {_TARGET} failed:\n{up.stdout}\n{up.stderr}"

        is_nullable, default = _column_meta(empty_scratch_db)
        assert is_nullable == "YES", "post-ce_0043 execution_mode must be NULLABLE"
        assert default is None, f"post-ce_0043 execution_mode must have NO default, got {default!r}"

        # A project inserted without a mode lands a real NULL (not 'multi_terminal').
        _insert_project(empty_scratch_db, pid="ce0043-nomode", execution_mode=None, set_mode=False)
        assert _mode_value(empty_scratch_db, "ce0043-nomode") is None

    def test_downgrade_restores_not_null_and_reupgrade_alters_back(self, empty_scratch_db: sa.Engine) -> None:
        """Exercises the REAL legacy-DB ALTER path that existing prod DBs hit.

        downgrade() forces the column back to NOT NULL + default 'multi_terminal'
        (backfilling any NULL rows first); the subsequent re-upgrade then runs the
        genuine NOT NULL -> nullable ALTER (the path an existing prod DB created
        from the old baseline takes), proving ce_0043's upgrade() converts a
        legacy column, not just no-ops a fresh one."""
        assert _run_alembic("upgrade", _TARGET).returncode == 0

        # A NULL-mode row (only possible post-ce_0043) must survive downgrade by
        # being backfilled to the legacy default before NOT NULL is re-imposed.
        _insert_project(empty_scratch_db, pid="ce0043-null", execution_mode=None, set_mode=True)
        assert _mode_value(empty_scratch_db, "ce0043-null") is None

        down = _run_alembic("downgrade", _PRE)
        assert down.returncode == 0, f"downgrade {_PRE} failed:\n{down.stdout}\n{down.stderr}"

        is_nullable, default = _column_meta(empty_scratch_db)
        assert is_nullable == "NO", "post-downgrade execution_mode must be NOT NULL (legacy shape)"
        assert default is not None and "multi_terminal" in default
        assert _mode_value(empty_scratch_db, "ce0043-null") == "multi_terminal", (
            "downgrade must backfill NULL rows to 'multi_terminal' before re-imposing NOT NULL"
        )

        # Re-upgrade now runs the genuine NOT NULL+default -> nullable ALTER.
        reup = _run_alembic("upgrade", _TARGET)
        assert reup.returncode == 0, f"re-upgrade failed:\n{reup.stdout}\n{reup.stderr}"
        is_nullable, default = _column_meta(empty_scratch_db)
        assert is_nullable == "YES", "re-upgrade must ALTER a legacy NOT NULL column back to nullable"
        assert default is None, "re-upgrade must drop the restored server default"
