# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9429: model-declared indexes must match what the migration chain builds.

THE DEFECT THIS GUARDS. ``uq_project_taxonomy_active`` was declared in
``models/projects.py`` WITHOUT ``postgresql_nulls_not_distinct=True`` while every
migration that creates it (``baseline_v38_unified.py``, ``baseline_v37_unified.py``,
the historical ``fix_taxonomy_nulls_not_distinct``) creates it WITH
``NULLS NOT DISTINCT``. The pytest schema is built by ``Base.metadata.create_all()``
(``tests/helpers/test_db_helper.py``), so **every test database was weaker than
every migrated database** -- a uniqueness rule prod enforces and CI did not.

WHY NEITHER EXISTING GUARD CAUGHT IT, and why this file is a THIRD one rather
than an extension of either:

* ``test_inf5060_squash_baseline_v38.py`` snapshots ``pg_indexes.indexdef`` (which
  does render ``NULLS NOT DISTINCT``), but it compares the fast path against a
  chain replay -- **migration versus migration**. The model is not a party to it.
* the repo's schema-drift gate DOES compare model against migration and
  Alembic DOES report this difference (as a ``remove_index``/``add_index`` pair).
  But the gate fails only on ``add_table``/``add_column``/``remove_column`` and
  collapses everything else into an anonymous ``Counter`` -- so CI printed
  ``{'remove_index': 2, 'add_index': 1}`` and passed, with no way for a reader to
  tell a shipped uniqueness guarantee from the known-benign ``idx_pme_fts``.

So nothing in the tree compared model to migration **per index, by name**. That
is the gap, and this file is deliberately a GENERAL parity guard rather than a
spot check on one index: the next ``op.create_index`` that silently drops a
dialect option fails here. That is not hypothetical -- ``ce_0059`` did exactly
that to ``uq_task_taxonomy_active`` while rewriting raw SQL as kwargs. That
second loss was repaired by BE-9431 (``ce_0095``, healing) and both taxonomy
indexes now carry a named pin here in addition to the general guard.

BE-9437 added a SECOND axis to this module: model-vs-chain **column NOT NULL**.
``projects.product_id`` had been NOT NULL in every real database since ``ce_0004``
while the model still said ``nullable=True`` -- the identical "test schema weaker
than production" shape, in a catalog no index comparison reads. The two live in
one module because they ask one question of one expensive fixture.

SAFETY: scratch DB only (the per-worker, per-clone ``bootstrap_db_base()``); the
live DBs giljo_mcp / giljo_mcp_ce are NEVER touched. Parallel-safe under xdist.
"""

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

# --------------------------------------------------------------------------
# Known, DOCUMENTED residue. Every entry names WHY it is exempt. An exemption
# that cannot be justified in one line does not belong here -- it belongs in a
# migration. Deliberately keyed by index name so the list stays auditable
# instead of being a silent "ignore anything that fails".
# --------------------------------------------------------------------------
PRESENCE_EXEMPT: dict[str, str] = {
    # ce_0069 (BE-8000c) records this one: a functional GIN full-text index whose
    # expression Alembic autogenerate cannot round-trip. Migration-created, and
    # the model cannot express it -- so it is DB-only by construction.
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
        # RAISE, never skip. A parity guard that quietly skips itself when its
        # credentials are missing is a guard nobody notices losing -- which is the
        # exact failure BE-9429 is about. Matching the idiom of its neighbour in
        # this directory (test_inf5060_squash_baseline_v38.py), which raises for
        # the same reason on the same credential. CI supplies this
        # (ci.yml: POSTGRES_OWNER_PASSWORD), so this fires only on a genuinely
        # misconfigured environment -- precisely when you want to hear about it.
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
    """Create the scratch DB if missing -- mirrors ``test_be_5115_vision_docs_inline_only``.

    NOT redundant with this directory's conftest. ``_ensure_scratch_db_as_superuser``
    provisions the DB only when ``POSTGRES_SUPERUSER_PASSWORD`` is set, and returns
    early otherwise, "leaving creation to the test file's own fallback". **CI is
    exactly that case** -- the postgres:18 image has no ``postgres`` role, so CI
    makes ``giljo_test`` (superuser + CREATEDB) the OWNER user and never sets a
    superuser password. So on the runner every module here must create its own
    scratch DB, and a module that assumes the conftest did it fails with
    "database ... does not exist" on whichever worker happens to run it first.

    The check-then-create is safe without a lock because the scratch name carries
    the per-worker suffix, so no two workers ever target this name.
    """
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
    """A scratch DB migrated to the CE chain head -- i.e. what a real install has."""
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
    """Every ``Index(...)`` the models declare **on a table this chain builds**.

    SCOPED TO THE MIGRATED TABLES ON PURPOSE, and that is not a convenience.
    ``Base.metadata`` is process-global, and importing the SaaS model modules
    registers their tables onto it as a side effect -- which something else in a
    full run does. Unscoped, this module would compare SaaS-table indexes
    (``org_api_keys``, ``password_reset_tokens``, ``account_deletion_requests``…)
    against a CE-migrated database and correctly report ~30 of them missing, so
    the result would depend on which tests happened to import first. Comparing
    only the tables the chain under test actually creates is both the right scope
    for a chain-parity check and immune to import order (CLAUDE.md: no test
    ordering dependencies).

    UniqueConstraint objects are deliberately NOT included: Postgres implements
    them with a backing index whose name is the CONSTRAINT's, so they compare
    correctly only against pg_constraint, not pg_index.
    """
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
    """Compare partial-index predicates by MEANING, not by rendering.

    Postgres re-renders a predicate from its parse tree, so the model's
    ``status = 'active'`` comes back as ``(status = 'active'::project_status)``.
    Casts, outer parens and whitespace are rendering; the rest is the predicate.
    """
    if pred is None:
        return None
    pred = re.sub(r"::\w+", "", pred)
    pred = pred.replace("(", " ").replace(")", " ")
    return " ".join(pred.split()).lower()


def test_no_model_index_diverges_on_nulls_not_distinct(migrated_engine):
    """THE BE-9429 GUARD, generalised.

    ``NULLS NOT DISTINCT`` decides whether a unique index constrains rows that
    carry a NULL in the indexed tuple -- which, for the taxonomy indexes, is
    ordinary rows. A model that omits it while the chain declares it makes the
    test schema permit what production rejects.
    """
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
    """A model that claims ``unique=True`` over a chain that built a plain index
    (or the reverse) is the same class of divergence, one axis over."""
    db = _migrated_indexes(migrated_engine)
    mismatched = [
        f"{name} on {model['table_name']}: model unique={model['is_unique']} migrated_db unique={db[name]['is_unique']}"
        for name, model in sorted(_model_indexes(migrated_engine).items())
        if name in db and model["is_unique"] != db[name]["is_unique"]
    ]
    assert not mismatched, "model/migration uniqueness divergence:\n  " + "\n  ".join(mismatched)


def test_no_model_index_diverges_on_its_partial_predicate(migrated_engine):
    """A partial index's WHERE clause decides WHICH rows it constrains, so a
    divergence there is a silent scope change, not a formatting nit."""
    db = _migrated_indexes(migrated_engine)
    mismatched = [
        f"{name} on {model['table_name']}:\n      model: {model['where_clause']}\n      db   : {db[name]['where_clause']}"
        for name, model in sorted(_model_indexes(migrated_engine).items())
        if name in db and _normalise_predicate(model["where_clause"]) != _normalise_predicate(db[name]["where_clause"])
    ]
    assert not mismatched, "model/migration partial-predicate divergence:\n  " + "\n  ".join(mismatched)


def test_every_model_declared_index_is_built_by_the_migration_chain(migrated_engine):
    """A model index no migration creates exists in the test schema and nowhere else."""
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
            # BE-9431. Same index, same failure, one table over: ce_0059 dropped
            # this flag while widening the predicate and nothing noticed for 36
            # revisions. ce_0095 restored it (healing duplicates first); this pin
            # is what makes a second silent loss fail immediately.
            "uq_task_taxonomy_active",
            "two live typed tasks in one product could share a serial again",
        ),
    ],
)
def test_taxonomy_index_is_nulls_not_distinct_in_both_layers(migrated_engine, name, consequence):
    """The specific pins for the two reported defects.

    Kept alongside the general guard on purpose: the general test would also go
    green if someone deleted the index from both layers, and these would not.
    """
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
    """``(table, column) -> nullable`` for every model column on a built table.

    Scoped to the migrated tables for the same reason ``_model_indexes`` is:
    ``Base.metadata`` is process-global and a SaaS model import would otherwise
    drag SaaS tables into a CE-chain comparison.
    """
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
    """BE-9437: the same parity question as the index guards, one axis over.

    WHY THIS AXIS EXISTS, and why the index guards above could not have caught
    it. ``projects.product_id`` was set NOT NULL by ``ce_0004`` in April, and
    ``baseline_v38_unified.py`` creates it NOT NULL, so every real database has
    rejected an orphan project for 91 revisions. The MODEL kept
    ``nullable=True`` the whole time -- and the pytest schema is built by
    ``Base.metadata.create_all()``, so CI happily flushed projects that
    production would refuse. Same shape as BE-9429 (test schema weaker than
    every migrated database), same consequence (a rule prod enforces and CI does
    not), different catalog: a column's NOT NULL is not an index, so nothing in
    this file's index comparison could see it. ``ce_0069`` recorded the
    divergence as known drift and deferred it to a product decision; the
    operator ruled it on 2026-08-15 (a project MUST belong to a product) and
    BE-9437 closed it by moving the model to the database, not the reverse.

    Deliberately NOT given an exemption dict. Measured at the CE head on
    2026-08-15 across 46 tables: with ``projects.product_id`` fixed the count is
    zero, and with it reverted it is exactly one. A guard that starts at zero
    needs no documented residue, and adding an empty escape hatch invites the
    next divergence to be filed in it instead of fixed.

    Lives in this module rather than its own so it shares ``migrated_engine``:
    that fixture replays the entire migration chain, and a second module would
    pay for a second replay to ask a question about the same two layers.
    """
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
    """The specific pin for BE-9437, alongside the general guard above.

    The general test would also pass if ``product_id`` were dropped from both
    layers, or relaxed in both. This one says what the operator actually ruled:
    a project belongs to a product, in the model and in the database.
    """
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
    """An exemption for an index that no longer exists is dead weight that hides
    the next real one. If a listed name is genuinely gone, delete its entry."""
    known = set(_model_indexes(migrated_engine)) | set(_migrated_indexes(migrated_engine))
    stale = sorted(set(PRESENCE_EXEMPT) - known)
    assert not stale, "PRESENCE_EXEMPT names index(es) that exist in neither layer; remove them:\n  " + "\n  ".join(
        stale
    )
