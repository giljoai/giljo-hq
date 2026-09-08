# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
PostgreSQL Test Database Helper

Provides utilities for managing PostgreSQL test databases with proper isolation.
Each test gets a clean database state through transaction rollback.

CRITICAL SAFETY: This module includes guards to prevent accidental production database access.
"""

import asyncio
import contextlib
import functools
import hashlib
import logging
import os
import re
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import Base


logger = logging.getLogger(__name__)


# =============================================================================
# PRODUCTION DATABASE SAFETY GUARD
# =============================================================================
# CRITICAL: These checks prevent tests from ever connecting to production.
# DO NOT REMOVE OR BYPASS THESE CHECKS.

PRODUCTION_DB_NAME = "giljo_mcp"
TEST_DB_SUFFIX = "_test"
ALLOWED_TEST_DBS = {
    "giljo_mcp_test",
    "giljo_test",
    "postgres",
}  # postgres needed for admin operations, giljo_test for CI

# Per-worker test databases under pytest-xdist are named giljo_mcp_test_gw0,
# giljo_mcp_test_gw1, ... locally and giljo_test_gw0, giljo_test_gw1, ... in CI
# (one DB per worker so parallel workers can never create/drop schema out from
# under each other).
#
# PARALLEL-CLONE ISOLATION: a NUMBERED suffix on the base (giljo_mcp_test2,
# giljo_mcp_test3, ...) lets simultaneous dev CLONES on the same Postgres run
# pytest at once without their per-worker DBs colliding (clone CI2 uses
# giljo_mcp_test2 -> giljo_mcp_test2_gwN, CI3 uses giljo_mcp_test3, ...). The
# ``\d*`` below accepts those numbered bases + their per-worker variants.
#
# This pattern is the ONLY widening of the safety allowlist: it accepts the two
# canonical test DB base names, their numbered clone variants, and their _gwN
# per-worker suffix — and NOTHING else. Production names such as ``giljo_mcp``
# (no ``_test``) and ``giljo_mcp_saas`` still hard-fail validation below.
WORKER_TEST_DB_PATTERN = re.compile(r"^(giljo_mcp_test\d*|giljo_test\d*)(_gw\d+)?$")

# Cross-process serialization key for CREATE DATABASE. Under xdist all workers
# copy ``template1`` to create their per-worker DB at nearly the same instant;
# concurrent copies fail with "source database template1 is being accessed by
# other users". A session-level pg_advisory_lock on the shared admin connection
# serializes just the create step (a brief one-time cost) and removes the race.
#
# THE ONE KEY (TSK-9381). ``template1`` is a single shared resource, so every
# CREATE DATABASE anywhere in the suite must take the SAME lock or the lock buys
# nothing. This was previously two keys: the migration scratch-DB bootstrap used
# 7281643 while intending — per its own comment, "same serialization key family
# as the main test-DB bootstrap" — to exclude against this one. Two keys exclude
# nothing, so the two paths could copy template1 simultaneously. Use
# ``create_database_lock`` / ``create_database_lock_async`` below rather than
# hand-rolling the pair of statements; a new create site that invents its own key
# reopens the same hole, and ``test_tsk9381_one_create_database_lock.py`` fails if
# one appears.
DB_CREATE_LOCK_KEY = 7281642

# Test engines use SQLAlchemy NullPool (DatabaseManager(use_null_pool=True)) so
# no idle connections are retained between checkouts. Under pytest-xdist many
# worker processes each open an engine; a retained per-engine pool would exhaust
# PostgreSQL ``max_connections``. NullPool keeps aggregate usage bounded.


# =============================================================================
# MIGRATION-CHAIN FINGERPRINT (INF-9534)
# =============================================================================
# BE-9525b dropped ``idx_project_single_active_per_product`` in a migration.
# Per-worker test databases are bootstrapped by ``Base.metadata.create_all``
# (BE-3002a), never by running Alembic against them -- so the guard that
# already existed (BE-9288's ``_missing_columns``, a column-level diff against
# ``Base.metadata``) could not see this class of drift at all: the dropped
# index was never part of ``Base.metadata`` to begin with, only ever created
# by raw SQL inside the migration. Per-worker databases could still carry it
# after the migration merged, so a test asserting the new behaviour ran
# against a schema that still physically forbade it -- indistinguishable from
# xdist flakiness, because nothing said the database itself was stale.
#
# The fix generalizes past this one index: fingerprint the WHOLE migration
# chain (every file under ``migrations/versions/`` and
# ``migrations/saas_versions/``, by content, not filename) and stamp that
# fingerprint into each per-worker database. A mismatch on bootstrap means
# the chain moved since this database was last built and its schema is reset
# alongside the existing BE-9288 response -- ``create_all`` then rebuilds it
# against whatever ``Base.metadata`` says *now*. Content (not just revision
# ids) is hashed deliberately: ``migrations/README.md``'s baseline-parity
# carve-out lets an already-shipped baseline file be edited in place without
# a new revision id, and a heads-only fingerprint would miss exactly that
# edit. ``migrations/archive/`` is excluded -- it is frozen history, not part
# of the live chain any test database is ever built against.
# Deliberately NOT in ``public``: BE-9288's guard (``_missing_columns``) scans
# ``information_schema.columns WHERE table_schema = 'public'``, and its own
# regression test asserts ``public`` holds exactly zero tables right after a
# drift reset. A marker table living in ``public`` would satisfy neither --
# it would show up as an "extra table" in every column diff and break that
# reset assertion's table count. A private schema keeps it wholly outside
# both, and survives the ``DROP SCHEMA public CASCADE`` reset unscathed (the
# marker is re-stamped unconditionally afterward anyway, so nothing depends
# on that survival -- it's a side benefit, not a requirement).
SCHEMA_FINGERPRINT_SCHEMA = "giljo_test_meta"
SCHEMA_FINGERPRINT_TABLE = f'"{SCHEMA_FINGERPRINT_SCHEMA}"."_giljo_test_schema_fingerprint"'

# Roles the shipped app connects as in a real (non-test) install (see
# ``installer/core/database.py``). Neither is guaranteed to exist on a given
# Postgres cluster, so every grant below is applied per-role and skipped, not
# failed, when the role is absent.
APP_ROLES = ("giljo_owner", "giljo_user")


def _migration_chain_paths() -> list[Path]:
    """Every file in the LIVE migration chain, in a stable order.

    Repo root is three parents up from ``tests/helpers/test_db_helper.py``.
    Deliberately excludes ``migrations/archive/`` and ``migrations/manual/``
    -- neither is part of the chain any database (test or real) is built
    against today.
    """
    root = Path(__file__).resolve().parents[2] / "migrations"
    return sorted((root / "versions").glob("*.py")) + sorted((root / "saas_versions").glob("*.py"))


@functools.lru_cache(maxsize=1)
def compute_schema_fingerprint() -> str:
    """Hash of the full migration chain's file names + contents.

    Cached per-process: the chain cannot change mid-run, and under xdist each
    worker is its own process, so a per-process cache neither hides a change
    within one run nor leaks across runs.
    """
    digest = hashlib.sha256()
    for path in _migration_chain_paths():
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


@contextlib.contextmanager
def create_database_lock(conn):
    """Hold :data:`DB_CREATE_LOCK_KEY` for a sync ``CREATE DATABASE`` (TSK-9381).

    ``conn`` must be an AUTOCOMMIT connection to a maintenance database and must
    stay open for the whole block: ``pg_advisory_lock`` is SESSION-scoped, so the
    lock lives on this connection, not on a transaction.

    Wrap the existence check as well as the CREATE. Checking outside the lock is
    a classic check-then-act race — two workers both read "absent" and both
    proceed to copy ``template1``.
    """
    conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": DB_CREATE_LOCK_KEY})
    try:
        yield conn
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": DB_CREATE_LOCK_KEY})


@contextlib.asynccontextmanager
async def create_database_lock_async(conn):
    """Async twin of :func:`create_database_lock`. Same key, same contract."""
    await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": DB_CREATE_LOCK_KEY})
    try:
        yield conn
    finally:
        await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": DB_CREATE_LOCK_KEY})


def worker_suffix() -> str:
    """Return ``_gwN`` for the current pytest-xdist worker, or "" if not parallel.

    xdist names its workers ``gw0``, ``gw1``, ...; the controller process and
    plain (non-xdist) runs leave ``PYTEST_XDIST_WORKER`` unset, which yields the
    bare (shared) name — identical to pre-change behaviour. Shared with the
    migration tests so their scratch DB is also per-worker isolated.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    if worker.startswith("gw") and worker[2:].isdigit():
        return f"_{worker}"
    return ""


# Back-compat private alias (internal callers).
_worker_suffix = worker_suffix


def validate_database_name(database: str) -> None:
    """
    Validate that a database name is a recognized TEST database.

    This is a CRITICAL production-safety guard. A name is accepted ONLY if it is
    in ``ALLOWED_TEST_DBS`` (``giljo_mcp_test``, ``giljo_test``, ``postgres``) or
    matches the per-worker pattern ``giljo_mcp_test_gwN`` / ``giljo_test_gwN``.
    Every other name — including the production databases ``giljo_mcp`` and
    ``giljo_mcp_saas`` — is rejected. This is strictly tighter than a denylist:
    anything not explicitly recognized as a test database is refused.

    Args:
        database: Database name to validate

    Raises:
        RuntimeError: If the name is not a recognized test database
    """
    if database in ALLOWED_TEST_DBS:
        return
    if WORKER_TEST_DB_PATTERN.match(database):
        return
    raise RuntimeError(
        f"SAFETY GUARD TRIGGERED: '{database}' is not a recognized test database!\n"
        f"Tests may ONLY use '{PRODUCTION_DB_NAME}{TEST_DB_SUFFIX}' (optionally with a "
        f"'_gwN' per-worker suffix), 'giljo_test', or 'postgres'.\n"
        f"Refusing to connect — this guard prevents accidental access to production "
        f"databases such as '{PRODUCTION_DB_NAME}' or '{PRODUCTION_DB_NAME}_saas'."
    )


def validate_connection_string(url: str) -> None:
    """
    Validate that a connection string targets a test database.

    RAISES RuntimeError if connection string targets production.

    Args:
        url: Database connection URL

    Raises:
        RuntimeError: If URL targets production database
    """
    # Extract database name from URL patterns like:
    # postgresql://user:pass@host:port/dbname
    # postgresql+asyncpg://user:pass@host:port/dbname
    match = re.search(r"/([^/?]+)(?:\?|$)", url)
    if match:
        db_name = match.group(1)
        validate_database_name(db_name)


class PostgreSQLTestHelper:
    """
    Helper for managing PostgreSQL test databases.

    Features:
    - Transaction-based test isolation (rollback after each test)
    - Automatic database creation/cleanup
    - Schema-based isolation for parallel tests when needed
    - Performance optimized for test suites
    """

    # Default test database configuration (local dev).
    # CI overrides via DATABASE_URL env var.
    # Local dev reads password from POSTGRES_SUPERUSER_PASSWORD env var
    # (set in .env — distinct from DB_PASSWORD which is the app's giljo_user password).
    DEFAULT_CONFIG = {
        "host": "localhost",
        "port": 5432,
        "database": "giljo_mcp_test",
        "username": "postgres",
        "password": os.environ.get("POSTGRES_SUPERUSER_PASSWORD", ""),
    }

    @staticmethod
    def _config_from_env() -> dict | None:
        """Parse DATABASE_URL env var into config dict if set."""
        import os

        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return None
        # Parse: postgresql://user:pass@host:port/dbname
        match = re.match(
            r"postgresql(?:\+\w+)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+?)(?:\?|$)",
            db_url,
        )
        if not match:
            return None
        return {
            "username": match.group(1),
            "password": match.group(2),
            "host": match.group(3),
            "port": int(match.group(4)),
            "database": match.group(5),
        }

    @staticmethod
    def resolve_test_db_name() -> str:
        """
        Resolve the test database name for THIS process.

        Under pytest-xdist each worker gets its own database — ``giljo_mcp_test_gw0``,
        ``giljo_mcp_test_gw1``, ... locally and ``giljo_test_gw0``, ``giljo_test_gw1``,
        ... in CI (base name supplied via DATABASE_URL) — so parallel workers never
        mutate one another's schema. The suffix is applied to any recognized test DB
        base name, INCLUDING the numbered parallel-clone bases the module comment
        above documents (``giljo_mcp_test2`` -> ``giljo_mcp_test2_gwN``; BE-9373 —
        the suffix condition previously matched only the two canonical bases, so a
        clone that set a numbered base got ONE shared DB for all xdist workers and
        every clone in practice fell back to the default base, colliding with
        sibling clones' runs). ``_worker_suffix()`` returns "" off-xdist, so serial
        callers (the CI integration / test-saas steps, plain local runs) keep their
        bare base name unchanged.
        """
        env_config = PostgreSQLTestHelper._config_from_env()
        base = env_config["database"] if env_config else PostgreSQLTestHelper.DEFAULT_CONFIG["database"]
        if re.fullmatch(r"giljo_mcp_test\d*|giljo_test\d*", base):
            base = f"{base}{_worker_suffix()}"
        return base

    @staticmethod
    def get_test_db_url(database: str | None = None, async_driver: bool = True) -> str:
        """
        Build PostgreSQL test database URL.

        Uses DATABASE_URL env var if set (CI), otherwise falls back to
        DEFAULT_CONFIG (local development). When ``database`` is omitted the
        per-worker name from :meth:`resolve_test_db_name` is used.

        SAFETY: Validates database name to prevent production access.

        Args:
            database: Database name. Defaults to the per-worker test DB.
            async_driver: Use async driver (asyncpg) vs sync (psycopg2)

        Returns:
            PostgreSQL connection URL

        Raises:
            RuntimeError: If database name is not a recognized test database
        """
        if database is None:
            database = PostgreSQLTestHelper.resolve_test_db_name()

        # CRITICAL SAFETY CHECK - prevent production database access
        validate_database_name(database)

        # Use DATABASE_URL env var if available (CI), else local defaults
        env_config = PostgreSQLTestHelper._config_from_env()
        config = env_config if env_config else PostgreSQLTestHelper.DEFAULT_CONFIG.copy()
        config["database"] = database

        return (
            (
                f"postgresql+asyncpg://{config['username']}:{config['password']}"
                f"@{config['host']}:{config['port']}/{config['database']}"
            )
            if async_driver
            else (
                f"postgresql://{config['username']}:{config['password']}"
                f"@{config['host']}:{config['port']}/{config['database']}"
            )
        )

    @staticmethod
    async def _missing_columns(target_db: str) -> dict[str, list[str]]:
        """Diff ``target_db``'s live ``public`` schema against ``Base.metadata``.

        Narrow by design (BE-9288) -- flags ONLY "a table that EXISTS in the DB
        is missing a column ``Base.metadata`` declares for it". Everything else
        is deliberately left alone (these are the documented false-positive
        sources, each asserted by the BE-9288 regression tests):
          - a table in ``Base.metadata`` absent from the DB entirely (normal
            CE-vs-SaaS split -- see memory
            ``feedback_local_createall_schema_differs_from_ce``)
          - a table in the DB that ``Base.metadata`` doesn't know about
            (alembic bookkeeping, leftover SaaS tables on a reused DB name)
          - extra columns the DB has that the model no longer declares
          - JSONB internals, type mismatches, nullability, defaults

        Returns ``{table_name: [missing_column, ...]}``; empty dict = no drift.
        """
        db_url = PostgreSQLTestHelper.get_test_db_url(database=target_db)
        engine = create_async_engine(db_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")
                )
                live_columns: dict[str, set[str]] = {}
                for table_name, column_name in rows:
                    live_columns.setdefault(table_name, set()).add(column_name)
        finally:
            await engine.dispose()

        drift: dict[str, list[str]] = {}
        for table_name, table in Base.metadata.tables.items():
            if table_name not in live_columns:
                continue  # table absent from the DB -- not drift, see docstring
            missing = [c.name for c in table.columns if c.name not in live_columns[table_name]]
            if missing:
                drift[table_name] = missing
        return drift

    @staticmethod
    async def _schema_fingerprint_is_stale(target_db: str, expected: str) -> bool:
        """True when ``target_db``'s stamped migration-chain fingerprint disagrees
        with ``expected`` (INF-9534), including when it has never been stamped at
        all -- a database bootstrapped before this guard existed, or one whose
        marker table was dropped by an out-of-band reset. Either way, "unknown"
        is treated as stale rather than trusted: the whole point is that a
        database must prove it is current, not be assumed so.

        Read-only and on its own engine, mirroring ``_missing_columns`` -- called
        BEFORE the create-database lock (INF-9406: no I/O on another connection
        may happen while that cluster-scoped lock is held).
        """
        db_url = PostgreSQLTestHelper.get_test_db_url(database=target_db)
        engine = create_async_engine(db_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                has_marker = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).has_table(
                        "_giljo_test_schema_fingerprint", schema=SCHEMA_FINGERPRINT_SCHEMA
                    )
                )
                if not has_marker:
                    return True
                row = (await conn.execute(text(f"SELECT fingerprint FROM {SCHEMA_FINGERPRINT_TABLE} LIMIT 1"))).first()
                return row is None or row[0] != expected
        finally:
            await engine.dispose()

    @staticmethod
    async def _stamp_schema_fingerprint(conn, fingerprint: str) -> None:
        """(Re)write the single-row fingerprint marker on ``conn``'s database.

        Runs unconditionally (not only on drift) so a database that was already
        current still ends the bootstrap with a marker -- the self-heal path for
        every per-worker database that predates this guard, without needing a
        reset. Idempotent: safe to call every bootstrap, drifted or not.
        """
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_FINGERPRINT_SCHEMA}"'))
        await conn.execute(text(f"CREATE TABLE IF NOT EXISTS {SCHEMA_FINGERPRINT_TABLE} (fingerprint text NOT NULL)"))
        await conn.execute(text(f"TRUNCATE {SCHEMA_FINGERPRINT_TABLE}"))
        await conn.execute(
            text(f"INSERT INTO {SCHEMA_FINGERPRINT_TABLE} (fingerprint) VALUES (:fp)"),
            {"fp": fingerprint},
        )

    @staticmethod
    async def _ensure_app_role_grants(conn, target_db: str) -> None:
        """Grant the app roles what they need on ``target_db``, and CREATEDB at
        the role level, every time a per-worker database is (re)provisioned
        (INF-9534, second gap).

        A lane that pins ``DATABASE_URL`` to connect as ``giljo_owner`` or
        ``giljo_user`` instead of the ``postgres`` superuser found the per-worker
        database granted DML to neither role (``DEFAULT_CONFIG`` connects as
        ``postgres``, and nothing had ever granted the app roles anything on a
        test database), and found neither role able to create the throwaway
        scratch databases several suites need (schema-drift guard, pg-parity,
        SaaS purge, schema-writer bootstrap all require CREATEDB). Neither was
        mechanised, so a database created later inherited nothing. This makes
        every (re)provision self-sufficient.

        Runs unconditionally, mirroring ``_stamp_schema_fingerprint`` -- cheap
        metadata-only statements, and running them every bootstrap self-heals
        every already-existing per-worker database too, not only ones created
        after this change ships.

        Per-role and best-effort: a role absent from this cluster (see
        ``APP_ROLES``) is skipped rather than failing the whole bootstrap, and
        a permission error on the
        CREATEDB grant (connecting role lacks CREATEROLE) is logged and
        swallowed rather than taking down test collection over a step that
        is not the point of this function.
        """
        for role in APP_ROLES:
            role_exists = bool(
                (await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})).scalar()
            )
            if not role_exists:
                continue
            await conn.execute(text(f'GRANT CONNECT ON DATABASE "{target_db}" TO "{role}"'))
            await conn.execute(text(f'GRANT ALL ON SCHEMA public TO "{role}"'))
            await conn.execute(text(f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "{role}"'))
            await conn.execute(text(f'GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))
            await conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{role}"'))
            await conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{role}"'))
            try:
                await conn.execute(text(f'ALTER ROLE "{role}" WITH CREATEDB'))
            except Exception:
                logger.warning(
                    "INF-9534: could not grant CREATEDB to role %r on %r "
                    "(connecting role likely lacks CREATEROLE) -- DML grants were still applied.",
                    role,
                    target_db,
                )

    @staticmethod
    async def ensure_test_database_exists():
        """
        Ensure the (per-worker) test database exists, create if it doesn't.

        Connects to the default 'postgres' database to create the test database
        if needed, then ensures the ``pg_trgm`` extension is present (used by
        fuzzy context search via ``similarity()``; on a shared dev DB this is
        created at install time, but a fresh per-worker DB starts empty).

        SCHEMA-DRIFT GUARD (BE-9288): a per-worker DB left over from an earlier
        run silently keeps its OLD schema -- ``Base.metadata.create_all()``
        (called by ``create_test_tables`` at worker bootstrap) only creates
        tables that don't exist yet; it never adds a column to a table that's
        already there. So a model column added since the DB was last created
        stays missing, and tests fail far from the real cause. If the DB
        already exists, its live columns are diffed against ``Base.metadata``
        (``_missing_columns``, narrow by design) and, on drift, its ``public``
        schema is reset so the bootstrap ``create_all`` starts clean.

        MIGRATION-CHAIN FINGERPRINT (INF-9534): ``_missing_columns`` only sees a
        table that exists losing a column -- it cannot see an index, constraint,
        or enum value the migration chain dropped or added, because none of
        those necessarily change ``Base.metadata`` (a raw-SQL migration index is
        the case that exposed this: a dropped index that per-worker databases
        still silently carried, indistinguishable from xdist flakiness).
        ``_schema_fingerprint_is_stale`` closes
        that gap by hashing the WHOLE migration chain and stamping the result
        into each per-worker database; a mismatch (including "never stamped")
        also triggers the reset below, and the fingerprint is re-stamped on
        every bootstrap regardless of drift. The app-role grants and CREATEDB
        (``_ensure_app_role_grants``, the second INF-9534 gap) are applied the
        same unconditional way, right after.

        Resetting (rather than failing loudly) is the chosen response because it
        IS race-safe here: the target DB name is per-worker-unique
        (``resolve_test_db_name``), so no sibling xdist worker ever targets this
        same name and nothing else can observe the reset. It is scoped to the
        schema rather than the database because that is the scope of the
        guarantee: ``_missing_columns`` diffs ``public``, and BE-9288 asserts
        ``public`` is empty afterwards. ``CASCADE`` also takes enum types and
        sequences, so ``create_all`` starts genuinely clean.

        NEVER GO IDLE WHILE HOLDING THE LOCK (INF-9406). ``DB_CREATE_LOCK_KEY``
        is a PostgreSQL advisory lock, which is CLUSTER-scoped: every xdist
        worker AND every concurrent clone on the same server queues on the one
        key, however disjoint their database names are. This function used to
        hold it across two operations issued on OTHER connections -- the
        ``_missing_columns`` diff and ``drop_test_database()``, each of which
        builds its own engine -- so the lock-holding connection sat ``idle`` for
        as long as those took. Measured: a holder idle 27s on the existence
        check while two sessions waited 24s on ``pg_advisory_lock``, which took
        the BE-9288 guard test's own body to 33.1s (29.1s of it purely waiting
        to acquire) against the 30s ``--timeout`` in pyproject.toml -- and
        ``--timeout-method=thread`` kills by ``os._exit(1)``, so that landed as
        a dead xdist worker and a red suite rather than as a slow test.

        Removing the idle hold was necessary and NOT sufficient, and the reason
        is the second half of INF-9406. The drift response still held the lock
        across a ``DROP DATABASE`` -- and ``DROP DATABASE`` forces a
        CLUSTER-WIDE immediate checkpoint and waits for it, so its duration is
        set by every OTHER worker's dirty buffers. Measured during a concurrent
        two-tree ``-n 6`` pair: one holder ACTIVE (never idle) for **34.30s** on
        that single statement, a sibling clone's worker blocked **28.54s**
        behind it, and BOTH died -- the waiter on the queue, the holder on its
        own statement inside its own 30s-timed body. That is why the crash only
        ever reproduced on concurrent pairs and never solo: solo, nothing else
        has dirtied the cluster.

        So the shape now is: the read-only diff happens BEFORE the lock (safe --
        the name is per-worker-unique, so nothing else mutates that schema); the
        drift response is a ``public``-schema reset, also before the lock, which
        forces no checkpoint and copies no ``template1``; and the critical
        section holds nothing but the authoritative existence check and
        ``CREATE DATABASE`` -- the one operation the lock exists for. Keep it
        that way: ``test_inf9406_lock_section_never_idles.py`` enforces both
        that everything inside runs on ``conn`` and that no ``DROP DATABASE``,
        ``DROP SCHEMA`` or ``pg_terminate_backend`` ever goes back in.
        """
        target_db = PostgreSQLTestHelper.resolve_test_db_name()
        # Defence-in-depth: never CREATE/connect a name that isn't a test DB.
        validate_database_name(target_db)

        # Connect to default postgres database to create the test database.
        admin_url = PostgreSQLTestHelper.get_test_db_url(database="postgres")
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with admin_engine.connect() as conn:
                # The drift diff runs BEFORE the lock (INF-9406). It is
                # read-only and needs its own connection to target_db, so
                # holding the cluster-wide lock across it is exactly the idle
                # hold that stalls every other worker and clone. This pre-check
                # only decides WHETHER a diff is possible; the authoritative
                # existence check is still taken under the lock below, so
                # TSK-9381's check-then-act closure is untouched. A pre-check
                # that disagreed with it could only happen if another process
                # created or dropped this name mid-call, which per-worker
                # uniqueness rules out -- and either way the in-lock branches
                # below still decide.
                pre_exists = bool(
                    (
                        await conn.execute(
                            text("SELECT 1 FROM pg_database WHERE datname = :name"),
                            {"name": target_db},
                        )
                    ).scalar()
                )
                current_fingerprint = compute_schema_fingerprint()
                drifted = (
                    bool(await PostgreSQLTestHelper._missing_columns(target_db))
                    or await PostgreSQLTestHelper._schema_fingerprint_is_stale(target_db, current_fingerprint)
                    if pre_exists
                    else False
                )

                # Serialize concurrent CREATE DATABASE across xdist workers so
                # template1 is only copied by one session at a time. That copy
                # is the ONLY shared resource here, so it is the only thing this
                # cluster-scoped lock covers -- the drift response is handled
                # below, outside it (INF-9406).
                async with create_database_lock_async(conn):
                    result = await conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :name"),
                        {"name": target_db},
                    )
                    if not result.scalar():
                        # DDL cannot be parameterised; target_db is validated
                        # above and matches ^(giljo_mcp_test|giljo_test)(_gw\d+)?$
                        # (safe id).
                        await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
        finally:
            await admin_engine.dispose()

        # The drift response, and the required extensions, inside the test
        # database itself. Both run OUTSIDE the create-database lock.
        db_url = PostgreSQLTestHelper.get_test_db_url(database=target_db)
        db_engine = create_async_engine(db_url, isolation_level="AUTOCOMMIT")
        try:
            async with db_engine.connect() as conn:
                if drifted:
                    # Stale schema: reset it rather than dropping the database.
                    #
                    # WHY NOT ``DROP DATABASE`` (INF-9406, measured on this
                    # server, PG 18): ``DROP DATABASE`` forces a CLUSTER-WIDE
                    # immediate checkpoint and waits for it, so its cost is a
                    # function of every OTHER worker's dirty buffers rather than
                    # of this database. Measured: 0.47s on an idle cluster,
                    # 34.30s during a concurrent two-tree ``-n 6`` pair -- past
                    # the 30s ``--timeout`` in pyproject.toml, whose
                    # ``thread`` method kills by ``os._exit(1)``, i.e. a dead
                    # xdist worker and a red suite. ``DROP SCHEMA ... CASCADE``
                    # forces NO checkpoint (measured: 0.273s vs 2.000s on the
                    # same populated database, checkpoints_requested +0 vs +1),
                    # and it copies no ``template1``, so it needs no lock.
                    #
                    # It is equivalent for what the guard actually guarantees:
                    # ``_missing_columns`` diffs the ``public`` schema, and
                    # BE-9288 asserts ``public`` is empty afterwards. CASCADE
                    # also removes enum types and sequences, so the caller's
                    # ``create_all`` starts genuinely clean -- dropping only the
                    # tables would leave types behind and break it.
                    #
                    # The terminate stays: unlike ``DROP DATABASE``, which
                    # ERRORS when other sessions are attached, ``DROP SCHEMA``
                    # BLOCKS on their locks. Without it a stray connection turns
                    # a loud failure into a hang, which is worse than the bug.
                    await conn.execute(
                        text(
                            """
                            SELECT pg_terminate_backend(pg_stat_activity.pid)
                            FROM pg_stat_activity
                            WHERE pg_stat_activity.datname = :name
                            AND pid <> pg_backend_pid()
                            """
                        ),
                        {"name": target_db},
                    )
                    await conn.execute(text("DROP SCHEMA public CASCADE"))
                    await conn.execute(text("CREATE SCHEMA public"))
                    # Both environments run the suite as a superuser (local
                    # ``postgres``; CI ``giljo_test``), so this is belt-and-
                    # braces -- it keeps the reset correct for a self-hoster
                    # running the suite as a non-superuser, since PG 15 stopped
                    # granting CREATE on ``public`` to everyone by default.
                    await conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))
                # Recreated last: the reset above drops pg_trgm with the schema.
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

                # INF-9534: stamp the current migration-chain fingerprint and
                # (re)apply the app-role grants unconditionally -- both are
                # idempotent, and running them every bootstrap (not only when
                # ``drifted``) self-heals a database that predates this guard
                # without waiting for its next migration to force a reset.
                await PostgreSQLTestHelper._stamp_schema_fingerprint(conn, current_fingerprint)
                await PostgreSQLTestHelper._ensure_app_role_grants(conn, target_db)
        finally:
            await db_engine.dispose()

    @staticmethod
    async def drop_test_database():
        """
        Drop the test database completely.

        USE WITH CAUTION - This removes all test data.
        Only use for cleanup after test runs.
        """
        target_db = PostgreSQLTestHelper.resolve_test_db_name()
        validate_database_name(target_db)

        admin_url = PostgreSQLTestHelper.get_test_db_url(database="postgres")
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

        try:
            async with admin_engine.connect() as conn:
                # Terminate all connections to the test database
                await conn.execute(
                    text(
                        """
                        SELECT pg_terminate_backend(pg_stat_activity.pid)
                        FROM pg_stat_activity
                        WHERE pg_stat_activity.datname = :name
                        AND pid <> pg_backend_pid()
                        """
                    ),
                    {"name": target_db},
                )

                # Drop the database (target_db validated above as a test DB)
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{target_db}"'))
        finally:
            await admin_engine.dispose()

    @staticmethod
    async def create_test_tables(db_manager: DatabaseManager):
        """
        Create all tables in the test database.

        Args:
            db_manager: DatabaseManager instance for the test database
        """
        await db_manager.create_tables_async()

    # NOTE: ``drop_test_tables`` and ``clean_all_tables`` were removed (BE-6014).
    # They were call-less and catastrophic on a shared test DB — dropping or
    # truncating tables out from under sibling xdist workers. Per-worker DB
    # isolation + per-test transaction rollback (TransactionalTestContext)
    # make them unnecessary. Use ``drop_test_database`` for whole-DB teardown.


def clone_dir_slot() -> str:
    """The numeric clone slot read off the DIRECTORY name ("2" in ``clone_CI2``), or "".

    The counterpart to :func:`clone_slot`, and the two answer different questions
    on purpose:

    * :func:`clone_slot` asks **"which lane am I RUNNING as"** — it reads the
      configured test-DB base, i.e. the pin that is actually in force.
    * this function asks **"which lane SHOULD I be"** — it reads the checkout
      directory, the same source this repo's local suite wrapper derives its base
      from (``clone_CI<N>`` -> ``giljo_mcp_test<N>``).

    They agree exactly when the tree is pinned correctly, and the gap between them
    IS the accident this project exists to make loud: a numbered clone running on
    the unnumbered shared base. Nothing could detect that before, because a single
    derivation cannot disagree with itself.

    Read off ``__file__`` rather than the process working directory. ``local_suite.sh``
    uses ``basename $(pwd)`` because it also reads ``./.env`` and ``./.venv`` and so
    is already anchored at the repo root; pytest carries no such guarantee, and a
    run launched from a subdirectory must not be able to report a different lane
    than the tree it is testing.

    Returns "" for any tree whose directory does not end in digits — the primary
    checkout, a CI runner's workspace, a rename — so callers
    must treat "" as "this tree has no lane of its own", never as lane 0.
    """
    # parents[2] of tests/helpers/test_db_helper.py is the repo root.
    match = re.search(r"CI(\d+)$", Path(__file__).resolve().parents[2].name)
    return match.group(1) if match else ""


def clone_slot() -> str:
    """The numeric clone slot for THIS tree ("6" in ``clone_CI6``), or "" when unnumbered.

    THE ONE ANSWER to "which lane am I". The slot is read off the configured
    test-DB base rather than off the directory name, because the base is what the
    local CI-faithful test runner already derives from the clone directory and
    pins into ``DATABASE_URL`` (``clone_CI6`` -> ``giljo_mcp_test6``). Every
    scratch-DB name that needs lane isolation must call THIS, not re-derive it:
    a second derivation is free to drift away from the first, and the two bare
    literals this function replaced (``giljo_test_bootstrap``, ``giljo_mcp_test9``)
    are what that drift already cost — see INF-9387 and :func:`bootstrap_db_base`.

    Unnumbered bases (CI's ``giljo_test``, the plain local ``giljo_mcp_test``)
    yield "", so callers keep their historical unnumbered name unchanged.
    """
    env_config = PostgreSQLTestHelper._config_from_env()
    base = env_config["database"] if env_config else PostgreSQLTestHelper.DEFAULT_CONFIG["database"]
    # Defensive: a base already carrying a worker suffix must not contribute its
    # worker number as the clone slot.
    slot = re.search(r"(\d+)$", re.sub(r"_gw\d+$", "", base))
    return slot.group(1) if slot else ""


def lane_scratch_db_selector(prefix: str) -> str:
    """A ``LIKE`` pattern matching only THIS lane's databases under ``prefix``.

    ``lane_scratch_db_selector("giljo_test_bootstrap")`` yields
    ``giljo_test_bootstrap2%`` in lane CI2 — that lane's scratch base plus its
    ``_gwN`` variants, and nothing belonging to a sibling lane.

    **It REFUSES rather than returning a slot-less pattern, and the refusal is the
    point of the function.** With no clone slot, ``giljo_test_bootstrap%`` is not
    "my scratch databases", it is *everyone's* — one string meaning both things is
    the defect class this module keeps paying for. A caller that asked for a
    lane-scoped selector and silently received a global one is worse off than one
    that got an exception, because the widened selector still appears to work and
    only reaches other people's databases.

    Measured cost of exactly that widening (2026-08-14): a lane building a local
    reproduction dropped 20 databases with ``LIKE 'giljo_test_bootstrap%'`` — its
    own slot-4 set plus lanes 1, 2 and 3's and the unnumbered default's. Every drop
    succeeded, so nothing live was severed and the scratch DBs self-provision on
    next use; the cost was the cross-lane reach, not the data. The selector should
    have carried the slot digit. The check that was run ("is this drop safe?") and
    the claim that was made ("these are mine") were about different sets.

    Args:
        prefix: A scratch-DB base name WITHOUT its slot digit — e.g.
            ``giljo_test_bootstrap``. An already-slotted name is refused, since it
            would yield ``giljo_test_bootstrap22%``.

    Raises:
        RuntimeError: when this tree has no clone slot, or ``prefix`` is a pattern
            or already carries a slot.
    """
    if not prefix or "%" in prefix:
        raise RuntimeError(
            f"lane_scratch_db_selector({prefix!r}): pass a bare scratch-DB prefix, not a pattern. "
            "This function appends the wildcard itself, so the slot digit cannot be left out of it."
        )
    if re.search(r"\d$", prefix):
        raise RuntimeError(
            f"lane_scratch_db_selector({prefix!r}): the prefix already ends in a digit, so the slot "
            "would be appended twice. Pass the unslotted base name and let this function add the slot."
        )

    slot = clone_slot()
    if not slot:
        raise RuntimeError(
            f"lane_scratch_db_selector({prefix!r}): refusing to build a slot-less selector.\n"
            f"  This tree resolves to an UNNUMBERED test-DB base, so '{prefix}%' would match EVERY "
            f"lane's databases on this server rather than this lane's.\n"
            f"  Fix: run under a numbered clone (clone_CI<N>) with its base pinned via "
            f"DATABASE_URL, or name the databases you mean explicitly instead of matching a pattern."
        )
    return f"{prefix}{slot}%"


def schema_guard_scratch_base() -> str:
    """Base name for the BE-9288 schema-drift guard's throwaway scratch DB, isolated PER CLONE.

    Two properties, and the second was missing until INF-9387:

    * **Slot 9 keeps it clear of real trees.** The guard drops and recreates this
      DB, so it must never be a database a developer is actually running against.
      Real simultaneous clones use the small slots (2, 3, 4 ... 6), so a 9-prefixed
      slot sits outside the range they occupy.
    * **The clone slot keeps it clear of sibling LANES.** The literal
      ``giljo_mcp_test9`` isolated xdist workers within one run (via the caller's
      ``worker_suffix()``) and nothing else: every clone hardcoded the same 9, so
      CI1/CI3/CI4/CI5/CI6 all targeted ``giljo_mcp_test9_gw0..gwN`` at once while
      the ``scratch_db`` fixture force-drops and recreates. One lane's CREATE landed
      between another's DROP and CREATE, or a sibling dropped a scratch DB
      mid-test — red runs on a database belonging to nobody. Appending
      :func:`clone_slot` gives lane CI6 ``giljo_mcp_test96`` and lane CI5
      ``giljo_mcp_test95``.

    Digits are appended with no separator because every name that reaches
    ``get_test_db_url`` must satisfy :data:`WORKER_TEST_DB_PATTERN`, which admits
    only digits and a ``_gwN`` suffix. So one point still rests on convention, as
    it always did: **do not create a clone numbered 9 or 9x** (``clone_CI9``,
    ``CI96``). Such a tree's own base would BE another tree's scratch name — CI9's
    ``giljo_mcp_test9`` is the unnumbered tree's scratch, CI96's is lane 6's — and
    the guard force-drops its scratch, so the collision costs a live database
    rather than a name. Real lanes are CI1-CI6, which is exactly what "outside the
    range real clones use" means. Widening a production-safety allowlist to buy a
    separator would be a far worse trade than keeping this convention.

    Unnumbered bases keep the historical ``giljo_mcp_test9`` exactly.
    """
    return f"giljo_mcp_test9{clone_slot()}"


def bootstrap_db_base() -> str:
    """Base name for the migration-bootstrap scratch DB, isolated PER CLONE (TSK-9381).

    ``GILJO_BOOTSTRAP_TEST_DB`` still wins when set. Otherwise the numeric clone
    slot is carried over from the configured test-DB base, so a clone running on
    ``giljo_mcp_test6`` gets ``giljo_test_bootstrap6`` instead of sharing one
    global ``giljo_test_bootstrap`` with every other clone on the same Postgres.

    THE GAP THIS CLOSES: BE-9373 gave the per-worker test DBs clone isolation via
    ``resolve_test_db_name``, which reads the base out of ``DATABASE_URL``. The
    migration scratch DB was missed because its name is not derived from
    ``DATABASE_URL`` at all — it was a bare literal, and nothing in the tree ever
    set the override. So setting a numbered base isolated a lane's test DBs while
    leaving it sharing the scratch DB, which the migration conftest DROPS and
    RECREATES per worker and the tests run ``upgrade``/``downgrade``/``drop_all``
    against. Two clones running suites at once demolished each other's schema
    mid-test, surfacing as ``UniqueViolation`` on ``pg_type_typname_nsp_index``
    (two concurrent CREATEs in one DB) or ``UndefinedTable`` on a table another
    process had just dropped — a different victim every run, which is what made
    it read as ambient flakiness rather than as an isolation bug.

    Unchanged everywhere it was already correct: CI's base is ``giljo_test`` (no
    digits) and the plain local default is ``giljo_mcp_test`` (no digits), so both
    still resolve to ``giljo_test_bootstrap``. Only a numbered clone moves — which
    is exactly the case that was broken.
    """
    override = os.environ.get("GILJO_BOOTSTRAP_TEST_DB", "")
    if override:
        return override

    return f"giljo_test_bootstrap{clone_slot()}"


class TransactionalTestContext:
    """
    Context manager for transactional test isolation.

    Each test runs in a transaction that is rolled back at the end,
    ensuring clean state for the next test.

    Usage:
        async with TransactionalTestContext(db_manager) as session:
            # Run test with session
            # Changes will be rolled back automatically
    """

    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize transactional context.

        Args:
            db_manager: DatabaseManager for test database
        """
        self.db_manager = db_manager
        self.connection = None
        self.transaction = None
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        """Start connection, transaction and return session."""
        # Get a connection from the engine
        self.connection = await self.db_manager.async_engine.connect()

        # Start a transaction on the connection
        self.transaction = await self.connection.begin()

        # Create session bound to this connection
        self.session = AsyncSession(bind=self.connection, expire_on_commit=False)

        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Rollback transaction and close connection."""
        # Close session first
        if self.session:
            with contextlib.suppress(Exception):
                await self.session.close()
            self.session = None

        # Then rollback transaction
        if self.transaction:
            with contextlib.suppress(Exception):
                await self.transaction.rollback()
            self.transaction = None

        # Finally close connection
        if self.connection:
            with contextlib.suppress(Exception):
                await self.connection.close()
            self.connection = None


async def purge_tenant_rows(db_manager: DatabaseManager, tenant_key: str) -> None:
    """Fixture-layer teardown for suites that COMMIT through real service-owned sessions.

    A suite that exercises services WITHOUT an injected test_session (real
    ``db_manager.get_session_async()`` sessions) commits its rows for real;
    ``TransactionalTestContext`` cannot roll them back, and the committed
    ``test_tenant_*`` rows persist in the per-worker test DB across runs
    (INF-9189: 143 leaked agent_executions rows found on local dev DBs).

    Call this after ``yield`` in the fixture that MINTS the suite's unique
    tenant_key — it deletes every row committed under that tenant, in FK-safe
    order (executions -> jobs -> templates -> projects -> products ->
    sequence runs -> users -> organizations). ``User.org_id`` references
    ``Organization``, so users are always deleted before organizations. The
    tenant-scoped session authorizes the tenant-predicate deletes under the
    fail-closed isolation guard. If a suite starts committing into a table not
    listed here, the FK violation surfaces loudly at teardown — extend the
    order list rather than suppressing it.

    A suite whose tenant has no rows in a given table simply deletes nothing,
    so the extra models are a no-op for the suites that predate them
    (TSK-9199 added SequenceRun/User/Organization for the REST suites that
    seed their own org+user).
    """
    from sqlalchemy import delete

    from giljo_mcp.models import AgentTemplate, Product, Project, User
    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.models.sequence_runs import SequenceRun

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        for model in (
            AgentExecution,
            AgentJob,
            AgentTemplate,
            Project,
            Product,
            SequenceRun,
            User,
            Organization,
        ):
            await session.execute(delete(model).where(model.tenant_key == tenant_key))
        await session.commit()


async def wait_for_database_ready(max_attempts: int = 30, delay: float = 1.0) -> bool:
    """
    Wait for PostgreSQL database to be ready.

    Useful for CI/CD environments where database may be starting up.

    Args:
        max_attempts: Maximum number of connection attempts
        delay: Delay between attempts in seconds

    Returns:
        True if database is ready, False if timeout
    """
    test_url = PostgreSQLTestHelper.get_test_db_url(database="postgres")

    for attempt in range(max_attempts):
        try:
            engine = create_async_engine(test_url)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            return True
        except Exception as _exc:
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)

    return False
