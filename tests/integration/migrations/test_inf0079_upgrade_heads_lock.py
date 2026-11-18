# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from giljo_mcp.db_url import normalize_database_url
from tests.helpers.test_db_helper import (
    create_database_lock,
    hold_session_advisory_lock,
    start_advisory_lock_holder,
    worker_suffix,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "scripts" / "alembic_cli.py"


def _script_lock_key() -> int:
    match = re.search(r"^MIGRATION_LOCK_KEY = (\d+)$", SCRIPT.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, "scripts/alembic_cli.py no longer defines MIGRATION_LOCK_KEY = <int>"
    return int(match.group(1))


MIGRATION_LOCK_KEY = _script_lock_key()

OWNER = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
OWNER_PW = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
HOST = os.environ.get("POSTGRES_HOST", os.environ.get("DB_HOST", "localhost"))
PORT = os.environ.get("POSTGRES_PORT", os.environ.get("DB_PORT", "5432"))
SUCCESS_PREFIX = "Dual-chain at head: CE="


def _owner_pw() -> str:
    if OWNER_PW:
        return OWNER_PW
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("POSTGRES_OWNER_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("POSTGRES_OWNER_PASSWORD is not set")


def _engine(db: str, **kw) -> sa.Engine:
    url = f"postgresql://{OWNER}:{_owner_pw()}@{HOST}:{PORT}/{db}"
    return sa.create_engine(normalize_database_url(url, "sync"), poolclass=sa.pool.NullPool, **kw)


@pytest.fixture
def scratch_db():
    name = f"giljo_test_inf0079_{uuid.uuid4().hex[:10]}{worker_suffix()}"
    superuser_pw = os.environ.get("POSTGRES_SUPERUSER_PASSWORD", "")
    if superuser_pw:
        admin_url = f"postgresql://postgres:{superuser_pw}@{HOST}:{PORT}/postgres"
    else:
        admin_url = f"postgresql://{OWNER}:{_owner_pw()}@{HOST}:{PORT}/postgres"
    admin = sa.create_engine(
        normalize_database_url(admin_url, "sync"), poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        with admin.connect() as conn, create_database_lock(conn):
            conn.execute(text(f'CREATE DATABASE "{name}" OWNER "{OWNER}"'))
        yield name
    finally:
        with admin.connect() as conn:
            conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n"), {"n": name})
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


def _env(db: str, *, mode: str, wait_seconds: int | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"postgresql://{OWNER}:{_owner_pw()}@{HOST}:{PORT}/{db}"
    env["GILJO_MODE"] = mode
    env.pop("POSTGRES_PASSWORD", None)
    if wait_seconds is not None:
        env["GILJO_MIGRATION_LOCK_WAIT_SECONDS"] = str(wait_seconds)
    return env


def _spawn(db: str, *, mode: str = "saas", wait_seconds: int | None = None) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, str(SCRIPT), "upgrade", "heads"],
        cwd=str(PROJECT_ROOT),
        env=_env(db, mode=mode, wait_seconds=wait_seconds),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _version_table_exists(db: str) -> bool:
    eng = _engine(db)
    try:
        with eng.connect() as conn:
            return conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is not None
    finally:
        eng.dispose()


@contextlib.contextmanager
def _held_lock(db: str):
    eng = _engine(db, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn, hold_session_advisory_lock(conn, MIGRATION_LOCK_KEY):
            yield
    finally:
        eng.dispose()


def _assert_one_success_line(out: str, err: str) -> None:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    structured = [ln for ln in lines if ln.startswith("Dual-chain")]
    assert len(structured) == 1, f"expected one structured line, got {structured!r} (stderr={err[-800:]!r})"
    assert lines[-1].startswith(SUCCESS_PREFIX)


@pytest.mark.timeout(600)
def test_two_concurrent_upgrade_heads_runs_both_succeed(scratch_db):
    procs = [_spawn(scratch_db), _spawn(scratch_db)]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=540)
        results.append((p.returncode, out, err))
    for rc, out, err in results:
        assert rc == 0, f"a concurrent runner failed: rc={rc}\n{err[-2500:]}"
        _assert_one_success_line(out, err)


@pytest.mark.timeout(300)
def test_runner_waits_while_lock_is_held_then_finishes(scratch_db):
    with _held_lock(scratch_db):
        proc = _spawn(scratch_db)
        time.sleep(6)
        assert proc.poll() is None, "script finished while the migration lock was held"
        assert not _version_table_exists(scratch_db), "script touched alembic_version while the lock was held"
    out, err = proc.communicate(timeout=240)
    assert proc.returncode == 0, err[-2500:]
    _assert_one_success_line(out, err)
    assert _version_table_exists(scratch_db)


@pytest.mark.timeout(300)
def test_wait_limit_prints_one_failure_line_and_exits_nonzero(scratch_db):
    with _held_lock(scratch_db):
        proc = _spawn(scratch_db, wait_seconds=2)
        out, err = proc.communicate(timeout=120)
    assert proc.returncode != 0
    assert out.strip() == ""
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, err_lines
    assert err_lines[0].startswith("Dual-chain migration FAILED: lock-wait — ")
    assert not _version_table_exists(scratch_db)


@pytest.mark.timeout(300)
def test_killed_holder_frees_the_lock_for_the_next_runner(scratch_db):
    dsn = f"postgresql://{OWNER}:{_owner_pw()}@{HOST}:{PORT}/{scratch_db}"
    holder = start_advisory_lock_holder(dsn, MIGRATION_LOCK_KEY)
    try:
        blocked = _spawn(scratch_db, wait_seconds=2)
        _, err = blocked.communicate(timeout=120)
        assert blocked.returncode != 0, "lock was not actually held by the holder process"
        assert "lock-wait" in err
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=30)
    finally:
        if holder.poll() is None:
            holder.kill()
    proc = _spawn(scratch_db, wait_seconds=60)
    out, err = proc.communicate(timeout=240)
    assert proc.returncode == 0, err[-2500:]
    _assert_one_success_line(out, err)


@pytest.mark.timeout(300)
def test_lock_connection_dying_mid_run_does_not_fail_a_good_upgrade(scratch_db):
    proc = _spawn(scratch_db)
    admin = _engine(scratch_db, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            deadline = time.monotonic() + 60
            pid = None
            while pid is None and time.monotonic() < deadline:
                pid = conn.execute(
                    text("SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND objid = :k AND granted"),
                    {"k": MIGRATION_LOCK_KEY},
                ).scalar()
                if pid is None:
                    time.sleep(0.05)
            assert pid is not None, "the runner never took the migration lock"
            assert proc.poll() is None, "upgrade already finished before the lock backend was killed"
            conn.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid})
    finally:
        admin.dispose()
    out, err = proc.communicate(timeout=240)
    assert proc.returncode == 0, err[-2500:]
    _assert_one_success_line(out, err)


@pytest.mark.timeout(300)
def test_ce_mode_never_takes_or_waits_for_the_lock(scratch_db):
    with _held_lock(scratch_db):
        proc = _spawn(scratch_db, mode="ce", wait_seconds=1)
        out, err = proc.communicate(timeout=240)
    assert proc.returncode == 0, err[-2500:]
    assert "lock-wait" not in err
    assert not out.startswith(SUCCESS_PREFIX)
