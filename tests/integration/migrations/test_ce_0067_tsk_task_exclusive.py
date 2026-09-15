# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

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

_PRE = "ce_0066_users_token_revocation_epoch"
_REV = "ce_0067_tsk_task_exclusive"


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
    yield scratch_engine
    _drop_all_objects(scratch_engine)



TK = "tk_imp6262"
PID = "prod_imp6262"


def _seed_base(engine: sa.Engine) -> dict[str, str]:
    ids = {"TSK": str(uuid4()), "BE": str(uuid4()), "FE": str(uuid4())}
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO products (id, tenant_key, name, is_active) VALUES (:id, :tk, :name, true)"),
            {"id": PID, "tk": TK, "name": "IMP-6262 test product"},
        )
        for abbr, tid in ids.items():
            conn.execute(
                text(
                    "INSERT INTO taxonomy_types (id, tenant_key, abbreviation, label, color, sort_order) "
                    "VALUES (:id, :tk, :abbr, :label, '#607D8B', 1)"
                ),
                {"id": tid, "tk": TK, "abbr": abbr, "label": abbr},
            )
        conn.commit()
    return ids


def _seed_task(engine: sa.Engine, title: str, type_id: str | None, series: int | None) -> str:
    tid = str(uuid4())
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO tasks (id, tenant_key, product_id, title, task_type_id, series_number, status) "
                "VALUES (:id, :tk, :pid, :title, :ttid, :s, 'pending')"
            ),
            {"id": tid, "tk": TK, "pid": PID, "title": title, "ttid": type_id, "s": series},
        )
        conn.commit()
    return tid


def _seed_project(engine: sa.Engine, name: str, type_id: str | None, series: int | None) -> str:
    pid = str(uuid4())
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, tenant_key, product_id, name, description, mission, "
                "alias, project_type_id, series_number) "
                "VALUES (:id, :tk, :pid, :name, 'd', '', :alias, :ptid, :s)"
            ),
            {"id": pid, "tk": TK, "pid": PID, "name": name, "alias": str(uuid4())[:6], "ptid": type_id, "s": series},
        )
        conn.commit()
    return pid


def _task_row(engine: sa.Engine, task_id: str) -> sa.Row:
    with engine.connect() as conn:
        return conn.execute(text("SELECT task_type_id, series_number FROM tasks WHERE id = :id"), {"id": task_id}).one()


def _project_row(engine: sa.Engine, project_id: str) -> sa.Row:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT project_type_id, series_number FROM projects WHERE id = :id"), {"id": project_id}
        ).one()


@pytest.mark.integration
class TestCe0067TskTaskExclusive:
    def test_legacy_nontsk_task_retyped_to_tsk_keeps_serial(self, scratch_at_pre: sa.Engine) -> None:
        ids = _seed_base(scratch_at_pre)
        task_id = _seed_task(scratch_at_pre, "BE-6080 task", ids["BE"], 6080)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        type_id, series = _task_row(scratch_at_pre, task_id)
        assert type_id == ids["TSK"], "legacy BE task must be re-typed to TSK"
        assert series == 6080, "no collision → original serial preserved"

    def test_serial_collision_two_tasks_get_distinct_serials(self, scratch_at_pre: sa.Engine) -> None:
        ids = _seed_base(scratch_at_pre)
        t_be = _seed_task(scratch_at_pre, "BE-0019", ids["BE"], 19)
        t_fe = _seed_task(scratch_at_pre, "FE-0019", ids["FE"], 19)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        be_type, be_series = _task_row(scratch_at_pre, t_be)
        fe_type, fe_series = _task_row(scratch_at_pre, t_fe)
        assert be_type == ids["TSK"] and fe_type == ids["TSK"], "both must be TSK-typed"
        assert be_series != fe_series, "colliding serials must be split apart"
        assert {be_series, fe_series} == {19, 20}, "one keeps 19, the other bumps to the watermark+1"

    def test_tsk_typed_project_is_untyped(self, scratch_at_pre: sa.Engine) -> None:
        ids = _seed_base(scratch_at_pre)
        proj_id = _seed_project(scratch_at_pre, "was a task", ids["TSK"], 100)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        type_id, series = _project_row(scratch_at_pre, proj_id)
        assert type_id is None, "TSK-typed project must be un-typed to NULL"
        assert series == 100, "serial preserved"

    def test_rerun_is_idempotent(self, scratch_at_pre: sa.Engine) -> None:
        ids = _seed_base(scratch_at_pre)
        task_id = _seed_task(scratch_at_pre, "BE-6080 task", ids["BE"], 6080)

        assert _run_alembic("upgrade", _REV).returncode == 0
        first = _task_row(scratch_at_pre, task_id)

        assert _run_alembic("stamp", _PRE).returncode == 0
        reup = _run_alembic("upgrade", _REV)
        assert reup.returncode == 0, f"idempotent re-upgrade failed:\n{reup.stdout}\n{reup.stderr}"
        assert _task_row(scratch_at_pre, task_id) == first, "second run must be a no-op"
