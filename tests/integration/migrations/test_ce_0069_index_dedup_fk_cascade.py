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

_PRE = "ce_0068_purge_completed_sequence_runs"
_TARGET = "ce_0069_dedup_indexes_drift_reconcile"

_FK_NAME = "oauth_refresh_tokens_user_id_fkey"


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


def _fk_delete_action(engine: sa.Engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT confdeltype FROM pg_constraint "
                "WHERE conrelid = 'oauth_refresh_tokens'::regclass AND contype = 'f' "
                "AND conkey = (SELECT array_agg(attnum) FROM pg_attribute "
                "  WHERE attrelid = 'oauth_refresh_tokens'::regclass AND attname = 'user_id')"
            )
        ).scalar()


def _index_exists(engine: sa.Engine, name: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = :n"),
                {"n": name},
            ).scalar()
        )


def _seed_user_and_token(engine: sa.Engine, *, uid: str) -> None:
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, tenant_key, username, failed_pin_attempts, "
                "must_change_password, must_set_pin, is_system_user, role, is_active) "
                "VALUES (:id, :tk, :un, 0, FALSE, FALSE, FALSE, 'admin', TRUE)"
            ),
            {"id": uid, "tk": "tk_" + uid, "un": "user_" + uid},
        )
        conn.execute(
            text(
                "INSERT INTO oauth_refresh_tokens "
                "(token_hash, family_id, client_id, tenant_key, user_id, aud, expires_at) "
                "VALUES (:th, gen_random_uuid(), 'client', :tk, :uid, 'aud', now() + interval '1 day')"
            ),
            {"th": "hash_" + uid, "tk": "tk_" + uid, "uid": uid},
        )
        conn.commit()


def _token_count(engine: sa.Engine, uid: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM oauth_refresh_tokens WHERE user_id = :uid"),
                {"uid": uid},
            ).scalar()
        )


def _delete_user(engine: sa.Engine, uid: str) -> None:
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})
        conn.commit()


@pytest.mark.integration
class TestCe0069IndexDedupFkCascade:
    def test_fresh_chain_has_cascade_fk_and_cascades(self, empty_scratch_db: sa.Engine) -> None:
        up = _run_alembic("upgrade", _TARGET)
        assert up.returncode == 0, f"upgrade {_TARGET} failed:\n{up.stdout}\n{up.stderr}"

        assert _fk_delete_action(empty_scratch_db) == "c", (
            "oauth_refresh_tokens.user_id must have an ON DELETE CASCADE FK after ce_0069"
        )

        _seed_user_and_token(empty_scratch_db, uid="u_cascade")
        assert _token_count(empty_scratch_db, "u_cascade") == 1
        _delete_user(empty_scratch_db, "u_cascade")
        assert _token_count(empty_scratch_db, "u_cascade") == 0, (
            "deleting a user must cascade-delete its oauth_refresh_tokens"
        )

    def test_legacy_missing_fk_is_healed_by_upgrade(self, empty_scratch_db: sa.Engine) -> None:
        assert _run_alembic("upgrade", _PRE).returncode == 0

        with empty_scratch_db.connect() as conn:
            conn.execute(text(f"ALTER TABLE oauth_refresh_tokens DROP CONSTRAINT IF EXISTS {_FK_NAME}"))
            conn.commit()
        assert _fk_delete_action(empty_scratch_db) is None, "precondition: FK removed to mimic a legacy DB"

        up = _run_alembic("upgrade", _TARGET)
        assert up.returncode == 0, f"upgrade {_TARGET} failed:\n{up.stdout}\n{up.stderr}"
        assert _fk_delete_action(empty_scratch_db) == "c", (
            "ce_0069 must ADD the CASCADE FK on a legacy DB that lacked it"
        )

        _seed_user_and_token(empty_scratch_db, uid="u_legacy")
        _delete_user(empty_scratch_db, "u_legacy")
        assert _token_count(empty_scratch_db, "u_legacy") == 0

    def test_duplicate_index_dropped_unique_twin_and_perf_composite_kept(self, empty_scratch_db: sa.Engine) -> None:
        assert _run_alembic("upgrade", _TARGET).returncode == 0

        assert not _index_exists(empty_scratch_db, "idx_apikey_hash")
        assert _index_exists(empty_scratch_db, "ix_api_keys_key_hash")
        assert not _index_exists(empty_scratch_db, "idx_agent_executions_tenant")
        assert _index_exists(empty_scratch_db, "idx_agent_executions_tenant_job_started")
