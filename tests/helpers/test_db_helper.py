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
import os
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import Base


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
_DB_CREATE_LOCK_KEY = 7281642

# Test engines use SQLAlchemy NullPool (DatabaseManager(use_null_pool=True)) so
# no idle connections are retained between checkouts. Under pytest-xdist many
# worker processes each open an engine; a retained per-engine pool would exhaust
# PostgreSQL ``max_connections``. NullPool keeps aggregate usage bounded.


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
        mutate one another's schema. The suffix is applied to either recognized test
        DB base name; ``_worker_suffix()`` returns "" off-xdist, so serial callers
        (the CI integration / test-saas steps, plain local runs) keep the bare
        ``giljo_test`` / ``giljo_mcp_test`` name unchanged.
        """
        env_config = PostgreSQLTestHelper._config_from_env()
        base = env_config["database"] if env_config else PostgreSQLTestHelper.DEFAULT_CONFIG["database"]
        if base in ("giljo_mcp_test", "giljo_test"):
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
        (``_missing_columns``, narrow by design) and, on drift, the DB is
        dropped and recreated so the bootstrap ``create_all`` starts clean.

        Drop+recreate (rather than failing loudly) is the chosen response
        because it IS race-safe here: the target DB name is per-worker-unique
        (``resolve_test_db_name``), so no sibling xdist worker ever targets
        this same name, and the whole drop+recreate below runs while this call
        still holds ``_DB_CREATE_LOCK_KEY`` -- the same process-wide advisory
        lock that already serializes CREATE DATABASE against the
        ``template1``-copy race -- so no other process can be mid CREATE
        against ANY test DB while this one is dropped and recreated.
        """
        target_db = PostgreSQLTestHelper.resolve_test_db_name()
        # Defence-in-depth: never CREATE/connect a name that isn't a test DB.
        validate_database_name(target_db)

        # Connect to default postgres database to create the test database.
        admin_url = PostgreSQLTestHelper.get_test_db_url(database="postgres")
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with admin_engine.connect() as conn:
                # Serialize concurrent CREATE DATABASE across xdist workers so
                # template1 is only copied by one session at a time. Also
                # covers the drop+recreate drift path below -- see docstring.
                await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _DB_CREATE_LOCK_KEY})
                try:
                    result = await conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :name"),
                        {"name": target_db},
                    )
                    if not result.scalar():
                        # DDL cannot be parameterised; target_db is validated
                        # above and matches ^(giljo_mcp_test|giljo_test)(_gw\d+)?$
                        # (safe id).
                        await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                    elif await PostgreSQLTestHelper._missing_columns(target_db):
                        # Stale schema: reuse the existing drop path, then the
                        # same CREATE statement as the fresh-DB branch above.
                        await PostgreSQLTestHelper.drop_test_database()
                        await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                finally:
                    await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _DB_CREATE_LOCK_KEY})
        finally:
            await admin_engine.dispose()

        # Ensure required extensions exist inside the test database itself.
        db_url = PostgreSQLTestHelper.get_test_db_url(database=target_db)
        db_engine = create_async_engine(db_url, isolation_level="AUTOCOMMIT")
        try:
            async with db_engine.connect() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
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
