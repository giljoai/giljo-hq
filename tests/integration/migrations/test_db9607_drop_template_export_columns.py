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
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

SCRATCH_DB = f"{bootstrap_db_base()}{worker_suffix()}"
ADMIN_USER = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
ADMIN_PASSWORD = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

PRODUCTION_DB_NAME = "giljo_mcp"

_REV = "ce_0105_db9607_drop_template_export_columns"
_PRE = "ce_0104_be9610a_product_owned_agent_copies"

_DROPPED = (
    ("agent_templates", "last_exported_at"),
    ("agent_templates", "user_managed_export"),
    ("product_agent_assignments", "last_exported_at"),
)


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


def _run_boot_stamp_seam() -> subprocess.CompletedProcess[str]:
    code = (
        "import sys, os; "
        "sys.path.insert(0, os.getcwd()); "
        "from startup_support.migration_stamp import _check_and_stamp_migration_version as f; "
        "f()"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
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
    eng = sa.create_engine(f"{prefix}/postgres", poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT")
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


def _columns_present(engine: sa.Engine) -> set[tuple[str, str]]:
    insp = sa.inspect(engine)
    tables = set(insp.get_table_names())
    return {
        (table, column)
        for table, column in _DROPPED
        if table in tables and any(c["name"] == column for c in insp.get_columns(table))
    }


@pytest.fixture(scope="module")
def scratch_engine():
    _ensure_scratch_database_exists()
    eng = _scratch_engine()
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield eng
    eng.dispose()


@pytest.mark.integration
def test_heal_then_upgrade_ends_with_the_columns_gone(scratch_engine):
    _drop_all_objects(scratch_engine)

    built = _run_alembic("upgrade", "baseline_v37")
    assert built.returncode == 0, f"build to baseline_v37 failed:\n{built.stdout}\n{built.stderr}"
    with scratch_engine.connect() as conn:
        conn.execute(text("ALTER TABLE agent_templates DROP COLUMN IF EXISTS user_managed_export"))
        conn.execute(text("UPDATE alembic_version SET version_num = 'baseline_v36'"))
        conn.commit()
    assert ("agent_templates", "user_managed_export") not in _columns_present(scratch_engine)

    healed = _run_boot_stamp_seam()

    assert healed.returncode == 0, f"boot seam failed:\n{healed.stdout}\n{healed.stderr}"
    with scratch_engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "baseline_v37"
    assert ("agent_templates", "user_managed_export") in _columns_present(scratch_engine), (
        "the heal pass did not restore the v37 shape -- ce_0105 would then be dropping "
        "a column the seam never re-added, and the chain order claim is wrong"
    )

    upgraded = _run_alembic("upgrade", "head")

    assert upgraded.returncode == 0, f"chain replay failed:\n{upgraded.stdout}\n{upgraded.stderr}"
    assert _columns_present(scratch_engine) == set(), (
        f"export-tracking columns survived a heal-then-upgrade boot: {sorted(_columns_present(scratch_engine))}"
    )


@pytest.mark.integration
def test_upgrade_is_a_no_op_on_rerun(scratch_engine):
    _drop_all_objects(scratch_engine)
    built = _run_alembic("upgrade", _REV)
    assert built.returncode == 0, f"chain build failed:\n{built.stdout}\n{built.stderr}"
    assert _columns_present(scratch_engine) == set()

    stamped = _run_alembic("stamp", _PRE)
    assert stamped.returncode == 0, f"stamp back failed:\n{stamped.stderr}"
    rerun = _run_alembic("upgrade", _REV)

    assert rerun.returncode == 0, f"re-running the drop over an already-dropped schema failed:\n{rerun.stderr}"
    assert _columns_present(scratch_engine) == set()
    with scratch_engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == _REV


@pytest.mark.integration
def test_downgrade_restores_all_three_nullable(scratch_engine):
    _drop_all_objects(scratch_engine)
    built = _run_alembic("upgrade", _REV)
    assert built.returncode == 0, f"chain build failed:\n{built.stdout}\n{built.stderr}"

    down = _run_alembic("downgrade", "-1")

    assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"
    assert _columns_present(scratch_engine) == set(_DROPPED)
    insp = sa.inspect(scratch_engine)
    for table, column in _DROPPED:
        col = next(c for c in insp.get_columns(table) if c["name"] == column)
        assert col["nullable"], f"{table}.{column} came back NOT NULL; the downgrade cannot honour that honestly"

    up = _run_alembic("upgrade", _REV)
    assert up.returncode == 0, f"re-upgrade after downgrade failed:\n{up.stderr}"
    assert _columns_present(scratch_engine) == set()
