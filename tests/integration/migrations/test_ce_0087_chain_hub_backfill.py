# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""``ce_0087``'s backfill links AT MOST ONE thread to a run (BE-9291).

The backfill recovers ``comm_threads.sequence_run_id`` from the old subject
convention. Its original guard, ``HAVING count(*) = 1``, bounds RUNS PER THREAD --
an ambiguous subject naming two runs is left NULL rather than guessed at. Nothing
bounded THREADS PER RUN: ``idx_comm_thread_sequence_run`` is a plain index rather
than a unique one, and the run-id validation on the write path checks that the run
EXISTS, not that it is unhubbed.

Two threads whose subjects both name the same run therefore both got stamped, and
both then landed in the FK branch of the resolver's CASE -- so the authoritative
branch stopped discriminating and the only tiebreak left was ``created_at ASC``.
Oldest wins, and the oldest thread mentioning a run id is not necessarily its hub.

What that costs, concretely: a conductor runs chain staging step 0, ``create_thread``
succeeds, and the conductor dies or is restaged before it records the thread id. It
re-runs step 0 and creates a SECOND hub which it hands to its sub-orchestrators.
Both get stamped. From then on the chain context answers every sub-orchestrator with
the FIRST, ABANDONED thread while the conductor polls the second -- split-brain
coordination, nothing raised, everyone quiet. That is the exact failure mode this
project exists to remove, and it needs no misbehaviour, only a retry.

The guard is symmetric with the one already there: a run claimed by more than one
candidate thread is SKIPPED rather than double-written. Skipping is not a loss --
resolution still finds those threads down the legacy subject branch, which is
precisely today's pre-``ce_0087`` behaviour. The migration declines to assert an
authoritative link it cannot determine.

Real database, real ``alembic upgrade`` -- these assertions are about what Postgres
actually did to seeded rows, not about what the SQL reads like.
"""

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

_PRE = "ce_0086_hub_identity_foundation"
_REV = "ce_0087_comm_threads_sequence_run_fk"

TK = "tk_ce0087"
TK_OTHER = "tk_ce0087_other"

# Realistic run ids. Every subject below is about whether one of these strings
# appears in it, so they are spelled once and never interpolated by accident.
RUN_SOLO = "0f7c1d2e-9a41-4b8e-8c33-5a6b7c8d9e01"
RUN_SHARED = "2b3c4d5e-6f70-4182-99aa-bbccddeeff01"
RUN_SECOND = "3c4d5e6f-7081-4293-aabb-ccddeeff0102"
RUN_CLAIMED = "4d5e6f70-8192-43a4-bbcc-ddeeff010203"
RUN_CROSS = "5e6f7081-92a3-44b5-ccdd-eeff01020304"


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
    """Fresh schema built up to ce_0086 -- the revision before the column exists."""
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    yield scratch_engine
    _drop_all_objects(scratch_engine)


# --------------------------------------------------------------------------- #
# Seeds -- raw SQL, because a migration test must not depend on the ORM models #
# --------------------------------------------------------------------------- #


def _seed_run(engine: sa.Engine, run_id: str, tenant: str = TK) -> None:
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO sequence_runs "
                "(id, tenant_key, project_ids, resolved_order, current_index, execution_mode, "
                " status, review_policy, project_statuses) "
                "VALUES (:id, :tk, '[]'::jsonb, '[]'::jsonb, 0, 'multi_terminal', 'running', "
                " 'per_card', '{}'::jsonb)"
            ),
            {"id": run_id, "tk": tenant},
        )
        conn.commit()


def _seed_thread(
    engine: sa.Engine,
    thread_id: str,
    serial: int,
    subject: str,
    *,
    tenant: str = TK,
    created: str = "2026-01-01T00:00:00+00:00",
) -> None:
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO comm_threads (id, tenant_key, serial, subject, status, created_at) "
                "VALUES (:id, :tk, :serial, :subject, 'open', :created)"
            ),
            {"id": thread_id, "tk": tenant, "serial": serial, "subject": subject, "created": created},
        )
        conn.commit()


def _link_of(engine: sa.Engine, thread_id: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT sequence_run_id FROM comm_threads WHERE id = :id"),
            {"id": thread_id},
        ).scalar()


def _runs_linked_more_than_once(engine: sa.Engine) -> list[tuple[str, int]]:
    """The invariant this whole file exists for, asked of the database directly."""
    with engine.connect() as conn:
        return [
            (row[0], row[1])
            for row in conn.execute(
                text(
                    "SELECT sequence_run_id, count(*) FROM comm_threads "
                    "WHERE sequence_run_id IS NOT NULL "
                    "GROUP BY sequence_run_id HAVING count(*) > 1"
                )
            ).all()
        ]


@pytest.mark.integration
class TestCe0087ChainHubBackfill:
    """One run, at most one link -- proven against a real upgrade."""

    def test_a_run_named_by_two_threads_is_skipped_rather_than_double_written(self, scratch_at_pre: sa.Engine) -> None:
        """THE regression. Both threads name the same run; neither may be stamped.

        Seeded exactly as the defect was measured: an OLDER thread that merely
        mentions the run and a NEWER thread that is the real hub. Before the guard
        both were stamped, and the resolver -- with both in the authoritative CASE
        branch and only ``created_at ASC`` left to decide -- answered with the older
        chatter thread.
        """
        _seed_run(scratch_at_pre, RUN_SHARED)
        _seed_thread(
            scratch_at_pre,
            "t_chatter_older",
            1,
            f"Random chatter mentioning {RUN_SHARED}",
            created="2026-01-01T00:00:00+00:00",
        )
        _seed_thread(
            scratch_at_pre,
            "t_real_hub_newer",
            2,
            f"Chain run {RUN_SHARED} coordination hub",
            created="2026-02-01T00:00:00+00:00",
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _runs_linked_more_than_once(scratch_at_pre) == [], (
            "the backfill linked one run to more than one thread — resolution's "
            "authoritative branch can no longer discriminate and oldest-wins decides"
        )
        assert _link_of(scratch_at_pre, "t_chatter_older") is None
        assert _link_of(scratch_at_pre, "t_real_hub_newer") is None

    def test_an_unambiguous_hub_is_still_backfilled(self, scratch_at_pre: sa.Engine) -> None:
        """The other side of the guard: it must not refuse the case it was built for.

        A guard that skipped everything would pass the test above and destroy the
        migration's entire purpose, so this is asserted in the same run.
        """
        _seed_run(scratch_at_pre, RUN_SOLO)
        _seed_thread(scratch_at_pre, "t_solo_hub", 1, f"Chain run {RUN_SOLO} coordination hub")

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _link_of(scratch_at_pre, "t_solo_hub") == RUN_SOLO

    def test_a_run_already_linked_does_not_gain_a_second_thread(self, scratch_at_pre: sa.Engine) -> None:
        """The idempotency-shaped variant of the same defect.

        The CE installer reruns the chain on every boot, so the backfill meets
        databases that already carry conductor-stamped links. A legacy thread naming
        an already-hubbed run must not become its second hub.
        """
        _seed_run(scratch_at_pre, RUN_CLAIMED)
        _seed_thread(scratch_at_pre, "t_existing_hub", 1, "Chain: ship the widget")
        _seed_thread(scratch_at_pre, "t_legacy_mention", 2, f"Chain run {RUN_CLAIMED} coordination hub")

        # Land the column/FK/index, then stamp the first thread the way a conductor
        # would, then force the backfill to run again against that state.
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"
        with scratch_at_pre.connect() as conn:
            conn.execute(
                text("UPDATE comm_threads SET sequence_run_id = :run WHERE id = 't_existing_hub'"),
                {"run": RUN_CLAIMED},
            )
            conn.execute(
                text("UPDATE comm_threads SET sequence_run_id = NULL WHERE id = 't_legacy_mention'"),
            )
            conn.execute(text("UPDATE alembic_version SET version_num = :pre"), {"pre": _PRE})
            conn.commit()

        again = _run_alembic("upgrade", _REV)
        assert again.returncode == 0, f"re-run of {_REV} failed:\n{again.stdout}\n{again.stderr}"

        assert _runs_linked_more_than_once(scratch_at_pre) == []
        assert _link_of(scratch_at_pre, "t_existing_hub") == RUN_CLAIMED
        assert _link_of(scratch_at_pre, "t_legacy_mention") is None

    def test_a_subject_naming_two_runs_is_still_left_null(self, scratch_at_pre: sa.Engine) -> None:
        """The original guard, unchanged. Runs-per-thread stays bounded too."""
        _seed_run(scratch_at_pre, RUN_SHARED)
        _seed_run(scratch_at_pre, RUN_SECOND)
        _seed_thread(
            scratch_at_pre,
            "t_ambiguous",
            1,
            f"Chain runs {RUN_SHARED} and {RUN_SECOND} coordination hub",
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _link_of(scratch_at_pre, "t_ambiguous") is None

    def test_another_tenants_thread_is_never_linked(self, scratch_at_pre: sa.Engine) -> None:
        """Tenant scoping on the backfill join, re-asserted around the new guard.

        The guard only ever PREVENTS a write, so it cannot widen this — but the
        join it wraps is the one that keeps a globally-unique run id from reaching
        across tenants, and that stays pinned.
        """
        _seed_run(scratch_at_pre, RUN_CROSS, tenant=TK)
        _seed_thread(
            scratch_at_pre,
            "t_other_tenant",
            1,
            f"Chain run {RUN_CROSS} coordination hub",
            tenant=TK_OTHER,
        )

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        assert _link_of(scratch_at_pre, "t_other_tenant") is None
