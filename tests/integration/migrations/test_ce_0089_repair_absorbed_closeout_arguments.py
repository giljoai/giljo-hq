# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""``ce_0089`` recovers closeout arguments absorbed into ``summary`` (BE-9348).

BE-9348 fixes the write path at the MCP dispatch seam. This migration repairs the rows
that path already produced: a closeout whose OPTIONAL argument was swallowed by the
caller's tool-call serialization stored the raw markup inside ``summary`` and left the
real column empty.

What is asserted here is the part that is easy to get wrong and impossible to see by
reading the SQL:

* the empty-column guard is ``NULL OR '[]'``, not ``IS NULL`` -- every real damaged row
  stores ``[]``, so a NULL-only guard would repair NOTHING while reporting success;
* a row that merely MENTIONS a marker in prose is left byte-for-byte alone -- the
  closeout written for BE-9348 itself is exactly that shape, and truncating it would be
  the migration reproducing the defect it exists to repair;
* a populated target column is never overwritten, and such a row's summary is not
  cleaned either, because a disagreeing residue means the row was not fully recoverable;
* a replay moves nothing.

Real database, real ``alembic upgrade`` -- these assertions are about what Postgres did
to seeded rows, not about what the SQL reads like. Mirrors
``test_ce_0088_completed_at_backfill.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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

_PRE = "ce_0088_backfill_project_completed_at"
_REV = "ce_0089_be9348_repair_absorbed_closeout_arguments"

TK = "tk_ce0089"
PRODUCT_ID = "ce008900-0000-4000-8000-000000000001"  # id columns are varchar(36)

# ---------------------------------------------------------------------------
# The three residue shapes, transcribed from real damaged 360 memory rows.
# ---------------------------------------------------------------------------
PROSE_A = "Swept the remaining operator docs and repaired every pointer."
SHAPE_TAGS_PARAMETER = PROSE_A + '</summary>\n<parameter name="tags">["docs", "chore", "infrastructure"]'

PROSE_B = "Chain cold-start hardening landed and the live deadlock is gone."
SHAPE_TAGS_OLD_STYLE = PROSE_B + '</summary>\n<tags>["backend", "frontend", "bug-fix", "test"]'

PROSE_C = "Built the pane, bound it to the API, and shipped the drag-reorder rail."
SHAPE_GIT_COMMITS = (
    PROSE_C + '</summary>\n<parameter name="git_commits">[{"sha": "7dafbb675", "message": "feat: pane"}]'
)

# The self-protection case: BE-9348's own closeout discusses these markers in prose and
# therefore MATCHES the existence guard. It must survive byte-for-byte.
SELF_REFERENTIAL_SUMMARY = (
    "A caller's serializer merged one argument into its neighbour, so a summary could end "
    "with </summary> followed by a serialized array while the real column stayed empty. "
    "The server now refuses that call at the dispatch seam and names the absorbed argument."
)

# Residue-looking but unparseable: a recoverable tag whose payload is not valid JSON.
UNPARSEABLE_SUMMARY = "Closed the lane." + '</summary>\n<tags>["backend", "frontend"'

# Residue present, but the target column already carries data that disagrees with it.
OCCUPIED_SUMMARY = "Shipped the limiter." + '</summary>\n<parameter name="tags">["backend"]'

UNDAMAGED_SUMMARY = "An ordinary closeout with no residue at all."

# The audit's must-fix: a LEGITIMATE closeout that quotes the residue verbatim at the
# very end, with an empty tags column. Byte-identical to real damage -- no gate can tell
# them apart. Its prose must survive; gaining tags is the accepted, logged trade.
QUOTES_RESIDUE_SUMMARY = (
    'The damaged shape is: ...filed as INF-9293.</summary>\n<parameter name="tags">["docs", "chore"]'
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


def _seed_product(conn) -> None:
    conn.execute(
        text(
            "INSERT INTO products (id, name, description, tenant_key, is_active, product_memory) "
            "VALUES (:id, 'CE0089 Product', 'BE-9348 repair', :tk, true, CAST('{}' AS JSONB)) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": PRODUCT_ID, "tk": TK},
    )


def _seed_entry(conn, *, seq: int, summary: str, tags: list | None, git_commits: list | None) -> str:
    entry_id = f"ce008900-0000-4000-8000-0000000{seq:05d}"
    conn.execute(
        text(
            "INSERT INTO product_memory_entries "
            "  (id, tenant_key, product_id, sequence, entry_type, source, timestamp, "
            "   project_name, summary, tags, git_commits) "
            "VALUES (CAST(:id AS uuid), :tk, :pid, :seq, 'project_closeout', 'closeout_v1', NOW(), "
            "   'CE0089', :summary, CAST(:tags AS JSONB), CAST(:commits AS JSONB))"
        ),
        {
            "id": entry_id,
            "tk": TK,
            "pid": PRODUCT_ID,
            "seq": seq,
            "summary": summary,
            "tags": json.dumps(tags if tags is not None else []),
            "commits": json.dumps(git_commits if git_commits is not None else []),
        },
    )
    return entry_id


def _read(conn, entry_id: str):
    return (
        conn.execute(
            text("SELECT summary, tags, git_commits FROM product_memory_entries WHERE id = CAST(:id AS uuid)"),
            {"id": entry_id},
        )
        .mappings()
        .one()
    )


@pytest.fixture
def seeded_at_pre(scratch_engine: sa.Engine):
    """Fresh schema built up to ce_0088 -- the revision before the repair runs -- with
    every residue shape plus the rows that must NOT be touched."""
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"

    ids: dict[str, str] = {}
    with scratch_engine.connect() as conn:
        _seed_product(conn)
        ids["tags_parameter"] = _seed_entry(conn, seq=1, summary=SHAPE_TAGS_PARAMETER, tags=[], git_commits=[])
        ids["tags_old_style"] = _seed_entry(conn, seq=2, summary=SHAPE_TAGS_OLD_STYLE, tags=[], git_commits=[])
        ids["git_commits"] = _seed_entry(conn, seq=3, summary=SHAPE_GIT_COMMITS, tags=["feature"], git_commits=[])
        ids["self_referential"] = _seed_entry(
            conn, seq=4, summary=SELF_REFERENTIAL_SUMMARY, tags=["bug-fix"], git_commits=[]
        )
        ids["unparseable"] = _seed_entry(conn, seq=5, summary=UNPARSEABLE_SUMMARY, tags=[], git_commits=[])
        ids["occupied"] = _seed_entry(conn, seq=6, summary=OCCUPIED_SUMMARY, tags=["security"], git_commits=[])
        ids["undamaged"] = _seed_entry(conn, seq=7, summary=UNDAMAGED_SUMMARY, tags=["chore"], git_commits=[])
        ids["quotes_residue_empty_tags"] = _seed_entry(
            conn, seq=8, summary=QUOTES_RESIDUE_SUMMARY, tags=[], git_commits=[]
        )
        conn.commit()

    return scratch_engine, ids


class TestCe0089RepairsAbsorbedArguments:
    def test_tags_absorbed_via_parameter_tag_are_recovered(self, seeded_at_pre) -> None:
        engine, ids = seeded_at_pre
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade to {_REV} failed:\n{up.stdout}\n{up.stderr}"

        with engine.connect() as conn:
            row = _read(conn, ids["tags_parameter"])
        assert row["tags"] == ["docs", "chore", "infrastructure"], "the absorbed tags were not restored"
        assert row["summary"] == SHAPE_TAGS_PARAMETER, (
            "summary was rewritten -- this migration recovers columns ONLY. The residue is "
            "byte-identical to a legitimate closeout quoting it, and it is the audit trail "
            f"for a damage set we cannot bound. Got: {row['summary']!r}"
        )

    def test_tags_absorbed_via_old_style_tag_are_recovered(self, seeded_at_pre) -> None:
        engine, ids = seeded_at_pre
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

        with engine.connect() as conn:
            row = _read(conn, ids["tags_old_style"])
        assert row["tags"] == ["backend", "frontend", "bug-fix", "test"]
        assert row["summary"] == SHAPE_TAGS_OLD_STYLE, "summary must never be rewritten"

    def test_absorbed_git_commits_are_recovered(self, seeded_at_pre) -> None:
        engine, ids = seeded_at_pre
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

        with engine.connect() as conn:
            row = _read(conn, ids["git_commits"])
        assert row["git_commits"] == [{"sha": "7dafbb675", "message": "feat: pane"}]
        assert row["summary"] == SHAPE_GIT_COMMITS, "summary must never be rewritten"
        assert row["tags"] == ["feature"], "a populated sibling column must not be disturbed"


class TestCe0089LeavesEverythingElseAlone:
    def test_prose_that_merely_mentions_the_marker_is_byte_identical(self, seeded_at_pre) -> None:
        """The load-bearing safety case. BE-9348's own closeout has this shape, so it
        MATCHES the existence guard -- the narrowing gate is the only thing between it
        and truncation. Byte-for-byte, not 'still present'."""
        engine, ids = seeded_at_pre
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

        with engine.connect() as conn:
            row = _read(conn, ids["self_referential"])
        assert row["summary"] == SELF_REFERENTIAL_SUMMARY, (
            "a summary that merely DISCUSSES the residue markers was altered -- the migration "
            "reproduced the very defect it exists to repair"
        )
        assert row["tags"] == ["bug-fix"]

    def test_a_legitimate_closeout_quoting_the_residue_keeps_its_summary(self, seeded_at_pre) -> None:
        """The audit's must-fix case, pinned.

        A closeout that quotes the residue VERBATIM at the very end, whose own ``tags``
        column happens to be empty, is byte-identical to a genuinely damaged row. No
        gate can separate them -- the information is not in the row. An earlier draft
        truncated this summary and fabricated tags for it.

        The summary must now survive byte-for-byte. The row still gains tags it should
        not have, which is the stated, accepted limitation: additive, hand-reversible,
        and logged with its pre-state. What is NOT acceptable is destroying the prose.
        """
        engine, ids = seeded_at_pre
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

        with engine.connect() as conn:
            row = _read(conn, ids["quotes_residue_empty_tags"])
        assert row["summary"] == QUOTES_RESIDUE_SUMMARY, (
            "a legitimate closeout that quotes the residue was TRUNCATED -- the migration "
            f"destroyed prose it could not prove was damage. Got: {row['summary']!r}"
        )

    def test_an_unparseable_residue_leaves_the_summary_untouched(self, seeded_at_pre) -> None:
        engine, ids = seeded_at_pre
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

        with engine.connect() as conn:
            row = _read(conn, ids["unparseable"])
        assert row["summary"] == UNPARSEABLE_SUMMARY, "a row that could not be fully recovered was rewritten"
        assert row["tags"] == []

    def test_a_populated_target_column_is_never_overwritten(self, seeded_at_pre) -> None:
        engine, ids = seeded_at_pre
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

        with engine.connect() as conn:
            row = _read(conn, ids["occupied"])
        assert row["tags"] == ["security"], "existing good data was overwritten by the residue"
        assert row["summary"] == OCCUPIED_SUMMARY, (
            "the summary of a row that was not fully recoverable was cleaned anyway, "
            "discarding the residue it disagreed with"
        )

    def test_an_undamaged_row_is_untouched(self, seeded_at_pre) -> None:
        engine, ids = seeded_at_pre
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

        with engine.connect() as conn:
            row = _read(conn, ids["undamaged"])
        assert row["summary"] == UNDAMAGED_SUMMARY
        assert row["tags"] == ["chore"]


class TestCe0089Idempotency:
    def test_a_replay_of_the_revision_moves_nothing(self, seeded_at_pre) -> None:
        """Re-running must be a clean no-op: repaired rows no longer match the guard,
        and skipped rows are skipped identically. The CE installer re-runs this on
        every boot."""
        engine, ids = seeded_at_pre
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

        with engine.connect() as conn:
            after_first = {key: dict(_read(conn, entry_id)) for key, entry_id in ids.items()}

        down = _run_alembic("downgrade", _PRE)
        assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"
        again = _run_alembic("upgrade", _REV)
        assert again.returncode == 0, f"re-upgrade failed:\n{again.stdout}\n{again.stderr}"

        with engine.connect() as conn:
            after_second = {key: dict(_read(conn, entry_id)) for key, entry_id in ids.items()}

        assert after_second == after_first, "a replay of the revision changed rows it had already settled"
