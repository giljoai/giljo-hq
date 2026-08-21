# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Migration regression for ce_0072_bus_retirement_fold_and_fk (BE-9012d, D8+D10).

The failing layer is the SCHEMA/migration layer, so this runs the REAL alembic
chain against a scratch PostgreSQL DB (model create_all can't exercise a data
backfill, and asserts here prove the actual upgrade folds + alters correctly).

Covered:

- D8 fold precedence (the resolver contract the shims + D1(a) also use): a project
  with bus rows but NO thread gets ONE marker thread minted; a project with an
  ORGANIC bound thread reuses it (no duplicate); a project with several threads
  folds into the marker one; town-square rows are untouched.
- D10 FK: after upgrade, comm_threads.project_id is ON DELETE CASCADE ('c') and a
  genuine project purge cascade-deletes the bound thread (was orphaned under the
  old SET NULL).
- Idempotency / reversibility: downgrade restores SET NULL, re-upgrade restores
  CASCADE and re-running the fold mints no duplicate threads.

Mirrors tests/integration/migrations/test_ce_0069_index_dedup_fk_cascade.py.
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

_PRE = "ce_0071_agent_todo_item_kind"
_TARGET = "ce_0072_bus_retirement_fold_and_fk"
_MARKER = "(project comms)"


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
    pwd = url.split("//", 1)[1].split("@", 1)[0].split(":", 1)[1]
    env["POSTGRES_PASSWORD"] = pwd
    env.pop("GILJO_MODE", None)  # CE chain
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


# --------------------------------------------------------------------------- #
# Seed helpers (raw SQL — the ORM isn't importable against a bare scratch DB)
# --------------------------------------------------------------------------- #

_TK = "tk_ce0072"


def _seed(conn, sql: str, **params) -> None:
    conn.execute(text(sql), params)


def _mk_product(conn) -> None:
    _seed(conn, "INSERT INTO products (id, tenant_key, name, is_active) VALUES ('prod1', :tk, 'P', true)", tk=_TK)


def _mk_project(conn, pid: str, series: int) -> None:
    # projects.alias is varchar(6); uq_project_taxonomy_active needs distinct series.
    _seed(
        conn,
        "INSERT INTO projects (id, tenant_key, product_id, name, alias, description, mission, series_number) "
        "VALUES (:id, :tk, 'prod1', 'n', :alias, 'd', 'm', :s)",
        id=pid,
        tk=_TK,
        alias=f"P{series:05d}",
        s=series,
    )


def _mk_thread(conn, tid: str, pid: str | None, serial: int, subject: str, created: str) -> None:
    _seed(
        conn,
        "INSERT INTO comm_threads (id, tenant_key, serial, subject, status, product_id, project_id, created_at) "
        "VALUES (:id, :tk, :serial, :subject, 'open', 'prod1', :pid, :created)",
        id=tid,
        tk=_TK,
        serial=serial,
        subject=subject,
        pid=pid,
        created=created,
    )


def _mk_bus(conn, mid: str, pid: str) -> None:
    _seed(
        conn,
        "INSERT INTO messages (id, tenant_key, content, project_id, thread_id) VALUES (:id, :tk, :c, :pid, NULL)",
        id=mid,
        tk=_TK,
        c="bus " + mid,
        pid=pid,
    )


def _scalar(engine: sa.Engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _fk_deltype(engine: sa.Engine) -> str | None:
    return _scalar(
        engine,
        "SELECT confdeltype FROM pg_constraint "
        "WHERE conrelid = 'comm_threads'::regclass AND contype = 'f' "
        "AND conkey = (SELECT array_agg(attnum) FROM pg_attribute "
        "  WHERE attrelid = 'comm_threads'::regclass AND attname = 'project_id')",
    )


@pytest.mark.integration
class TestCe0072BusRetirement:
    def test_fold_precedence_and_fk_and_cascade(self, empty_scratch_db: sa.Engine) -> None:
        """One upgrade covers: create-new, organic-reuse, marker-precedence, town
        untouched, FK -> CASCADE, and a functional project-purge cascade."""
        assert _run_alembic("upgrade", _PRE).returncode == 0
        eng = empty_scratch_db
        with eng.connect() as conn:
            _mk_product(conn)
            # A: create-new (3 bus rows, no thread)
            _mk_project(conn, "pA", 1)
            for i in range(3):
                _mk_bus(conn, f"a{i}", "pA")
            # B: organic reuse (2 bus rows + 1 organic thread, no marker)
            _mk_project(conn, "pB", 2)
            _mk_thread(conn, "tB", "pB", 201, "Chain hub", "2026-01-01")
            for i in range(2):
                _mk_bus(conn, f"b{i}", "pB")
            # C: several, marker present (1 bus row + marker + older organic)
            _mk_project(conn, "pC", 3)
            _mk_thread(conn, "tC_org", "pC", 202, "Older hub", "2026-01-01")
            _mk_thread(conn, "tC_mark", "pC", 203, _MARKER, "2026-02-01")
            _mk_bus(conn, "c0", "pC")
            # Town square (no project) — must be untouched
            _mk_thread(conn, "tTown", None, 204, "town", "2026-01-01")
            _seed(
                conn,
                "INSERT INTO messages (id, tenant_key, content, project_id, thread_id) "
                "VALUES ('town0', :tk, 't', NULL, 'tTown')",
                tk=_TK,
            )
            conn.commit()

        up = _run_alembic("upgrade", _TARGET)
        assert up.returncode == 0, f"upgrade {_TARGET} failed:\n{up.stdout}\n{up.stderr}"

        # D8 fold
        assert _scalar(eng, "SELECT count(*) FROM messages WHERE thread_id IS NULL AND project_id IS NOT NULL") == 0
        assert _scalar(eng, "SELECT count(*) FROM comm_threads WHERE project_id='pA'") == 1
        assert _scalar(eng, "SELECT subject FROM comm_threads WHERE project_id='pA'") == _MARKER
        a_tid = _scalar(eng, "SELECT id FROM comm_threads WHERE project_id='pA'")
        assert _scalar(eng, "SELECT count(*) FROM messages WHERE project_id='pA' AND thread_id=:t", t=a_tid) == 3
        assert _scalar(eng, "SELECT count(*) FROM comm_threads WHERE project_id='pB'") == 1  # organic reused
        assert _scalar(eng, "SELECT count(*) FROM messages WHERE project_id='pB' AND thread_id='tB'") == 2
        assert _scalar(eng, "SELECT thread_id FROM messages WHERE id='c0'") == "tC_mark"  # marker precedence
        assert _scalar(eng, "SELECT count(*) FROM comm_threads WHERE project_id='pC'") == 2  # no dup minted
        assert _scalar(eng, "SELECT thread_id FROM messages WHERE id='town0'") == "tTown"  # untouched

        # D10 FK + functional cascade
        assert _fk_deltype(eng) == "c", "comm_threads.project_id must be ON DELETE CASCADE after ce_0072"
        with eng.connect() as conn:
            conn.execute(text("DELETE FROM messages WHERE project_id='pA'"))  # nuclear_delete order
            conn.execute(text("DELETE FROM projects WHERE id='pA'"))
            conn.commit()
        assert _scalar(eng, "SELECT count(*) FROM comm_threads WHERE id=:t", t=a_tid) == 0, (
            "bound thread must CASCADE on project purge"
        )
        assert _scalar(eng, "SELECT count(*) FROM comm_threads WHERE project_id IS NULL AND id=:t", t=a_tid) == 0, (
            "thread must not be orphaned into the town square (the old SET NULL bug)"
        )

    def test_downgrade_restores_set_null_reup_is_idempotent(self, empty_scratch_db: sa.Engine) -> None:
        """downgrade -> SET NULL; re-upgrade -> CASCADE again and no duplicate
        threads (the fold re-runs on already-folded data as a no-op)."""
        assert _run_alembic("upgrade", _PRE).returncode == 0
        eng = empty_scratch_db
        with eng.connect() as conn:
            _mk_product(conn)
            _mk_project(conn, "pA", 1)
            for i in range(3):
                _mk_bus(conn, f"a{i}", "pA")
            conn.commit()

        assert _run_alembic("upgrade", _TARGET).returncode == 0
        assert _fk_deltype(eng) == "c"
        threads_after_upgrade = _scalar(eng, "SELECT count(*) FROM comm_threads")

        assert _run_alembic("downgrade", "-1").returncode == 0
        assert _fk_deltype(eng) == "n", "downgrade must restore ON DELETE SET NULL"

        reup = _run_alembic("upgrade", _TARGET)
        assert reup.returncode == 0, f"re-upgrade failed:\n{reup.stdout}\n{reup.stderr}"
        assert _fk_deltype(eng) == "c", "re-upgrade must restore CASCADE"
        assert _scalar(eng, "SELECT count(*) FROM comm_threads") == threads_after_upgrade, (
            "re-running the fold must not mint duplicate threads (idempotent via thread_id IS NULL guard)"
        )
