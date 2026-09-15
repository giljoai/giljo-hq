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

_PRE = "ce_0087_comm_threads_sequence_run_fk"
_REV = "ce_0088_backfill_project_completed_at"

TK = "tk_ce0088"
PRODUCT_ID = "ce008800-0000-4000-8000-000000000001"

CLOSEOUT_TS = "2026-07-01 10:00:00+00"
DRIFTED_UPDATED_TS = "2026-07-20 23:59:00+00"
NO_CLOSEOUT_UPDATED_TS = "2026-07-02 11:30:00+00"
PRESET_COMPLETED_TS = "2026-06-01 09:09:09+00"


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
def scratch_at_pre(scratch_engine: sa.Engine):
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    _seed_product(scratch_engine)
    yield scratch_engine
    _drop_all_objects(scratch_engine)




def _seed_product(engine: sa.Engine) -> None:
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO products (id, name, description, tenant_key, is_active, created_at, updated_at) "
                "VALUES (:id, 'ce_0088 product', 'migration test', :tk, false, now(), now())"
            ),
            {"id": PRODUCT_ID, "tk": TK},
        )
        conn.commit()


def _seed_project(
    engine: sa.Engine,
    project_id: str,
    *,
    status: str,
    series: int,
    updated_at: str,
    closeout_executed_at: str | None = None,
    completed_at: str | None = None,
) -> None:
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO projects "
                "(id, alias, tenant_key, product_id, name, description, mission, status, series_number, "
                " created_at, updated_at, closeout_executed_at, completed_at) "
                "VALUES (:id, :alias, :tk, :pd, :id, 'ce_0088 row', 'ce_0088 mission', "
                " CAST(:st AS project_status), :sn, '2026-06-01 00:00:00+00', "
                " CAST(:up AS timestamptz), CAST(:co AS timestamptz), CAST(:cp AS timestamptz))"
            ),
            {
                "id": project_id,
                "alias": f"C88{series:03d}",
                "tk": TK,
                "pd": PRODUCT_ID,
                "st": status,
                "sn": series,
                "up": updated_at,
                "co": closeout_executed_at,
                "cp": completed_at,
            },
        )
        conn.commit()


def _completed_at(engine: sa.Engine, project_id: str):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT completed_at FROM projects WHERE id = :id"),
            {"id": project_id},
        ).scalar()


def _as_utc_text(engine: sa.Engine, project_id: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') FROM projects WHERE id = :id"
            ),
            {"id": project_id},
        ).scalar()


@pytest.mark.integration
class TestCe0088CompletedAtBackfill:

    def test_a_closed_out_project_takes_its_exact_closeout_timestamp(self, scratch_at_pre: sa.Engine) -> None:
        _seed_project(
            scratch_at_pre,
            "p_closed_out",
            status="completed",
            series=1,
            updated_at=DRIFTED_UPDATED_TS,
            closeout_executed_at=CLOSEOUT_TS,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _as_utc_text(scratch_at_pre, "p_closed_out") == "2026-07-01 10:00:00", (
            "the backfill took the drifted updated_at instead of the exact closeout stamp"
        )

    def test_a_project_with_no_closeout_falls_back_to_updated_at(self, scratch_at_pre: sa.Engine) -> None:
        _seed_project(
            scratch_at_pre,
            "p_no_closeout",
            status="completed",
            series=2,
            updated_at=NO_CLOSEOUT_UPDATED_TS,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _as_utc_text(scratch_at_pre, "p_no_closeout") == "2026-07-02 11:30:00"

    @pytest.mark.parametrize(
        ("status", "series"),
        [("cancelled", 3), ("terminated", 4), ("superseded", 5), ("deleted", 6)],
    )
    def test_every_terminal_status_is_backfilled_not_just_completed(
        self, scratch_at_pre: sa.Engine, status: str, series: int
    ) -> None:
        _seed_project(
            scratch_at_pre,
            f"p_{status}",
            status=status,
            series=series,
            updated_at=NO_CLOSEOUT_UPDATED_TS,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _completed_at(scratch_at_pre, f"p_{status}") is not None, (
            f"'{status}' is a lifecycle-finished status and must be backfilled"
        )

    @pytest.mark.parametrize(
        ("status", "series"),
        [("active", 7), ("inactive", 8), ("parked", 9)],
    )
    def test_a_non_terminal_project_is_never_stamped(self, scratch_at_pre: sa.Engine, status: str, series: int) -> None:
        _seed_project(
            scratch_at_pre,
            f"p_{status}",
            status=status,
            series=series,
            updated_at=NO_CLOSEOUT_UPDATED_TS,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _completed_at(scratch_at_pre, f"p_{status}") is None, (
            f"'{status}' is not a finished state and must not receive a completion date"
        )

    def test_an_existing_completed_at_is_never_rewritten(self, scratch_at_pre: sa.Engine) -> None:
        _seed_project(
            scratch_at_pre,
            "p_already_dated",
            status="completed",
            series=10,
            updated_at=DRIFTED_UPDATED_TS,
            completed_at=PRESET_COMPLETED_TS,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _as_utc_text(scratch_at_pre, "p_already_dated") == "2026-06-01 09:09:09"

    def test_a_replay_of_the_revision_moves_nothing(self, scratch_at_pre: sa.Engine) -> None:
        _seed_project(
            scratch_at_pre,
            "p_replay",
            status="completed",
            series=11,
            updated_at=DRIFTED_UPDATED_TS,
            closeout_executed_at=CLOSEOUT_TS,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"
        after_first = _as_utc_text(scratch_at_pre, "p_replay")

        with scratch_at_pre.connect() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = :pre"), {"pre": _PRE})
            conn.commit()

        again = _run_alembic("upgrade", _REV)
        assert again.returncode == 0, f"re-run of {_REV} failed:\n{again.stdout}\n{again.stderr}"

        assert _as_utc_text(scratch_at_pre, "p_replay") == after_first, (
            "a second run of the backfill changed an already-filled row"
        )
