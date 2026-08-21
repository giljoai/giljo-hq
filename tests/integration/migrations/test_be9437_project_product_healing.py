# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Migration regression for BE-9437 — ``ce_0004`` keeps orphan projects instead of deleting them.

Real scratch PostgreSQL DB, real alembic. ``ce_0004`` enforces
``projects.product_id NOT NULL``, and as shipped it made room for that constraint
with ``DELETE FROM projects WHERE product_id IS NULL`` -- silent, unrecoverable
data loss on any install where "none expected in a healthy install" was wrong.
The CE installer reruns ``alembic upgrade`` on every boot with no operator
present to notice. BE-9437 rewrote the migration to BIND those rows to a product
instead, under the operator's 2026-08-15 ruling that a project must belong to a
product -- which decides where the rows go, not whether they live.

THE DISCRIMINATING CONTROL is ``test_the_orphan_survives_the_upgrade``: against
the shipped migration that project is GONE after the upgrade. Every other
assertion here would pass just as happily against a chain that deleted the row
and then found nothing left to collide -- which is exactly how a destructive
migration reads as a clean one.

Binding is not free, and the rest of this file is about that. An orphan moving
into a product's bucket meets partial unique indexes that NULL product_ids
escape today, and any of them would abort the upgrade -- turning a boot-time
migration into a boot failure, the outcome the rewrite exists to prevent:

- ``idx_project_single_active_per_product`` (UNIQUE(product_id) WHERE
  status='active') -- several ACTIVE orphans can legitimately coexist while their
  product_id is NULL.
- ``uq_project_taxonomy_active`` (NULLS NOT DISTINCT, WHERE deleted_at IS NULL)
  -- the arriving row can collide with one already in the bucket.
- ``idx_product_single_active_per_tenant`` (UNIQUE(tenant_key) WHERE
  is_active=true) -- reached only when a placeholder product has to be created,
  and it does not exclude soft-deleted rows, so a trashed-but-active product
  still holds the slot.

Mirrors tests/integration/migrations/test_be9431_task_index_teeth.py, whose
heal-then-enforce shape and reassign-above-the-watermark rule ce_0004 now follows.
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

from tests.helpers.test_db_helper import bootstrap_db_base, worker_suffix


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

SCRATCH_DB = f"{bootstrap_db_base()}{worker_suffix()}"
ADMIN_USER = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
ADMIN_PASSWORD = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

PRODUCTION_DB_NAME = "giljo_mcp"

_PRE = "ce_0003_widen_alembic_version"
_REV = "ce_0004_projects_product_id_not_null"


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
    """Fresh schema built up to ce_0003 (the pre-revision), ready for seeding."""
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    yield scratch_engine
    _drop_all_objects(scratch_engine)


# --------------------------------------------------------------------------- #
# Seed helpers (raw SQL — the ORM models are not needed for a migration test)  #
# --------------------------------------------------------------------------- #

TK = "tk_be9437"


def _seed_product(
    engine: sa.Engine,
    name: str,
    *,
    tenant_key: str = TK,
    created_at: str | None = None,
    is_active: bool = False,
) -> str:
    """Seed a product. ``is_active`` defaults to FALSE deliberately.

    ``idx_product_single_active_per_tenant`` is UNIQUE(tenant_key) WHERE
    is_active = true, so a helper that defaulted to active could seed at most one
    product per tenant -- and the "which product wins" cases here need several.
    Only the tests that are ABOUT that index set it.
    """
    product_id = str(uuid4())
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO products (id, tenant_key, name, is_active, created_at) "
                "VALUES (:id, :tk, :name, :active, COALESCE(CAST(:created AS timestamptz), now()))"
            ),
            {"id": product_id, "tk": tenant_key, "name": name, "created": created_at, "active": is_active},
        )
        conn.commit()
    return product_id


def _seed_project(
    engine: sa.Engine,
    name: str,
    *,
    tenant_key: str = TK,
    product_id: str | None = None,
    status: str = "inactive",
    series_number: int | None = None,
    project_type_id: str | None = None,
    trashed: bool = False,
) -> str:
    """INSERT a project directly. Raises IntegrityError if an index refuses it."""
    project_id = str(uuid4())
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, tenant_key, product_id, name, alias, description, mission, "
                "status, series_number, project_type_id, deleted_at) "
                "VALUES (:id, :tk, :pid, :name, :alias, 'd', '', :status, :series, :ptid, "
                "CASE WHEN :trashed THEN CURRENT_TIMESTAMP ELSE NULL END)"
            ),
            {
                "id": project_id,
                "tk": tenant_key,
                "pid": product_id,
                "name": name,
                "alias": str(uuid4())[:6],
                "status": status,
                "series": series_number,
                "ptid": project_type_id,
                "trashed": trashed,
            },
        )
        conn.commit()
    return project_id


def _project_row(engine: sa.Engine, project_id: str) -> sa.Row | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT product_id, status, series_number, subseries, deleted_at FROM projects WHERE id = :id"),
            {"id": project_id},
        ).one_or_none()


def _product_id_is_nullable(engine: sa.Engine) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='projects' AND column_name='product_id'"
                )
            ).scalar()
            == "YES"
        )


def _product_names(engine: sa.Engine, tenant_key: str = TK) -> list[str]:
    with engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT name FROM products WHERE tenant_key = :tk ORDER BY created_at, id"),
                {"tk": tenant_key},
            )
        ]


@pytest.mark.integration
class TestBe9437ProjectProductHealing:
    def test_the_pre_revision_accepts_an_orphan_project(self, scratch_at_pre: sa.Engine) -> None:
        """THE PRE-STATE, and the reason any of this is needed.

        At ce_0003 ``product_id`` is nullable and a product-less project inserts
        cleanly. If this ever fails, the pre-state changed and every assertion in
        this file stops meaning anything.
        """
        orphan = _seed_project(scratch_at_pre, "orphan")

        assert _product_id_is_nullable(scratch_at_pre) is True
        assert _project_row(scratch_at_pre, orphan).product_id is None

    def test_the_orphan_survives_the_upgrade(self, scratch_at_pre: sa.Engine) -> None:
        """THE DISCRIMINATING CONTROL. Against the shipped ce_0004 this row is GONE.

        The old migration opened with ``DELETE FROM projects WHERE product_id IS
        NULL``. Nothing else in this file can tell a healing migration from a
        deleting one -- delete the rows and every collision assertion below passes
        vacuously, because there is nothing left to collide.
        """
        product = _seed_product(scratch_at_pre, "The Only Product")
        orphan = _seed_project(scratch_at_pre, "orphan")

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        row = _project_row(scratch_at_pre, orphan)
        assert row is not None, "the orphan project was DELETED -- this is the BE-9437 defect"
        assert row.product_id == product, "the orphan must be bound to the tenant's product"
        assert row.deleted_at is None, "healing must not soft-delete either"
        assert _product_id_is_nullable(scratch_at_pre) is False, "the column must end up NOT NULL"

    def test_the_upgrade_still_enforces_not_null_afterwards(self, scratch_at_pre: sa.Engine) -> None:
        """The constraint is the POINT of the migration; healing must not cost it.

        The property, not just the catalog flag -- the same INSERT the
        pre-revision accepted is now refused.
        """
        _seed_product(scratch_at_pre, "p")
        assert _run_alembic("upgrade", _REV).returncode == 0

        with pytest.raises(sa.exc.IntegrityError):
            _seed_project(scratch_at_pre, "new orphan")

    def test_multiple_products_bind_to_the_oldest(self, scratch_at_pre: sa.Engine) -> None:
        """The documented rule when the choice is ambiguous: oldest, deterministically."""
        oldest = _seed_product(scratch_at_pre, "First", created_at="2020-01-01T00:00:00Z")
        _seed_product(scratch_at_pre, "Second", created_at="2021-01-01T00:00:00Z")
        orphan = _seed_project(scratch_at_pre, "orphan")

        assert _run_alembic("upgrade", _REV).returncode == 0

        assert _project_row(scratch_at_pre, orphan).product_id == oldest

    def test_a_soft_deleted_product_is_not_a_binding_target(self, scratch_at_pre: sa.Engine) -> None:
        """Filing a live project into a trashed product hides it as effectively as
        deleting it, so the tenant gets a real product instead.

        The trashed product is seeded ACTIVE on purpose, which makes this the
        regression for a second index too: ``idx_product_single_active_per_tenant``
        is UNIQUE(tenant_key) WHERE is_active=true and does NOT exclude
        soft-deleted rows, so this tenant's active slot is already taken. A
        placeholder inserted with a hardcoded ``is_active = true`` raises a unique
        violation here and aborts the whole upgrade.
        """
        with scratch_at_pre.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO products (id, tenant_key, name, is_active, deleted_at) "
                    "VALUES (:id, :tk, 'Trashed', true, now())"
                ),
                {"id": str(uuid4()), "tk": TK},
            )
            conn.commit()
        orphan = _seed_project(scratch_at_pre, "orphan")

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade aborted creating the placeholder:\n{up.stdout}\n{up.stderr}"

        bound_to = _project_row(scratch_at_pre, orphan).product_id
        with scratch_at_pre.connect() as conn:
            name, deleted_at, is_active = conn.execute(
                text("SELECT name, deleted_at, is_active FROM products WHERE id = :id"), {"id": bound_to}
            ).one()
        assert deleted_at is None, "an orphan must never be filed into a soft-deleted product"
        assert name == "Recovered Projects"
        assert is_active is False, "the tenant's active slot was taken, so the placeholder must not claim it"

    def test_a_tenant_with_no_product_gets_one_rather_than_losing_its_projects(self, scratch_at_pre: sa.Engine) -> None:
        """The case with no good answer, resolved the only non-destructive way.

        Refusing to boot is not available (the CE installer reruns this with
        nobody to ask), and deleting is the defect. So a product is created, named
        so the user can find what happened to their projects.
        """
        orphan = _seed_project(scratch_at_pre, "orphan")

        assert _run_alembic("upgrade", _REV).returncode == 0

        row = _project_row(scratch_at_pre, orphan)
        assert row is not None and row.product_id is not None
        assert _product_names(scratch_at_pre) == ["Recovered Projects"]

    def test_a_second_active_orphan_is_deactivated_not_dropped(self, scratch_at_pre: sa.Engine) -> None:
        """``idx_project_single_active_per_product`` collision.

        Two ACTIVE orphans are legal while product_id is NULL (NULLS DISTINCT), and
        binding both to one product would violate that unique index and abort the
        upgrade. The incumbent keeps its status; the later row is demoted. Both
        live: status is one click to restore, a failed boot is not.
        """
        product = _seed_product(scratch_at_pre, "The Only Product")
        first = _seed_project(scratch_at_pre, "active one", status="active", series_number=1)
        second = _seed_project(scratch_at_pre, "active two", status="active", series_number=2)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade aborted on an active collision:\n{up.stdout}\n{up.stderr}"

        kept, demoted = _project_row(scratch_at_pre, first), _project_row(scratch_at_pre, second)
        assert kept.status == "active", "the earliest active project keeps its status"
        assert demoted.status == "inactive", "the later one is deactivated, not deleted"
        assert kept.product_id == product and demoted.product_id == product
        assert demoted.deleted_at is None

    def test_an_incumbent_active_project_outranks_an_arriving_orphan(self, scratch_at_pre: sa.Engine) -> None:
        """The collision the other way round: the product already has an active
        project, and the orphan is the newcomer. The row the user is looking at
        must not be deactivated by an upgrade."""
        product = _seed_product(scratch_at_pre, "The Only Product")
        incumbent = _seed_project(scratch_at_pre, "incumbent", product_id=product, status="active", series_number=1)
        orphan = _seed_project(scratch_at_pre, "arriving", status="active", series_number=2)

        assert _run_alembic("upgrade", _REV).returncode == 0

        assert _project_row(scratch_at_pre, incumbent).status == "active"
        assert _project_row(scratch_at_pre, orphan).status == "inactive"

    def test_a_taxonomy_collision_is_renumbered_above_the_watermark(self, scratch_at_pre: sa.Engine) -> None:
        """``uq_project_taxonomy_active`` collision.

        The orphan carries serial 1 with no type, and the product already holds a
        live row with the same (type, serial, subseries) tuple -- a genuine
        collision, since that index is NULLS NOT DISTINCT. The ARRIVING row is
        renumbered above the bucket's watermark; the row already filed there keeps
        its number.
        """
        product = _seed_product(scratch_at_pre, "The Only Product")
        incumbent = _seed_project(scratch_at_pre, "already here", product_id=product, series_number=1)
        _seed_project(scratch_at_pre, "high water", product_id=product, series_number=7)
        orphan = _seed_project(scratch_at_pre, "colliding orphan", series_number=1)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade aborted on a taxonomy collision:\n{up.stdout}\n{up.stderr}"

        assert _project_row(scratch_at_pre, incumbent).series_number == 1, "the row already filed keeps its serial"
        assert _project_row(scratch_at_pre, orphan).series_number == 8, "reassigned above the watermark (7 + 1)"

    def test_a_non_colliding_orphan_keeps_its_serial(self, scratch_at_pre: sa.Engine) -> None:
        """The renumbering is a collision remedy, not a blanket renumber -- an
        orphan whose serial is free in the target bucket keeps it."""
        product = _seed_product(scratch_at_pre, "The Only Product")
        _seed_project(scratch_at_pre, "already here", product_id=product, series_number=1)
        orphan = _seed_project(scratch_at_pre, "no collision", series_number=5)

        assert _run_alembic("upgrade", _REV).returncode == 0

        assert _project_row(scratch_at_pre, orphan).series_number == 5

    def test_a_soft_deleted_orphan_is_bound_but_not_renumbered(self, scratch_at_pre: sa.Engine) -> None:
        """The taxonomy index is partial on ``deleted_at IS NULL``, so a trashed
        orphan is out of its scope -- it may share a serial with a live row, and
        renumbering it would be churn on data the user already discarded."""
        product = _seed_product(scratch_at_pre, "The Only Product")
        _seed_project(scratch_at_pre, "live", product_id=product, series_number=1)
        trashed = _seed_project(scratch_at_pre, "trashed orphan", series_number=1, trashed=True)

        assert _run_alembic("upgrade", _REV).returncode == 0

        row = _project_row(scratch_at_pre, trashed)
        assert row.product_id == product, "a trashed orphan is still bound -- NOT NULL applies to every row"
        assert row.series_number == 1, "but it is not a duplicate here, so it is not renumbered"

    def test_each_tenant_binds_within_its_own_products(self, scratch_at_pre: sa.Engine) -> None:
        """Tenant isolation is not suspended for a backfill: an orphan may never
        land on another tenant's product."""
        mine = _seed_product(scratch_at_pre, "Mine")
        other_tenant = "tk_be9437_other"
        theirs = _seed_product(scratch_at_pre, "Theirs", tenant_key=other_tenant)
        my_orphan = _seed_project(scratch_at_pre, "mine")
        their_orphan = _seed_project(scratch_at_pre, "theirs", tenant_key=other_tenant)

        assert _run_alembic("upgrade", _REV).returncode == 0

        assert _project_row(scratch_at_pre, my_orphan).product_id == mine
        assert _project_row(scratch_at_pre, their_orphan).product_id == theirs

    def test_rerun_is_idempotent(self, scratch_at_pre: sa.Engine) -> None:
        """The CE installer's every-boot ``alembic upgrade`` re-entry: the second
        run finds the column already NOT NULL and changes nothing."""
        _seed_product(scratch_at_pre, "The Only Product")
        orphan = _seed_project(scratch_at_pre, "orphan", status="active", series_number=3)

        assert _run_alembic("upgrade", _REV).returncode == 0
        first = _project_row(scratch_at_pre, orphan)

        assert _run_alembic("stamp", _PRE).returncode == 0
        reup = _run_alembic("upgrade", _REV)
        assert reup.returncode == 0, f"idempotent re-upgrade failed:\n{reup.stdout}\n{reup.stderr}"

        assert _project_row(scratch_at_pre, orphan) == first
        assert _product_names(scratch_at_pre) == ["The Only Product"], "no second placeholder product on rerun"

    def test_downgrade_then_upgrade_round_trips(self, scratch_at_pre: sa.Engine) -> None:
        """The chain stays walkable: downgrade relaxes the column (schema only,
        the bound rows keep their product) and upgrade re-enforces it."""
        product = _seed_product(scratch_at_pre, "The Only Product")
        orphan = _seed_project(scratch_at_pre, "orphan")

        assert _run_alembic("upgrade", _REV).returncode == 0
        assert _product_id_is_nullable(scratch_at_pre) is False

        down = _run_alembic("downgrade", _PRE)
        assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"
        assert _product_id_is_nullable(scratch_at_pre) is True
        assert _project_row(scratch_at_pre, orphan).product_id == product, "the backfill is not reverted"

        assert _run_alembic("upgrade", _REV).returncode == 0
        assert _product_id_is_nullable(scratch_at_pre) is False
