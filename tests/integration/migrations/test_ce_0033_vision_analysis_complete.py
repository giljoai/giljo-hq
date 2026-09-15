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


def _upgrade_to_pre_ce_0033(scratch_engine: sa.Engine) -> None:
    result = _run_alembic("upgrade", "ce_0032_vision_docs_inline_only")
    assert result.returncode == 0, (
        f"alembic upgrade ce_0032 failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def _insert_product(
    engine: sa.Engine,
    *,
    pid: str,
    consolidated_light: str | None,
    consolidated_medium: str | None,
) -> None:
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO products "
                "(id, tenant_key, name, is_active, consolidated_vision_light, consolidated_vision_medium) "
                "VALUES (:pid, :tk, :name, FALSE, :light, :medium)"
            ),
            {
                "pid": pid,
                "tk": "tk_" + pid,
                "name": "be5117 " + pid,
                "light": consolidated_light,
                "medium": consolidated_medium,
            },
        )
        conn.commit()


def _column_value(engine: sa.Engine, pid: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT vision_analysis_complete FROM products WHERE id = :id"),
            {"id": pid},
        ).first()
    assert row is not None, f"product row {pid} missing"
    return bool(row[0])


def _column_exists(engine: sa.Engine) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'products' AND column_name = 'vision_analysis_complete'"
            )
        ).first()
    return row is not None


@pytest.mark.integration
class TestCe0033Migration:
    def test_legacy_consolidated_rows_backfill_to_true(self, empty_scratch_db: sa.Engine) -> None:
        _upgrade_to_pre_ce_0033(empty_scratch_db)
        _insert_product(
            empty_scratch_db,
            pid="be5117-legacy",
            consolidated_light="legacy light",
            consolidated_medium="legacy medium",
        )

        upgrade = _run_alembic("upgrade", "ce_0033_vision_analysis_complete")
        assert upgrade.returncode == 0, (
            f"alembic upgrade ce_0033 failed:\nSTDOUT:\n{upgrade.stdout}\nSTDERR:\n{upgrade.stderr}"
        )

        assert _column_value(empty_scratch_db, "be5117-legacy") is True

    def test_rows_without_consolidated_summaries_remain_false(self, empty_scratch_db: sa.Engine) -> None:
        _upgrade_to_pre_ce_0033(empty_scratch_db)
        _insert_product(
            empty_scratch_db,
            pid="be5117-empty",
            consolidated_light=None,
            consolidated_medium=None,
        )

        upgrade = _run_alembic("upgrade", "ce_0033_vision_analysis_complete")
        assert upgrade.returncode == 0, (
            f"alembic upgrade ce_0033 failed:\nSTDOUT:\n{upgrade.stdout}\nSTDERR:\n{upgrade.stderr}"
        )

        assert _column_value(empty_scratch_db, "be5117-empty") is False

    def test_downgrade_drops_column_and_upgrade_is_idempotent(self, empty_scratch_db: sa.Engine) -> None:
        _upgrade_to_pre_ce_0033(empty_scratch_db)
        _insert_product(
            empty_scratch_db,
            pid="be5117-roundtrip",
            consolidated_light="legacy light",
            consolidated_medium="legacy medium",
        )

        upgrade = _run_alembic("upgrade", "ce_0033_vision_analysis_complete")
        assert upgrade.returncode == 0, upgrade.stderr
        assert _column_exists(empty_scratch_db)

        downgrade = _run_alembic("downgrade", "ce_0032_vision_docs_inline_only")
        assert downgrade.returncode == 0, downgrade.stderr
        assert not _column_exists(empty_scratch_db)

        reupgrade = _run_alembic("upgrade", "ce_0033_vision_analysis_complete")
        assert reupgrade.returncode == 0, reupgrade.stderr
        assert _column_exists(empty_scratch_db)
        assert _column_value(empty_scratch_db, "be5117-roundtrip") is True
