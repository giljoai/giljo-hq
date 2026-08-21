# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Migration regression for BE-9431 — ``uq_task_taxonomy_active`` gets its teeth back.

Real scratch PostgreSQL DB, real alembic. ``ce_0059`` rewrote this index as
``op.create_index(...)`` kwargs while widening its predicate and silently lost
``NULLS NOT DISTINCT``; since ``subseries`` is NULL on ordinary rows, the index
then rejected nothing for the common case. ``ce_0095`` restores the flag, and
must HEAL any database already holding duplicates first — the CE installer
reruns ``alembic upgrade`` on every boot, so a migration that merely tried to
build the strict index would brick a self-hoster's boot with no operator around
to clean the data up.

The four things this pins:

- **The defect is real, at the pre-revision.** A duplicate live typed serial
  INSERTs successfully at ce_0094. This is the discriminating control: without
  it, every assertion below would also pass against an index that was strict all
  along, and the test would prove nothing.
- **The upgrade heals rather than fails.** Two colliding rows both survive, live,
  with DISTINCT serials taken from the shared tasks+projects watermark.
- **The index is strict afterwards** (``indnullsnotdistinct``) and actually
  REJECTS a fresh duplicate — the property, not just the catalog flag.
- **Idempotent.** The boot-rerun path is a clean no-op.

Mirrors tests/integration/migrations/test_ce_0067_tsk_task_exclusive.py, whose
reassign-above-the-watermark healing ce_0095 follows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.helpers.test_db_helper import bootstrap_db_base, worker_suffix


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

SCRATCH_DB = f"{bootstrap_db_base()}{worker_suffix()}"
ADMIN_USER = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
ADMIN_PASSWORD = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

PRODUCTION_DB_NAME = "giljo_mcp"

_PRE = "ce_0094_per_product_export_staleness"
_REV = "ce_0095_be9431_task_index_nnd"
_INDEX = "uq_task_taxonomy_active"


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
    """Fresh schema built up to ce_0094 (the pre-revision), ready for seeding."""
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    yield scratch_engine
    _drop_all_objects(scratch_engine)


# --------------------------------------------------------------------------- #
# Seed helpers (raw SQL — the ORM models are not needed for a migration test)  #
# --------------------------------------------------------------------------- #

TK = "tk_be9431"
PID = "prod_be9431"


def _seed_base(engine: sa.Engine) -> str:
    """Seed a product + one taxonomy type; return the type id."""
    type_id = str(uuid4())
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO products (id, tenant_key, name, is_active) VALUES (:id, :tk, :name, true)"),
            {"id": PID, "tk": TK, "name": "BE-9431 test product"},
        )
        conn.execute(
            text(
                "INSERT INTO taxonomy_types (id, tenant_key, abbreviation, label, color, sort_order) "
                "VALUES (:id, :tk, 'TSK', 'Task', '#8b5cf6', 100)"
            ),
            {"id": type_id, "tk": TK},
        )
        conn.commit()
    return type_id


def _seed_task(
    engine: sa.Engine,
    title: str,
    type_id: str | None,
    series: int | None,
    *,
    trashed: bool = False,
) -> str:
    """INSERT a task directly. Raises IntegrityError if an index refuses it."""
    task_id = str(uuid4())
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO tasks (id, tenant_key, product_id, title, task_type_id, series_number, "
                "status, deleted_at) "
                "VALUES (:id, :tk, :pid, :title, :ttid, :s, 'pending', "
                "CASE WHEN :trashed THEN CURRENT_TIMESTAMP ELSE NULL END)"
            ),
            {"id": task_id, "tk": TK, "pid": PID, "title": title, "ttid": type_id, "s": series, "trashed": trashed},
        )
        conn.commit()
    return task_id


def _seed_project(engine: sa.Engine, name: str, series: int | None) -> str:
    project_id = str(uuid4())
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, tenant_key, product_id, name, description, mission, "
                "alias, project_type_id, series_number) "
                "VALUES (:id, :tk, :pid, :name, 'd', '', :alias, NULL, :s)"
            ),
            {"id": project_id, "tk": TK, "pid": PID, "name": name, "alias": str(uuid4())[:6], "s": series},
        )
        conn.commit()
    return project_id


def _task_row(engine: sa.Engine, task_id: str) -> sa.Row:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT series_number, subseries, deleted_at FROM tasks WHERE id = :id"),
            {"id": task_id},
        ).one()


def _index_is_strict(engine: sa.Engine) -> bool | None:
    """``pg_index.indnullsnotdistinct`` for the index, ``None`` if it is gone."""
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT i.indnullsnotdistinct FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :i"
            ),
            {"i": _INDEX},
        ).scalar()


@pytest.mark.integration
class TestBe9431TaskIndexTeeth:
    def test_pre_revision_accepts_a_duplicate_serial(self, scratch_at_pre: sa.Engine) -> None:
        """THE DISCRIMINATING CONTROL, and the defect itself.

        At ce_0094 the index exists, is UNIQUE, and covers exactly these rows —
        and still accepts the duplicate, because ``subseries`` is NULL and
        Postgres' default NULLS DISTINCT makes each row unique by construction.
        If this test ever fails, the pre-state changed and every assertion in
        this file stops meaning anything.
        """
        type_id = _seed_base(scratch_at_pre)
        _seed_task(scratch_at_pre, "TSK-19 first", type_id, 19)
        _seed_task(scratch_at_pre, "TSK-19 duplicate", type_id, 19)

        assert _index_is_strict(scratch_at_pre) is False, "pre-revision index must be the weakened one"

    def test_upgrade_heals_duplicates_instead_of_failing(self, scratch_at_pre: sa.Engine) -> None:
        """A database already holding duplicates must UPGRADE, not brick.

        Both rows survive, both stay live, and the later one is reassigned above
        the bucket's shared tasks+projects watermark — the project at serial 50
        is what proves the watermark is the shared line and not just MAX(tasks).
        """
        type_id = _seed_base(scratch_at_pre)
        keeper = _seed_task(scratch_at_pre, "TSK-19 first", type_id, 19)
        duplicate = _seed_task(scratch_at_pre, "TSK-19 duplicate", type_id, 19)
        _seed_project(scratch_at_pre, "holds serial 50", 50)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed on a duplicate-holding DB:\n{up.stdout}\n{up.stderr}"

        kept = _task_row(scratch_at_pre, keeper)
        moved = _task_row(scratch_at_pre, duplicate)
        assert kept.series_number == 19, "the earliest row keeps its serial"
        assert kept.deleted_at is None and moved.deleted_at is None, "healing must not delete or trash a row"
        assert moved.series_number == 51, "reassigned above the SHARED watermark (project 50 + 1), subseries cleared"
        assert moved.subseries is None
        assert _index_is_strict(scratch_at_pre) is True, "the index must be strict after healing"

    def test_restored_index_rejects_a_fresh_duplicate(self, scratch_at_pre: sa.Engine) -> None:
        """The property, not just the catalog flag — the same INSERT the
        pre-revision accepted is now refused."""
        type_id = _seed_base(scratch_at_pre)
        _seed_task(scratch_at_pre, "TSK-19 first", type_id, 19)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        with pytest.raises(IntegrityError):
            _seed_task(scratch_at_pre, "TSK-19 duplicate", type_id, 19)

    def test_trashed_rows_are_out_of_scope_and_untouched(self, scratch_at_pre: sa.Engine) -> None:
        """The predicate excludes soft-deleted rows, so a trashed task may keep a
        serial a live task also holds — healing must not renumber it."""
        type_id = _seed_base(scratch_at_pre)
        live = _seed_task(scratch_at_pre, "TSK-19 live", type_id, 19)
        trashed = _seed_task(scratch_at_pre, "TSK-19 trashed", type_id, 19, trashed=True)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _task_row(scratch_at_pre, live).series_number == 19
        assert _task_row(scratch_at_pre, trashed).series_number == 19, "a trashed row is not a duplicate here"

    def test_rerun_is_idempotent(self, scratch_at_pre: sa.Engine) -> None:
        """The CE installer's every-boot ``alembic upgrade`` re-entry: the second
        run finds the index already strict and changes nothing."""
        type_id = _seed_base(scratch_at_pre)
        keeper = _seed_task(scratch_at_pre, "TSK-19 first", type_id, 19)
        duplicate = _seed_task(scratch_at_pre, "TSK-19 duplicate", type_id, 19)

        assert _run_alembic("upgrade", _REV).returncode == 0
        first = (_task_row(scratch_at_pre, keeper), _task_row(scratch_at_pre, duplicate))

        assert _run_alembic("stamp", _PRE).returncode == 0
        reup = _run_alembic("upgrade", _REV)
        assert reup.returncode == 0, f"idempotent re-upgrade failed:\n{reup.stdout}\n{reup.stderr}"

        assert (_task_row(scratch_at_pre, keeper), _task_row(scratch_at_pre, duplicate)) == first
        assert _index_is_strict(scratch_at_pre) is True

    def test_downgrade_then_upgrade_round_trips(self, scratch_at_pre: sa.Engine) -> None:
        """The chain stays walkable: downgrade drops the flag (schema only,
        serials keep their healed values) and upgrade puts it back."""
        type_id = _seed_base(scratch_at_pre)
        _seed_task(scratch_at_pre, "TSK-19 first", type_id, 19)

        assert _run_alembic("upgrade", _REV).returncode == 0
        assert _index_is_strict(scratch_at_pre) is True

        down = _run_alembic("downgrade", _PRE)
        assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"
        assert _index_is_strict(scratch_at_pre) is False, "downgrade must restore the pre-revision shape"

        assert _run_alembic("upgrade", _REV).returncode == 0
        assert _index_is_strict(scratch_at_pre) is True
