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


def _upgrade_to_pre_be5115(scratch_engine: sa.Engine) -> None:
    result = _run_alembic("upgrade", "ce_0031_user_split_name")
    assert result.returncode == 0, (
        f"alembic upgrade ce_0031_user_split_name failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def _vision_documents_row(engine: sa.Engine, doc_id: str) -> dict:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text("SELECT id, storage_type, vision_path, vision_document FROM vision_documents WHERE id = :id"),
                {"id": doc_id},
            )
            .mappings()
            .first()
        )
    assert row is not None, f"vision_documents row {doc_id} missing"
    return dict(row)


def _insert_vision_doc_skipping_constraint(
    engine: sa.Engine,
    *,
    row_id: str,
    storage_type: str,
    vision_path: str | None,
    vision_document: str | None,
) -> None:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE vision_documents DROP CONSTRAINT IF EXISTS ck_vision_doc_storage_consistency"))
        product_id = conn.execute(
            text("INSERT INTO products (id, tenant_key, name, is_active) VALUES (:pid, :tk, :name, true) RETURNING id"),
            {"pid": "prod-" + row_id, "tk": "tk_" + row_id, "name": "be5115 product " + row_id},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO vision_documents "
                "(id, tenant_key, product_id, document_name, document_type, storage_type, "
                "vision_path, vision_document, chunked, chunk_count, is_summarized, "
                "version, is_active, display_order) "
                "VALUES (:id, :tk, :pid, :name, 'vision', :stype, :vpath, :vdoc, "
                "false, 0, false, '1.0.0', true, 0)"
            ),
            {
                "id": row_id,
                "tk": "tk_" + row_id,
                "pid": product_id,
                "name": "vision-" + row_id,
                "stype": storage_type,
                "vpath": vision_path,
                "vdoc": vision_document,
            },
        )
        conn.commit()


@pytest.mark.integration
class TestBe5115Migration:
    def test_hybrid_row_collapses_to_inline_with_content_preserved(self, empty_scratch_db: sa.Engine) -> None:
        _upgrade_to_pre_be5115(empty_scratch_db)

        _insert_vision_doc_skipping_constraint(
            empty_scratch_db,
            row_id="be5115-hybrid",
            storage_type="hybrid",
            vision_path="/tmp/legacy/vision.md",
            vision_document="preserved hybrid content",
        )

        upgrade = _run_alembic("upgrade", "ce_0032_vision_docs_inline_only")
        assert upgrade.returncode == 0, (
            f"alembic upgrade ce_0032_vision_docs_inline_only failed:\n"
            f"STDOUT:\n{upgrade.stdout}\nSTDERR:\n{upgrade.stderr}"
        )

        row = _vision_documents_row(empty_scratch_db, "be5115-hybrid")
        assert row["storage_type"] == "inline"
        assert row["vision_path"] is None
        assert row["vision_document"] == "preserved hybrid content"

    def test_file_row_with_null_document_is_backfilled_to_empty_string(self, empty_scratch_db: sa.Engine) -> None:
        _upgrade_to_pre_be5115(empty_scratch_db)

        _insert_vision_doc_skipping_constraint(
            empty_scratch_db,
            row_id="be5115-file-null",
            storage_type="file",
            vision_path="/tmp/legacy/orphan.md",
            vision_document=None,
        )

        upgrade = _run_alembic("upgrade", "ce_0032_vision_docs_inline_only")
        assert upgrade.returncode == 0, (
            f"alembic upgrade ce_0032 failed:\nSTDOUT:\n{upgrade.stdout}\nSTDERR:\n{upgrade.stderr}"
        )

        row = _vision_documents_row(empty_scratch_db, "be5115-file-null")
        assert row["storage_type"] == "inline"
        assert row["vision_path"] is None
        assert row["vision_document"] == ""

    def test_downgrade_does_not_raise_and_upgrade_is_idempotent(self, empty_scratch_db: sa.Engine) -> None:
        _upgrade_to_pre_be5115(empty_scratch_db)
        _insert_vision_doc_skipping_constraint(
            empty_scratch_db,
            row_id="be5115-inline-roundtrip",
            storage_type="hybrid",
            vision_path="/tmp/legacy/vision.md",
            vision_document="roundtrip content",
        )

        upgrade = _run_alembic("upgrade", "ce_0032_vision_docs_inline_only")
        assert upgrade.returncode == 0, (
            f"alembic upgrade ce_0032 failed:\nSTDOUT:\n{upgrade.stdout}\nSTDERR:\n{upgrade.stderr}"
        )

        downgrade = _run_alembic("downgrade", "ce_0031_user_split_name")
        assert downgrade.returncode == 0, (
            f"alembic downgrade ce_0031 failed:\nSTDOUT:\n{downgrade.stdout}\nSTDERR:\n{downgrade.stderr}"
        )

        row = _vision_documents_row(empty_scratch_db, "be5115-inline-roundtrip")
        assert row["storage_type"] == "inline"

        reupgrade = _run_alembic("upgrade", "ce_0032_vision_docs_inline_only")
        assert reupgrade.returncode == 0, (
            f"alembic re-upgrade ce_0032 failed:\nSTDOUT:\n{reupgrade.stdout}\nSTDERR:\n{reupgrade.stderr}"
        )
        row = _vision_documents_row(empty_scratch_db, "be5115-inline-roundtrip")
        assert row["storage_type"] == "inline"
        assert row["vision_path"] is None
