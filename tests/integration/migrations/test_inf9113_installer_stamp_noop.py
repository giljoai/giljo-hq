# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9113 regression: installer Phase-B migration stamp logic.

The CE installer runs migrations twice on a fresh install: Phase A
("Setting Up Database", install.py --setup-only) upgrades the fresh DB to
head, then Phase B ("Applying Database Migrations",
DatabaseSetupMixin.run_database_migrations) re-checks the alembic state.
Phase B's recognition scan resolved ``migrations/versions`` relative to
``installer/core/database_setup.py`` -- a directory that does not exist --
so every real ce_0XXX revision was misclassified as "unknown" and the
pointer was destructively stamped DOWN to baseline_v37. The subsequent
chain replay then crashed in ce_0015 (backfill reads ``tasks.category``,
which ce_0016 drops), wedging every fresh install.

Failing-layer regressions (real scratch PostgreSQL, per-worker DB):

  (a) Fresh-install sequence -- Phase A to head, then Phase B must NO-OP:
      pointer stays at head, never stamped down. THE load-bearing test:
      the bug shipped because nothing ran Phase A + Phase B together.
  (b) ce_0015 replayed over an at-head schema (category absent) no-ops
      instead of crashing UndefinedColumn; a DB wedged by this bug
      (pointer=baseline_v37, schema at head) self-heals via full replay.
  (c) The genuinely-empty-DB path (no alembic_version table) still
      installs to head -- the legacy case Phase B exists for.
  (+) A revision unknown to this build's chain (newer build) is never
      stamped down; the install fails loudly at alembic instead.

SAFETY: scratch DB only (giljo_test_bootstrap{worker}); the live DBs
giljo_mcp / giljo_mcp_ce are NEVER touched. Parallel-safe: per-worker
scratch DB (conftest provisions it), monkeypatch owns env/cwd mutations.
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

_CE_0014 = "ce_0014_rename_project_types_to_taxonomy_types"
_CE_0015 = "ce_0015_tasks_add_task_type_id"
_FAKE_FUTURE_REVISION = "zz_9999_from_a_newer_build"


def _scratch_db_url() -> str:
    if SCRATCH_DB == PRODUCTION_DB_NAME:
        raise RuntimeError(
            "SAFETY GUARD: Refusing to run INF-9113 regression tests against "
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


def _current_version(engine: sa.Engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()


def _set_version(engine: sa.Engine, version: str) -> None:
    with engine.connect() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": version})
        conn.commit()


def _column_exists(engine: sa.Engine, table: str, column: str) -> bool:
    insp = sa.inspect(engine)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _table_exists(engine: sa.Engine, name: str) -> bool:
    return name in sa.inspect(engine).get_table_names()


def _run_installer_phase_b(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Run the REAL installer Phase B (run_database_migrations) in-process.

    Exercises the failing layer exactly: UnifiedInstaller (which hosts
    DatabaseSetupMixin + _verify_essential_tables) against the scratch DB.
    Only the venv-python lookup is stubbed (tests run in the dev venv, which
    has alembic; there is no installer-created venv here).
    """
    import install

    monkeypatch.chdir(PROJECT_ROOT)
    for key, value in _build_env().items():
        monkeypatch.setenv(key, value)

    inst = install.UnifiedInstaller(settings={"install_dir": str(PROJECT_ROOT)})
    monkeypatch.setattr(inst.platform, "get_venv_python", lambda venv_dir: Path(sys.executable))
    return inst.run_database_migrations()


@pytest.fixture(scope="module")
def scratch_engine():
    engine = _scratch_engine()
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# (a) THE load-bearing sequence: Phase A to head, Phase B must NO-OP
# ---------------------------------------------------------------------------


def test_phase_b_noops_on_fresh_at_head_db(scratch_engine, monkeypatch):
    """Fresh install: after Phase A upgrades to head, Phase B must not stamp down."""
    _drop_all_objects(scratch_engine)

    # Phase A: alembic upgrade head on the fresh DB (what --setup-only does).
    phase_a = _run_alembic("upgrade", "head")
    assert phase_a.returncode == 0, f"Phase A failed:\n{phase_a.stdout}\n{phase_a.stderr}"

    head_rev = _current_version(scratch_engine)
    assert head_rev is not None
    assert head_rev != "baseline_v37", "precondition: chain head must be past baseline"
    # The Acer repro precondition: at head, tasks.category is already dropped.
    assert not _column_exists(scratch_engine, "tasks", "category")

    # Phase B: the installer's second migration pass.
    result = _run_installer_phase_b(monkeypatch)

    assert result["success"] is True, f"Phase B failed: {result.get('error')}"
    # THE regression assertion: pointer untouched, never stamped down.
    assert _current_version(scratch_engine) == head_rev
    # And nothing got replayed on the already-at-head schema.
    assert result["migrations_applied"] == []


# ---------------------------------------------------------------------------
# (+) Unknown/newer revision: fail loudly, NEVER stamp down
# ---------------------------------------------------------------------------


def test_unknown_revision_is_never_stamped_down(scratch_engine, monkeypatch):
    """A revision from a newer build must not be 'bridged' down to baseline_v37.

    Phase B must leave the pointer alone; the subsequent `alembic upgrade
    head` fails loudly ("Can't locate revision") and Phase B reports failure.
    """
    _drop_all_objects(scratch_engine)
    phase_a = _run_alembic("upgrade", "head")
    assert phase_a.returncode == 0, f"setup failed:\n{phase_a.stderr}"

    _set_version(scratch_engine, _FAKE_FUTURE_REVISION)

    result = _run_installer_phase_b(monkeypatch)

    # Loud failure at alembic -- not a silent destructive stamp.
    assert result["success"] is False
    assert _current_version(scratch_engine) == _FAKE_FUTURE_REVISION


# ---------------------------------------------------------------------------
# (b) ce_0015 replay tolerance + wedged-DB self-heal
# ---------------------------------------------------------------------------


def test_ce_0015_replays_cleanly_on_at_head_schema(scratch_engine):
    """Replaying ce_0015 over a schema where ce_0016 already dropped
    tasks.category must no-op, not crash UndefinedColumn."""
    _drop_all_objects(scratch_engine)
    assert _run_alembic("upgrade", "head").returncode == 0

    assert not _column_exists(scratch_engine, "tasks", "category")

    # Force the exact replay the stamp-down bug caused, isolated to ce_0015.
    assert _run_alembic("stamp", _CE_0014).returncode == 0
    replay = _run_alembic("upgrade", _CE_0015)

    assert replay.returncode == 0, f"ce_0015 replay crashed on at-head schema:\n{replay.stdout}\n{replay.stderr}"
    assert _current_version(scratch_engine) == _CE_0015


def test_wedged_db_self_heals_on_next_upgrade(scratch_engine):
    """A DB wedged by the INF-9113 bug (pointer=baseline_v37, schema at head)
    must reach head on its next `alembic upgrade head` (tolerance/self-heal
    DoD -- no manual fix instructions to CE self-hosters)."""
    _drop_all_objects(scratch_engine)
    assert _run_alembic("upgrade", "head").returncode == 0
    head_rev = _current_version(scratch_engine)

    # Reproduce the wedge exactly as the shipped installer created it.
    _set_version(scratch_engine, "baseline_v37")

    heal = _run_alembic("upgrade", "head")

    assert heal.returncode == 0, f"full-chain replay over at-head schema crashed:\n{heal.stdout}\n{heal.stderr}"
    assert _current_version(scratch_engine) == head_rev


# ---------------------------------------------------------------------------
# (+) startup.py boot path: same stamp-down policy, same fix
# ---------------------------------------------------------------------------


def _run_startup_migrations() -> subprocess.CompletedProcess[str]:
    """Invoke startup.run_database_migrations in a fresh subprocess (the CE
    boot path -- startup.py re-runs migrations on every server start)."""
    code = (
        "import sys, os; "
        "sys.path.insert(0, os.getcwd()); "
        "import startup; "
        "ok = startup.run_database_migrations(); "
        "sys.exit(0 if ok else 1)"
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


def test_startup_boot_never_stamps_down_unknown_revision(scratch_engine):
    """startup.py shares the installer's bridge logic; a revision from a
    newer build (rollback / restore onto older code / partial update) must
    never be stamped down on boot -- fail loudly, pointer untouched."""
    _drop_all_objects(scratch_engine)
    assert _run_alembic("upgrade", "head").returncode == 0

    _set_version(scratch_engine, _FAKE_FUTURE_REVISION)

    boot = _run_startup_migrations()

    # Loud failure at alembic ("Can't locate revision") -- not a silent
    # destructive stamp + full-chain replay.
    assert boot.returncode != 0
    assert _current_version(scratch_engine) == _FAKE_FUTURE_REVISION


def test_startup_boot_noops_on_at_head_db(scratch_engine):
    """Normal boot on an at-head DB: pointer stays at head, boot succeeds."""
    _drop_all_objects(scratch_engine)
    assert _run_alembic("upgrade", "head").returncode == 0
    head_rev = _current_version(scratch_engine)

    boot = _run_startup_migrations()

    assert boot.returncode == 0, f"boot failed:\n{boot.stdout}\n{boot.stderr}"
    assert _current_version(scratch_engine) == head_rev


# ---------------------------------------------------------------------------
# (c) Genuinely empty DB: the fresh path Phase B exists for still works
# ---------------------------------------------------------------------------


def test_empty_db_installs_to_head(scratch_engine, monkeypatch):
    """No alembic_version table at all: Phase B runs the full chain to head."""
    _drop_all_objects(scratch_engine)

    result = _run_installer_phase_b(monkeypatch)

    assert result["success"] is True, f"empty-DB install failed: {result.get('error')}"
    version = _current_version(scratch_engine)
    assert version is not None and version != "baseline_v37"
    for table in ("setup_state", "users", "tasks", "projects"):
        assert _table_exists(scratch_engine, table), f"essential table missing: {table}"
