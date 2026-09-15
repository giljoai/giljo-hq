# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
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

_PRE = "ce_0067_tsk_task_exclusive"
_REV = "ce_0068_purge_completed_sequence_runs"


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



TK = "tk_ce0068"


def _seed_run_with_conductor(engine: sa.Engine, *, status: str) -> dict[str, str]:
    run_id = str(uuid4())
    job_id = str(uuid4())
    agent_id = str(uuid4())
    exec_id = str(uuid4())
    metadata = json.dumps({"chain_conductor": True, "run_id": run_id})
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO sequence_runs "
                "(id, tenant_key, project_ids, resolved_order, execution_mode, status, "
                " review_policy, current_index, project_statuses) "
                "VALUES (:id, :tk, '[]'::jsonb, '[]'::jsonb, 'claude_code_cli', :status, "
                " 'per_card', 0, '{}'::jsonb)"
            ),
            {"id": run_id, "tk": TK, "status": status},
        )
        conn.execute(
            text(
                "INSERT INTO agent_jobs (job_id, tenant_key, project_id, job_type, status, job_metadata) "
                "VALUES (:jid, :tk, NULL, 'orchestrator', 'active', CAST(:meta AS jsonb))"
            ),
            {"jid": job_id, "tk": TK, "meta": metadata},
        )
        conn.execute(
            text(
                "INSERT INTO agent_executions "
                "(id, agent_id, job_id, tenant_key, agent_display_name, status, health_status, "
                " health_failure_count, progress, messages_sent_count, messages_waiting_count, "
                " messages_read_count, tool_type) "
                "VALUES (:eid, :aid, :jid, :tk, 'orchestrator', 'waiting', 'unknown', "
                " 0, 0, 0, 0, 0, 'universal')"
            ),
            {"eid": exec_id, "aid": agent_id, "jid": job_id, "tk": TK},
        )
        conn.commit()
    return {"run_id": run_id, "job_id": job_id, "exec_id": exec_id}


def _run_exists(engine: sa.Engine, run_id: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1 FROM sequence_runs WHERE id = :id"), {"id": run_id}).scalar() is not None


def _job_exists(engine: sa.Engine, job_id: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1 FROM agent_jobs WHERE job_id = :id"), {"id": job_id}).scalar() is not None


def _exec_exists(engine: sa.Engine, exec_id: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1 FROM agent_executions WHERE id = :id"), {"id": exec_id}).scalar() is not None


@pytest.mark.integration
class TestCe0068PurgeCompletedSequenceRuns:
    def test_completed_run_and_conductor_are_purged(self, scratch_at_pre: sa.Engine) -> None:
        done = _seed_run_with_conductor(scratch_at_pre, status="completed")

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert not _run_exists(scratch_at_pre, done["run_id"]), "completed run must be deleted"
        assert not _job_exists(scratch_at_pre, done["job_id"]), "orphan conductor job must be deleted"
        assert not _exec_exists(scratch_at_pre, done["exec_id"]), "orphan conductor execution must be deleted"

    def test_terminated_run_and_conductor_survive(self, scratch_at_pre: sa.Engine) -> None:
        kept = _seed_run_with_conductor(scratch_at_pre, status="terminated")

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _run_exists(scratch_at_pre, kept["run_id"]), "terminated run must survive (out of scope)"
        assert _job_exists(scratch_at_pre, kept["job_id"]), "terminated run's conductor job must survive"
        assert _exec_exists(scratch_at_pre, kept["exec_id"]), "terminated run's conductor execution must survive"

    def test_rerun_is_idempotent(self, scratch_at_pre: sa.Engine) -> None:
        done = _seed_run_with_conductor(scratch_at_pre, status="completed")
        kept = _seed_run_with_conductor(scratch_at_pre, status="terminated")

        assert _run_alembic("upgrade", _REV).returncode == 0
        assert not _run_exists(scratch_at_pre, done["run_id"])
        assert _run_exists(scratch_at_pre, kept["run_id"])

        assert _run_alembic("stamp", _PRE).returncode == 0
        reup = _run_alembic("upgrade", _REV)
        assert reup.returncode == 0, f"idempotent re-upgrade failed:\n{reup.stdout}\n{reup.stderr}"

        assert not _run_exists(scratch_at_pre, done["run_id"]), "completed run stays gone on re-run"
        assert _run_exists(scratch_at_pre, kept["run_id"]), "terminated survivor stays put on re-run"
        assert _job_exists(scratch_at_pre, kept["job_id"])
        assert _exec_exists(scratch_at_pre, kept["exec_id"])
