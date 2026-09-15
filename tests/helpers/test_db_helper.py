# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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



PRODUCTION_DB_NAME = "giljo_mcp"
TEST_DB_SUFFIX = "_test"
ALLOWED_TEST_DBS = {
    "giljo_mcp_test",
    "giljo_test",
    "postgres",
}

WORKER_TEST_DB_PATTERN = re.compile(r"^(giljo_mcp_test\d*|giljo_test\d*)(_gw\d+)?$")

DB_CREATE_LOCK_KEY = 7281642



SCHEMA_FINGERPRINT_SCHEMA = "giljo_test_meta"
SCHEMA_FINGERPRINT_TABLE = f'"{SCHEMA_FINGERPRINT_SCHEMA}"."_giljo_test_schema_fingerprint"'

APP_ROLES = ("giljo_owner", "giljo_user")


def _migration_chain_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[2] / "migrations"
    return sorted((root / "versions").glob("*.py")) + sorted((root / "saas_versions").glob("*.py"))


@functools.lru_cache(maxsize=1)
def compute_schema_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in _migration_chain_paths():
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


@contextlib.contextmanager
def create_database_lock(conn):
    conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": DB_CREATE_LOCK_KEY})
    try:
        yield conn
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": DB_CREATE_LOCK_KEY})


@contextlib.asynccontextmanager
async def create_database_lock_async(conn):
    await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": DB_CREATE_LOCK_KEY})
    try:
        yield conn
    finally:
        await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": DB_CREATE_LOCK_KEY})


def worker_suffix() -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    if worker.startswith("gw") and worker[2:].isdigit():
        return f"_{worker}"
    return ""


_worker_suffix = worker_suffix


def validate_database_name(database: str) -> None:
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
    match = re.search(r"/([^/?]+)(?:\?|$)", url)
    if match:
        db_name = match.group(1)
        validate_database_name(db_name)


class PostgreSQLTestHelper:

    DEFAULT_CONFIG = {
        "host": "localhost",
        "port": 5432,
        "database": "giljo_mcp_test",
        "username": "postgres",
        "password": os.environ.get("POSTGRES_SUPERUSER_PASSWORD", ""),
    }

    @staticmethod
    def _config_from_env() -> dict | None:
        import os

        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return None
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
        env_config = PostgreSQLTestHelper._config_from_env()
        base = env_config["database"] if env_config else PostgreSQLTestHelper.DEFAULT_CONFIG["database"]
        if re.fullmatch(r"giljo_mcp_test\d*|giljo_test\d*", base):
            base = f"{base}{_worker_suffix()}"
        return base

    @staticmethod
    def get_test_db_url(database: str | None = None, async_driver: bool = True) -> str:
        if database is None:
            database = PostgreSQLTestHelper.resolve_test_db_name()

        validate_database_name(database)

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
                continue
            missing = [c.name for c in table.columns if c.name not in live_columns[table_name]]
            if missing:
                drift[table_name] = missing
        return drift

    @staticmethod
    async def _schema_fingerprint_is_stale(target_db: str, expected: str) -> bool:
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
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_FINGERPRINT_SCHEMA}"'))
        await conn.execute(text(f"CREATE TABLE IF NOT EXISTS {SCHEMA_FINGERPRINT_TABLE} (fingerprint text NOT NULL)"))
        await conn.execute(text(f"TRUNCATE {SCHEMA_FINGERPRINT_TABLE}"))
        await conn.execute(
            text(f"INSERT INTO {SCHEMA_FINGERPRINT_TABLE} (fingerprint) VALUES (:fp)"),
            {"fp": fingerprint},
        )

    @staticmethod
    async def _ensure_app_role_grants(conn, target_db: str) -> None:
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
        target_db = PostgreSQLTestHelper.resolve_test_db_name()
        validate_database_name(target_db)

        admin_url = PostgreSQLTestHelper.get_test_db_url(database="postgres")
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with admin_engine.connect() as conn:
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

                async with create_database_lock_async(conn):
                    result = await conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :name"),
                        {"name": target_db},
                    )
                    if not result.scalar():
                        await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
        finally:
            await admin_engine.dispose()

        db_url = PostgreSQLTestHelper.get_test_db_url(database=target_db)
        db_engine = create_async_engine(db_url, isolation_level="AUTOCOMMIT")
        try:
            async with db_engine.connect() as conn:
                if drifted:
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
                    await conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

                await PostgreSQLTestHelper._stamp_schema_fingerprint(conn, current_fingerprint)
                await PostgreSQLTestHelper._ensure_app_role_grants(conn, target_db)
        finally:
            await db_engine.dispose()

    @staticmethod
    async def drop_test_database():
        target_db = PostgreSQLTestHelper.resolve_test_db_name()
        validate_database_name(target_db)

        admin_url = PostgreSQLTestHelper.get_test_db_url(database="postgres")
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

        try:
            async with admin_engine.connect() as conn:
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

                await conn.execute(text(f'DROP DATABASE IF EXISTS "{target_db}"'))
        finally:
            await admin_engine.dispose()

    @staticmethod
    async def create_test_tables(db_manager: DatabaseManager):
        await db_manager.create_tables_async()



def clone_dir_slot() -> str:
    match = re.search(r"CI(\d+)$", Path(__file__).resolve().parents[2].name)
    return match.group(1) if match else ""


def clone_slot() -> str:
    env_config = PostgreSQLTestHelper._config_from_env()
    base = env_config["database"] if env_config else PostgreSQLTestHelper.DEFAULT_CONFIG["database"]
    slot = re.search(r"(\d+)$", re.sub(r"_gw\d+$", "", base))
    return slot.group(1) if slot else ""


def lane_scratch_db_selector(prefix: str) -> str:
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
    return f"giljo_mcp_test9{clone_slot()}"


def bootstrap_db_base() -> str:
    override = os.environ.get("GILJO_BOOTSTRAP_TEST_DB", "")
    if override:
        return override

    return f"giljo_test_bootstrap{clone_slot()}"


class TransactionalTestContext:

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.connection = None
        self.transaction = None
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        self.connection = await self.db_manager.async_engine.connect()

        self.transaction = await self.connection.begin()

        self.session = AsyncSession(bind=self.connection, expire_on_commit=False)

        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            with contextlib.suppress(Exception):
                await self.session.close()
            self.session = None

        if self.transaction:
            with contextlib.suppress(Exception):
                await self.transaction.rollback()
            self.transaction = None

        if self.connection:
            with contextlib.suppress(Exception):
                await self.connection.close()
            self.connection = None


async def purge_tenant_rows(db_manager: DatabaseManager, tenant_key: str) -> None:
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
