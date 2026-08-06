# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Migration regression for ce_0084 -- heal neutralized tester/implementer/documenter
seed personas (BE-9259 audit blocker).

Real scratch PostgreSQL DB, real alembic. Covers ce_0084's byte-exact heal:

- A row whose ``user_instructions``/``description`` still byte-match the
  PRE-BE-9259 seed text are rewritten to the neutralized (post-BE-9259) text.
- A row whose text was genuinely user-edited (diverges from the old seed) is
  left byte-identical -- the migration must never guess at user prose.
- A row already healed (matches the NEW text, e.g. a tenant seeded after
  BE-9259 shipped) is a no-op.
- Idempotency: re-running against an already-migrated DB changes nothing
  further and does not crash (the "CE reruns upgrade head on every boot"
  scenario).

Mirrors tests/integration/migrations/test_ce_0068_purge_completed_sequence_runs.py.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from tests.helpers.test_db_helper import worker_suffix


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

SCRATCH_DB = f"{os.environ.get('GILJO_BOOTSTRAP_TEST_DB', 'giljo_test_bootstrap')}{worker_suffix()}"
ADMIN_USER = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
ADMIN_PASSWORD = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

PRODUCTION_DB_NAME = "giljo_mcp"

_PRE = "ce_0083_projects_parked_status"
_REV = "ce_0084_heal_neutralized_seed_personas"

# Load the migration module directly so the test's expected OLD/NEW text can
# never drift from what the migration itself writes (single source of truth).
_MIGRATION_PATH = PROJECT_ROOT / "migrations" / "versions" / f"{_REV}.py"
_spec = importlib.util.spec_from_file_location(_REV, _MIGRATION_PATH)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)

OLD_TESTER_DESCRIPTION = _migration._OLD_TESTER_DESCRIPTION
NEW_TESTER_DESCRIPTION = _migration._NEW_TESTER_DESCRIPTION
OLD_TESTER_UI = _migration._OLD_TESTER_UI
NEW_TESTER_UI = _migration._NEW_TESTER_UI
OLD_IMPLEMENTER_UI = _migration._OLD_IMPLEMENTER_UI
NEW_IMPLEMENTER_UI = _migration._NEW_IMPLEMENTER_UI
OLD_DOCUMENTER_UI = _migration._OLD_DOCUMENTER_UI
NEW_DOCUMENTER_UI = _migration._NEW_DOCUMENTER_UI


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
    """Fresh schema built up to ce_0083 (the pre-revision), ready for seeding."""
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    yield scratch_engine
    _drop_all_objects(scratch_engine)


# --------------------------------------------------------------------------- #
# Seed helper (raw SQL -- the ORM models are not needed for a migration test) #
# --------------------------------------------------------------------------- #

TK = "tk_ce0084"


def _insert_template(
    engine: sa.Engine,
    *,
    name: str,
    description: str,
    user_instructions: str,
    version: str = "1.0.0",
) -> str:
    template_id = str(uuid4())
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_templates "
                "(id, tenant_key, name, category, role, cli_tool, background_color, "
                " description, system_instructions, user_instructions, model, tools, "
                " variables, behavioral_rules, success_criteria, tool, version, "
                " is_active, is_default, tags) "
                "VALUES "
                "(:id, :tk, :name, 'role', :name, 'claude', '#000000', "
                " :description, 'bootstrap', :user_instructions, 'sonnet', NULL, "
                " '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 'claude', :version, "
                ' true, true, \'["default", "tenant"]\'::jsonb)'
            ),
            {
                "id": template_id,
                "tk": TK,
                "name": name,
                "description": description,
                "user_instructions": user_instructions,
                "version": version,
            },
        )
        conn.commit()
    return template_id


def _fetch_row(engine: sa.Engine, template_id: str) -> dict:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text("SELECT description, user_instructions FROM agent_templates WHERE id = :id"),
                {"id": template_id},
            )
            .mappings()
            .one()
        )
        return dict(row)


@pytest.mark.integration
class TestCe0084HealNeutralizedSeedPersonas:
    def test_unedited_old_tester_row_healed(self, scratch_at_pre: sa.Engine) -> None:
        tid = _insert_template(
            scratch_at_pre,
            name="tester",
            description=OLD_TESTER_DESCRIPTION,
            user_instructions=OLD_TESTER_UI,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        row = _fetch_row(scratch_at_pre, tid)
        assert row["description"] == NEW_TESTER_DESCRIPTION
        assert row["user_instructions"] == NEW_TESTER_UI

    def test_unedited_old_implementer_row_healed(self, scratch_at_pre: sa.Engine) -> None:
        tid = _insert_template(
            scratch_at_pre,
            name="implementer",
            description="Implementation specialist for writing production-grade code",
            user_instructions=OLD_IMPLEMENTER_UI,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        row = _fetch_row(scratch_at_pre, tid)
        assert row["user_instructions"] == NEW_IMPLEMENTER_UI

    def test_unedited_old_documenter_row_healed(self, scratch_at_pre: sa.Engine) -> None:
        tid = _insert_template(
            scratch_at_pre,
            name="documenter",
            description="Documentation specialist for clear, comprehensive project documentation",
            user_instructions=OLD_DOCUMENTER_UI,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        row = _fetch_row(scratch_at_pre, tid)
        assert row["user_instructions"] == NEW_DOCUMENTER_UI

    def test_user_edited_row_survives_byte_identical(self, scratch_at_pre: sa.Engine) -> None:
        """A tenant's hand-edited tester prose must NOT be touched by the heal."""
        edited_ui = OLD_TESTER_UI + "\n\nCUSTOM: also verify our internal deploy checklist."
        tid = _insert_template(
            scratch_at_pre,
            name="tester",
            description=OLD_TESTER_DESCRIPTION,
            user_instructions=edited_ui,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        row = _fetch_row(scratch_at_pre, tid)
        # user_instructions diverged from the old seed -> untouched, byte-identical.
        assert row["user_instructions"] == edited_ui
        # description still byte-matched the old seed -> that column IS healed
        # independently (each column's guard is its own byte-equality check).
        assert row["description"] == NEW_TESTER_DESCRIPTION

    def test_already_healed_row_is_noop(self, scratch_at_pre: sa.Engine) -> None:
        """A tenant seeded AFTER BE-9259 already has the new text -- must stay put."""
        tid = _insert_template(
            scratch_at_pre,
            name="documenter",
            description="Documentation specialist for clear, comprehensive project documentation",
            user_instructions=NEW_DOCUMENTER_UI,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        row = _fetch_row(scratch_at_pre, tid)
        assert row["user_instructions"] == NEW_DOCUMENTER_UI

    def test_rerun_is_idempotent(self, scratch_at_pre: sa.Engine) -> None:
        """Re-running ce_0084 (boot-rerun / stamp-behind) heals once, then no-ops."""
        healed_tid = _insert_template(
            scratch_at_pre,
            name="implementer",
            description="Implementation specialist for writing production-grade code",
            user_instructions=OLD_IMPLEMENTER_UI,
        )
        edited_ui = OLD_IMPLEMENTER_UI.replace("Test edge cases", "Test edge cases AND our own weird ones")
        edited_tid = _insert_template(
            scratch_at_pre,
            name="implementer",
            description="Implementation specialist for writing production-grade code",
            user_instructions=edited_ui,
            version="1.0.1",
        )

        assert _run_alembic("upgrade", _REV).returncode == 0
        assert _fetch_row(scratch_at_pre, healed_tid)["user_instructions"] == NEW_IMPLEMENTER_UI
        assert _fetch_row(scratch_at_pre, edited_tid)["user_instructions"] == edited_ui

        assert _run_alembic("stamp", _PRE).returncode == 0
        reup = _run_alembic("upgrade", _REV)
        assert reup.returncode == 0, f"idempotent re-upgrade failed:\n{reup.stdout}\n{reup.stderr}"

        assert _fetch_row(scratch_at_pre, healed_tid)["user_instructions"] == NEW_IMPLEMENTER_UI
        assert _fetch_row(scratch_at_pre, edited_tid)["user_instructions"] == edited_ui
