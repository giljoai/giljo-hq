# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Migration regression for ce_0090 -- heal the "GiljoAI MCP" -> "Giljo HQ"
orchestrator identity prose (BE-9361) on legacy ``agent_templates`` rows.

Real scratch PostgreSQL DB, real alembic. Mirrors
tests/integration/migrations/test_ce_0085_heal_giljo_hq_bootstrap_rebrand.py.

ce_0090 differs from ce_0084/ce_0085 in kind: those swap one byte-exact text
generation, this one replaces two stable SUBSTRINGS so it reaches a legacy
orchestrator row from ANY older seed generation. The cases below pin that
difference -- notably that surrounding user prose survives untouched, which a
byte-exact heal could not offer.
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

_PRE = "ce_0089_be9348_repair_absorbed_closeout_arguments"
_REV = "ce_0090_heal_giljo_hq_orchestrator_identity"

# Load the migration module directly so the test's expected old/new substrings
# can never drift from what the migration itself writes (single source of truth).
_MIGRATION_PATH = PROJECT_ROOT / "migrations" / "versions" / f"{_REV}.py"
_spec = importlib.util.spec_from_file_location(_REV, _MIGRATION_PATH)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)

REPLACEMENTS = _migration._REPLACEMENTS
OLD_SENTENCE, NEW_SENTENCE = REPLACEMENTS[0]
OLD_HEADING, NEW_HEADING = REPLACEMENTS[1]

_CUSTOM_LINE = "CUSTOM: our own onboarding note the migration must not disturb."

LEGACY_ORCHESTRATOR_UI = (
    f"{OLD_HEADING}\n"
    "\n"
    "## Identity & Environment\n"
    "\n"
    f"{OLD_SENTENCE} - a multi-tenant system coordinating specialized AI agents.\n"
    "\n"
    f"{_CUSTOM_LINE}"
)

HEALED_ORCHESTRATOR_UI = (
    f"{NEW_HEADING}\n"
    "\n"
    "## Identity & Environment\n"
    "\n"
    f"{NEW_SENTENCE} - a multi-tenant system coordinating specialized AI agents.\n"
    "\n"
    f"{_CUSTOM_LINE}"
)


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
    """Fresh schema built up to ce_0089 (the pre-revision), ready for seeding."""
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    yield scratch_engine
    _drop_all_objects(scratch_engine)


TK = "tk_ce0090"


def _insert_template(engine: sa.Engine, *, name: str, user_instructions: str, version: str = "1.0.0") -> str:
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
                " 'test role', 'test bootstrap', :user_instructions, 'sonnet', NULL, "
                " '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 'claude', :version, "
                ' true, true, \'["default", "tenant"]\'::jsonb)'
            ),
            {
                "id": template_id,
                "tk": TK,
                "name": name,
                "user_instructions": user_instructions,
                "version": version,
            },
        )
        conn.commit()
    return template_id


def _fetch_user_instructions(engine: sa.Engine, template_id: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT user_instructions FROM agent_templates WHERE id = :id"),
            {"id": template_id},
        ).scalar_one()


@pytest.mark.integration
class TestCe0090HealGiljoHqOrchestratorIdentity:
    def test_legacy_orchestrator_row_fully_healed(self, scratch_at_pre: sa.Engine) -> None:
        """Both residuals a legacy row can carry -- the heading BE-9275b left and
        the identity sentence BE-9361 flipped -- are healed in one pass."""
        tid = _insert_template(scratch_at_pre, name="orchestrator", user_instructions=LEGACY_ORCHESTRATOR_UI)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        healed = _fetch_user_instructions(scratch_at_pre, tid)
        assert healed == HEALED_ORCHESTRATOR_UI
        assert "GiljoAI MCP" not in healed

    def test_surrounding_user_prose_survives(self, scratch_at_pre: sa.Engine) -> None:
        """The substring heal must rewrite ONLY the brand text. A tenant's own
        added prose is left byte-identical -- the reason this migration replaces
        substrings instead of swapping a whole byte-exact generation."""
        tid = _insert_template(scratch_at_pre, name="orchestrator", user_instructions=LEGACY_ORCHESTRATOR_UI)

        assert _run_alembic("upgrade", _REV).returncode == 0

        healed = _fetch_user_instructions(scratch_at_pre, tid)
        assert _CUSTOM_LINE in healed
        assert healed.count(_CUSTOM_LINE) == 1

    def test_partial_generation_row_healed(self, scratch_at_pre: sa.Engine) -> None:
        """A row carrying the sentence but NOT the heading (a different seed
        generation) is still reached -- byte-exact matching would have missed it."""
        only_sentence = f"Some older preamble.\n\n{OLD_SENTENCE} - and the rest of the prose."
        tid = _insert_template(scratch_at_pre, name="orchestrator", user_instructions=only_sentence)

        assert _run_alembic("upgrade", _REV).returncode == 0

        healed = _fetch_user_instructions(scratch_at_pre, tid)
        assert NEW_SENTENCE in healed
        assert "Some older preamble." in healed
        assert "GiljoAI MCP" not in healed

    def test_row_without_brand_text_untouched(self, scratch_at_pre: sa.Engine) -> None:
        """A modern (or unrelated) row matches nothing and is left alone."""
        prose = "You are an implementation specialist responsible for production-grade code."
        tid = _insert_template(scratch_at_pre, name="implementer", user_instructions=prose)

        assert _run_alembic("upgrade", _REV).returncode == 0

        assert _fetch_user_instructions(scratch_at_pre, tid) == prose

    def test_rerun_is_idempotent(self, scratch_at_pre: sa.Engine) -> None:
        """Re-running ce_0090 (the CE installer's every-boot rerun) heals once,
        then no-ops -- it must not double-apply or crash."""
        tid = _insert_template(scratch_at_pre, name="orchestrator", user_instructions=LEGACY_ORCHESTRATOR_UI)

        assert _run_alembic("upgrade", _REV).returncode == 0
        assert _fetch_user_instructions(scratch_at_pre, tid) == HEALED_ORCHESTRATOR_UI

        assert _run_alembic("stamp", _PRE).returncode == 0
        reup = _run_alembic("upgrade", _REV)
        assert reup.returncode == 0, f"idempotent re-upgrade failed:\n{reup.stdout}\n{reup.stderr}"

        assert _fetch_user_instructions(scratch_at_pre, tid) == HEALED_ORCHESTRATOR_UI

    def test_downgrade_restores_previous_text(self, scratch_at_pre: sa.Engine) -> None:
        """The heal is reversible -- downgrade puts the legacy brand text back."""
        tid = _insert_template(scratch_at_pre, name="orchestrator", user_instructions=LEGACY_ORCHESTRATOR_UI)

        assert _run_alembic("upgrade", _REV).returncode == 0
        assert _fetch_user_instructions(scratch_at_pre, tid) == HEALED_ORCHESTRATOR_UI

        down = _run_alembic("downgrade", _PRE)
        assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"

        assert _fetch_user_instructions(scratch_at_pre, tid) == LEGACY_ORCHESTRATOR_UI
