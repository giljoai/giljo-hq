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
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")
PRODUCTION_DB_NAME = "giljo_mcp"

PRESENCE_EXEMPT: dict[str, str] = {
    "idx_pme_fts": "functional GIN expression index; not round-trippable (ce_0069)",
}


def _scratch_db_url() -> str:
    if SCRATCH_DB == PRODUCTION_DB_NAME:
        raise RuntimeError(
            "SAFETY GUARD: refusing to run BE-9429 parity tests against the "
            "production DB name 'giljo_mcp'. Override GILJO_BOOTSTRAP_TEST_DB."
        )
    pw = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
    if not pw:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("POSTGRES_OWNER_PASSWORD="):
                    pw = line.split("=", 1)[1].strip()
                    break
    if not pw:
        raise RuntimeError(
            "POSTGRES_OWNER_PASSWORD is not set; cannot reach the scratch DB. "
            "The BE-9429 index-parity guard needs it and will not silently skip."
        )
    return f"postgresql://{ADMIN_USER}:{pw}@{DB_HOST}:{DB_PORT}/{SCRATCH_DB}"


def _build_env(url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    env["POSTGRES_DB"] = SCRATCH_DB
    env["POSTGRES_USER"] = ADMIN_USER
    env["DB_NAME"] = SCRATCH_DB
    env["DB_USER"] = ADMIN_USER
    pwd = url.split("//", 1)[1].split("@", 1)[0].split(":", 1)[1]
    env["POSTGRES_PASSWORD"] = pwd
    env["DB_PASSWORD"] = pwd
    env.pop("GILJO_MODE", None)
    return env


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
def migrated_engine() -> sa.Engine:
    _ensure_scratch_database_exists()
    url = _scratch_db_url()
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text(f"GRANT ALL ON SCHEMA public TO {ADMIN_USER}"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        conn.commit()

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        env=_build_env(url),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"alembic upgrade head failed rc={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    yield engine
    engine.dispose()


_DB_INDEX_SQL = """
SELECT c.relname AS name,
       t.relname AS table_name,
       i.indisunique AS is_unique,
       i.indnullsnotdistinct AS nulls_not_distinct,
       pg_get_expr(i.indpred, i.indrelid) AS where_clause
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_class t ON t.oid = i.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
"""


def _migrated_indexes(engine: sa.Engine) -> dict[str, dict]:
    with engine.connect() as conn:
        return {r["name"]: dict(r) for r in conn.execute(text(_DB_INDEX_SQL)).mappings()}


def _migrated_tables(engine: sa.Engine) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))}


def _model_indexes(engine: sa.Engine) -> dict[str, dict]:
    from giljo_mcp.models import Base

    built = _migrated_tables(engine)
    out: dict[str, dict] = {}
    for table in Base.metadata.tables.values():
        if table.name not in built:
            continue
        for idx in table.indexes:
            opts = idx.dialect_options.get("postgresql", {})
            out[idx.name] = {
                "table_name": table.name,
                "is_unique": bool(idx.unique),
                "nulls_not_distinct": bool(opts.get("nulls_not_distinct") or False),
                "where_clause": str(opts["where"]) if opts.get("where") is not None else None,
            }
    return out


def _normalise_predicate(pred: str | None) -> str | None:
    if pred is None:
        return None
    pred = re.sub(r"::\w+", "", pred)
    pred = pred.replace("(", " ").replace(")", " ")
    return " ".join(pred.split()).lower()


def test_no_model_index_diverges_on_nulls_not_distinct(migrated_engine):
    db = _migrated_indexes(migrated_engine)
    mismatched = [
        f"{name} on {model['table_name']}: model={model['nulls_not_distinct']} "
        f"migrated_db={db[name]['nulls_not_distinct']}"
        for name, model in sorted(_model_indexes(migrated_engine).items())
        if name in db and model["nulls_not_distinct"] != db[name]["nulls_not_distinct"]
    ]
    assert not mismatched, (
        "model-declared index(es) disagree with the migration chain on NULLS NOT DISTINCT.\n"
        "The pytest schema is built from the models, so this means CI is enforcing a\n"
        "DIFFERENT uniqueness rule than every migrated database:\n  " + "\n  ".join(mismatched)
    )


def test_no_model_index_diverges_on_uniqueness(migrated_engine):
    db = _migrated_indexes(migrated_engine)
    mismatched = [
        f"{name} on {model['table_name']}: model unique={model['is_unique']} migrated_db unique={db[name]['is_unique']}"
        for name, model in sorted(_model_indexes(migrated_engine).items())
        if name in db and model["is_unique"] != db[name]["is_unique"]
    ]
    assert not mismatched, "model/migration uniqueness divergence:\n  " + "\n  ".join(mismatched)


def test_no_model_index_diverges_on_its_partial_predicate(migrated_engine):
    db = _migrated_indexes(migrated_engine)
    mismatched = [
        f"{name} on {model['table_name']}:\n      model: {model['where_clause']}\n      db   : {db[name]['where_clause']}"
        for name, model in sorted(_model_indexes(migrated_engine).items())
        if name in db and _normalise_predicate(model["where_clause"]) != _normalise_predicate(db[name]["where_clause"])
    ]
    assert not mismatched, "model/migration partial-predicate divergence:\n  " + "\n  ".join(mismatched)


def test_every_model_declared_index_is_built_by_the_migration_chain(migrated_engine):
    db = _migrated_indexes(migrated_engine)
    missing = sorted(set(_model_indexes(migrated_engine)) - set(db) - set(PRESENCE_EXEMPT))
    assert not missing, (
        "model declares index(es) that the CE migration chain never creates, so they\n"
        "exist in the create_all test schema and in NO real database:\n  " + "\n  ".join(missing)
    )


@pytest.mark.parametrize(
    ("name", "consequence"),
    [
        (
            "uq_project_taxonomy_active",
            "untyped/serial-less projects would stop being de-duplicated in production",
        ),
        (
            "uq_task_taxonomy_active",
            "two live typed tasks in one product could share a serial again",
        ),
    ],
)
def test_taxonomy_index_is_nulls_not_distinct_in_both_layers(migrated_engine, name, consequence):
    db = _migrated_indexes(migrated_engine)
    model = _model_indexes(migrated_engine)
    assert name in db, f"{name} is missing from the migrated schema entirely"
    assert name in model, f"{name} is no longer declared on its model"
    assert db[name]["nulls_not_distinct"] is True, (
        f"the migration chain no longer builds {name} with NULLS NOT DISTINCT -- {consequence}"
    )
    assert model[name]["nulls_not_distinct"] is True, (
        f"{name} lost postgresql_nulls_not_distinct=True on the model, so the "
        "create_all pytest schema is weaker than every migrated database (BE-9429)"
    )


def _model_column_nullability(engine: sa.Engine) -> dict[tuple[str, str], bool]:
    from giljo_mcp.models import Base

    built = _migrated_tables(engine)
    return {
        (table.name, col.name): bool(col.nullable)
        for table in Base.metadata.tables.values()
        if table.name in built
        for col in table.columns
    }


def _db_column_nullability(engine: sa.Engine) -> dict[tuple[str, str], bool]:
    with engine.connect() as conn:
        return {
            (r.table_name, r.column_name): r.is_nullable == "YES"
            for r in conn.execute(
                text(
                    "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            )
        }


def test_no_model_column_diverges_on_nullability(migrated_engine):
    db = _db_column_nullability(migrated_engine)
    diverged = [
        f"{table}.{column}: model nullable={model_nullable} migrated_db nullable={db[(table, column)]}"
        for (table, column), model_nullable in sorted(_model_column_nullability(migrated_engine).items())
        if (table, column) in db and model_nullable != db[(table, column)]
    ]
    assert not diverged, (
        "model column(s) disagree with the migration chain on NOT NULL.\n"
        "The pytest schema is built from the models, so a model that is MORE permissive\n"
        "than the chain lets CI flush rows every real database rejects (BE-9437):\n  " + "\n  ".join(diverged)
    )


def test_projects_product_id_is_not_null_in_both_layers(migrated_engine):
    db = _db_column_nullability(migrated_engine)
    model = _model_column_nullability(migrated_engine)
    key = ("projects", "product_id")
    assert key in db, "projects.product_id is missing from the migrated schema entirely"
    assert key in model, "projects.product_id is no longer declared on the Project model"
    assert db[key] is False, (
        "the migration chain no longer builds projects.product_id as NOT NULL -- orphan "
        "projects, which belong to no product, become insertable again (BE-9437)"
    )
    assert model[key] is False, (
        "the Project model relaxed product_id to nullable, so the create_all pytest schema "
        "is weaker than every migrated database again (BE-9437 / the BE-9429 defect class)"
    )


def test_the_exemption_list_does_not_rot(migrated_engine):
    known = set(_model_indexes(migrated_engine)) | set(_migrated_indexes(migrated_engine))
    stale = sorted(set(PRESENCE_EXEMPT) - known)
    assert not stale, "PRESENCE_EXEMPT names index(es) that exist in neither layer; remove them:\n  " + "\n  ".join(
        stale
    )
