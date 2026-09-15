# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import re
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

SQUASH_BOUNDARY = "ce_0077_sequence_run_reviewed_project_ids"
NEW_BASELINE = "baseline_v38"


def _head_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()


def _scratch_db_url() -> str:
    if SCRATCH_DB == PRODUCTION_DB_NAME:
        raise RuntimeError(
            "SAFETY GUARD: Refusing to run INF-5060 regression tests against "
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


def _table_exists(engine: sa.Engine, name: str) -> bool:
    return name in sa.inspect(engine).get_table_names()


def _column_exists(engine: sa.Engine, table: str, column: str) -> bool:
    insp = sa.inspect(engine)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _schema_snapshot(engine: sa.Engine) -> dict:
    with engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT table_name, "
                "ROW_NUMBER() OVER (PARTITION BY table_name ORDER BY ordinal_position), "
                "column_name, data_type, "
                "is_nullable, column_default, character_maximum_length "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name <> 'alembic_version' "
                "ORDER BY table_name, ordinal_position"
            )
        ).all()
        indexes = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version' ORDER BY indexdef"
            )
        ).all()
        constraints = conn.execute(
            text(
                "SELECT cl.relname, con.conname, pg_get_constraintdef(con.oid) "
                "FROM pg_constraint con JOIN pg_class cl ON cl.oid = con.conrelid "
                "JOIN pg_namespace n ON n.oid = cl.relnamespace "
                "WHERE n.nspname = 'public' AND cl.relname <> 'alembic_version' "
                "AND con.contype <> 'n' "
                "ORDER BY cl.relname, con.conname"
            )
        ).all()
        comments = conn.execute(
            text(
                "SELECT c.relname, a.attname, d.description "
                "FROM pg_description d "
                "JOIN pg_class c ON c.oid = d.objoid "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = d.objsubid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND d.objsubid > 0 "
                "ORDER BY c.relname, a.attname"
            )
        ).all()
    return {
        "columns": [tuple(r) for r in columns],
        "indexes": [r[0] for r in indexes],
        "constraints": [tuple(r) for r in constraints],
        "comments": [tuple(r) for r in comments],
    }


def _fast_path_build(engine: sa.Engine) -> None:
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:rev)").bindparams(rev=SQUASH_BOUNDARY))
        conn.commit()
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"fast-path upgrade failed:\n{result.stdout}\n{result.stderr}"


def _run_installer_phase_b(monkeypatch: pytest.MonkeyPatch) -> dict:
    import install

    monkeypatch.chdir(PROJECT_ROOT)
    for key, value in _build_env().items():
        monkeypatch.setenv(key, value)

    inst = install.UnifiedInstaller(settings={"install_dir": str(PROJECT_ROOT)})
    monkeypatch.setattr(inst.platform, "get_venv_python", lambda venv_dir: Path(sys.executable))
    return inst.run_database_migrations()


def _run_startup_migrations() -> subprocess.CompletedProcess[str]:
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


@pytest.fixture(scope="module")
def scratch_engine():
    engine = _scratch_engine()
    yield engine
    engine.dispose()




def test_fresh_installer_fast_path_runs_only_baseline(scratch_engine, monkeypatch, capsys):
    _drop_all_objects(scratch_engine)

    result = _run_installer_phase_b(monkeypatch)

    assert result["success"] is True, f"installer failed: {result.get('error')}"
    assert _current_version(scratch_engine) == _head_revision()
    out = capsys.readouterr().out
    assert "baseline_v38 fast path" in out, f"installer did not take the fast path:\n{out}"
    for table in ("setup_state", "users", "tasks", "projects", "sequence_runs"):
        assert _table_exists(scratch_engine, table), f"essential table missing: {table}"




def test_fresh_boot_takes_fast_path(scratch_engine):
    _drop_all_objects(scratch_engine)

    boot = _run_startup_migrations()

    assert boot.returncode == 0, f"boot failed:\n{boot.stdout}\n{boot.stderr}"
    assert _current_version(scratch_engine) == _head_revision()
    combined = boot.stdout + boot.stderr
    assert "fast path" in combined, f"fresh boot did not report the fast path:\n{combined}"




def test_parity_fast_path_vs_chain_replay(scratch_engine):
    head = _head_revision()
    _drop_all_objects(scratch_engine)
    _fast_path_build(scratch_engine)
    assert _current_version(scratch_engine) == head
    fast = _schema_snapshot(scratch_engine)

    _drop_all_objects(scratch_engine)
    replay = _run_alembic("upgrade", "head")
    assert replay.returncode == 0, f"chain replay failed:\n{replay.stdout}\n{replay.stderr}"
    assert _current_version(scratch_engine) == head
    chain = _schema_snapshot(scratch_engine)

    for key in ("columns", "indexes", "constraints", "comments"):
        assert fast[key] == chain[key], (
            f"PARITY VIOLATION in {key}: fast-path vs chain-replay differ.\n"
            f"fast-only: {[x for x in fast[key] if x not in chain[key]][:10]}\n"
            f"chain-only: {[x for x in chain[key] if x not in fast[key]][:10]}"
        )




def test_at_head_ce0077_db_upgrades_as_pure_noop(scratch_engine):
    _drop_all_objects(scratch_engine)
    build = _run_alembic("upgrade", SQUASH_BOUNDARY)
    assert build.returncode == 0, f"chain build to ce_0077 failed:\n{build.stderr}"
    assert _current_version(scratch_engine) == SQUASH_BOUNDARY
    before = _schema_snapshot(scratch_engine)

    up = _run_alembic("upgrade", NEW_BASELINE)

    assert up.returncode == 0, f"tip upgrade failed:\n{up.stdout}\n{up.stderr}"
    assert _current_version(scratch_engine) == NEW_BASELINE
    after = _schema_snapshot(scratch_engine)
    assert before == after, "guarded tip modified an at-head schema (must be a pure no-op)"




def test_adr009_org_scaffolding_survives_squash(scratch_engine):
    _drop_all_objects(scratch_engine)
    _fast_path_build(scratch_engine)

    assert _table_exists(scratch_engine, "organizations")
    assert _table_exists(scratch_engine, "org_memberships")
    assert _column_exists(scratch_engine, "users", "org_id")
    assert _column_exists(scratch_engine, "products", "org_id")
    assert _column_exists(scratch_engine, "organizations", "tenant_key")




def test_squash_boundary_revision_in_sync():
    from startup_support.migration_stamp import FRESH_INSTALL_STAMP_REVISION

    assert FRESH_INSTALL_STAMP_REVISION == SQUASH_BOUNDARY

    baseline_src = (PROJECT_ROOT / "migrations" / "versions" / "baseline_v38_unified.py").read_text(encoding="utf-8")
    m = re.search(r'^down_revision.*=\s*"([^"]+)"', baseline_src, re.MULTILINE)
    assert m and m.group(1) == SQUASH_BOUNDARY, "baseline_v38.down_revision drifted from the seam constant"

    installer_src = (PROJECT_ROOT / "installer" / "core" / "database_setup.py").read_text(encoding="utf-8")
    assert SQUASH_BOUNDARY in installer_src, "installer seam lost the squash-boundary stamp revision"
