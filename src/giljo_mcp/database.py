# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
DatabaseManager for Giljo HQ with PostgreSQL support.

Provides connection pooling, tenant isolation, and production-ready database management.
"""

import logging
import os
from contextlib import asynccontextmanager, contextmanager, suppress
from urllib.parse import quote_plus
from uuid import uuid4

from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from .logging.error_codes import ErrorCode
from .models import (
    Base,
)
from .tenant import TenantManager


logger = logging.getLogger(__name__)

# Sprint 002f: Named constants for pool/cache configuration
POOL_RECYCLE_SECONDS = 3600  # 1 hour -- recycle stale DB connections

# INF-3009a: explicit, fixed per-worker pool defaults. These replace the old
# psutil host-RAM heuristic, which mis-sized the pool inside containers (it read
# the HOST's RAM, ignored worker count, and could request ~150 connections/worker
# against a managed Postgres with ~100 total slots). The authoritative knob is now
# DatabaseConfig.pg_pool_size / pg_max_overflow (env: GILJO_PG_POOL_SIZE /
# GILJO_PG_MAX_OVERFLOW); these constants are only the fallback when nothing is set.
# INF-9577: kept in step with DatabaseConfig's defaults -- a fallback that disagreed
# with the configured default would quietly hand any caller that omits the pool args
# double the connections the deployment budget was computed against.
DEFAULT_POOL_SIZE = 5
DEFAULT_MAX_OVERFLOW = 5


def _pgbouncer_connect_args() -> dict | None:
    """asyncpg connect_args that make the async engine safe behind PgBouncer transaction pooling (INF-3009f, P1).

    Under transaction pooling a server connection is returned to the pool at every
    COMMIT/ROLLBACK, so asyncpg's client-side prepared statements (default cache
    size 100, names like ``__asyncpg_stmt_<n>__``) collide or vanish across server
    connections and raise ``DuplicatePreparedStatementError`` /
    ``InvalidSQLStatementName`` under concurrency. Setting both caches to 0 disables
    the automatic prepared statements; the unique ``prepared_statement_name_func`` is
    still required because ``pool_pre_ping``'s ping (which we run) emits a prepared
    statement even at cache size 0 (SQLAlchemy issue #10226).

    Gated on ``GILJO_PGBOUNCER=1`` so the default (a direct connection) keeps
    prepared-statement performance and stays byte-identical: the flag off returns
    ``None`` and the caller adds NO ``connect_args`` at all. A deployment enables it
    only once its app URL points at PgBouncer.
    """
    if os.getenv("GILJO_PGBOUNCER") != "1":
        return None
    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


# BE-6063c: the tenant-isolation guard (CE/SaaS model registry, the do_orm_execute
# AST-walk enforcement + its shape memo, bypass/context managers, event listeners) was
# extracted to tenant_guard.py to keep this file under the 800-line CI guardrail. Importing
# it here registers the SQLAlchemy event listeners (import side effect) and re-exports every
# public name so all `giljo_mcp.database.<name>` import paths are unchanged.
from . import tenant_guard as _tenant_guard  # noqa: E402  (after logger/constants above)
from .tenant_guard import (  # noqa: E402,F401  (re-exported for back-compat)
    TENANT_BYPASS_MODELS_KEY,
    TENANT_BYPASS_REASON_KEY,
    TENANT_CONTEXT_SOURCE_KEY,
    TenantIsolationError,
    register_tenant_scoped_models,
    tenant_isolation_bypass,
    tenant_session_context,
)


def __getattr__(name: str):
    # Delegate the PEP 562 live-union names (and any other public guard symbol) to
    # tenant_guard so `giljo_mcp.database.TENANT_SCOPED_MODELS` keeps working post-extraction.
    return getattr(_tenant_guard, name)


class DatabaseManager:
    """
    Manages PostgreSQL database connections.

    Features:
    - PostgreSQL connection pooling
    - Multi-tenant isolation through filtered queries
    - High-performance async support
    - Production-ready configuration
    """

    def __init__(
        self,
        database_url: str | None = None,
        is_async: bool = False,
        pool_size: int | None = None,
        max_overflow: int | None = None,
        use_null_pool: bool = False,
    ):
        """
        Initialize DatabaseManager.

        Args:
            database_url: PostgreSQL connection URL. Required.
            is_async: Whether to use async engine and sessions.
            pool_size: Connection pool size per worker. Defaults to
                ``DEFAULT_POOL_SIZE`` (a fixed constant) when not set — NO longer
                derived from host RAM (INF-3009a). The authoritative value comes
                from DatabaseConfig.pg_pool_size (env GILJO_PG_POOL_SIZE).
            max_overflow: Max overflow connections per worker. Defaults to
                ``DEFAULT_MAX_OVERFLOW`` when not set (DatabaseConfig.pg_max_overflow
                / env GILJO_PG_MAX_OVERFLOW).
            use_null_pool: When True, use SQLAlchemy ``NullPool`` (no pooling —
                each checkout opens a fresh connection and closes it on return).
                Intended for the test harness: under pytest-xdist many worker
                processes each open an engine, and a retained per-engine pool
                quickly exhausts PostgreSQL ``max_connections``. NullPool holds
                no idle connections, so aggregate usage stays bounded. Production
                leaves this False and keeps the QueuePool. ``pool_size`` and
                ``max_overflow`` are ignored when True.
        """
        if not database_url:
            raise ValueError("Database URL is required")

        self.database_url = database_url
        self.is_async = is_async
        self.use_null_pool = use_null_pool

        # INF-3009a: fixed, explicit pool sizing. When a value is not supplied,
        # fall back to fixed constants — never to a host-RAM heuristic.
        if pool_size is None:
            pool_size = DEFAULT_POOL_SIZE
        if max_overflow is None:
            max_overflow = DEFAULT_MAX_OVERFLOW

        self.pool_size = pool_size
        self.max_overflow = max_overflow

        # Validate database URL - PostgreSQL only
        if "postgresql" not in self.database_url:
            raise ValueError("Only PostgreSQL databases are supported")

        # Initialize engines and session factories
        if self.is_async:
            self.async_engine = self._create_async_engine()
            self.AsyncSessionLocal = sessionmaker(self.async_engine, class_=AsyncSession, expire_on_commit=False)
        else:
            self.engine = self._create_sync_engine()
            self.SessionLocal = scoped_session(sessionmaker(self.engine, expire_on_commit=False))

    def _create_sync_engine(self) -> Engine:
        """Create synchronous PostgreSQL engine with optimized settings."""
        if self.use_null_pool:
            # NullPool ignores pool_size/max_overflow/pool_recycle (no pooling).
            return create_engine(
                self.database_url,
                poolclass=NullPool,
                pool_pre_ping=True,
                echo=False,
            )
        return create_engine(
            self.database_url,
            poolclass=QueuePool,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_pre_ping=True,
            pool_recycle=POOL_RECYCLE_SECONDS,
            echo=False,
        )

    def _create_async_engine(self) -> AsyncEngine:
        """Create asynchronous PostgreSQL engine with optimized settings."""
        async_url = self.database_url

        if async_url.startswith("postgresql://"):
            async_url = async_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        # INF-3009f (P1): when GILJO_PGBOUNCER=1, disable asyncpg prepared statements so
        # the engine is safe behind PgBouncer transaction pooling. Flag off -> None ->
        # no connect_args passed -> byte-identical to the pre-INF-3009f behavior.
        pgbouncer_args = _pgbouncer_connect_args()
        extra_args = {"connect_args": pgbouncer_args} if pgbouncer_args else {}

        if self.use_null_pool:
            # NullPool ignores pool_size/max_overflow/pool_recycle (no pooling).
            return create_async_engine(
                async_url,
                poolclass=NullPool,
                pool_pre_ping=True,
                echo=False,
                **extra_args,
            )
        return create_async_engine(
            async_url,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_pre_ping=True,
            pool_recycle=POOL_RECYCLE_SECONDS,
            echo=False,
            **extra_args,
        )

    def create_tables(self):
        """Create all database tables (sync)."""
        if not self.is_async:
            Base.metadata.create_all(bind=self.engine)
        else:
            raise RuntimeError("Use create_tables_async() for async engine")

    async def create_tables_async(self):
        """
        Create all database tables (async).

        Handover 0017: pg_trgm extension is created during installation by installer/core/database.py
        with proper superuser privileges. Application does not require CREATE privilege on database.

        BE-3002a (schema source of truth): Alembic is the authoritative schema
        writer. When the database is already Alembic-managed (an ``alembic_version``
        table is present), ``create_all`` is redundant and is SKIPPED so boot
        performs ZERO DDL — Alembic's migration chain is the single source of
        truth (SaaS prod runs ``alembic upgrade heads`` via the platform's
        pre-deploy hook; CE runs it in startup.py before the API boots). Only a
        fresh, un-migrated
        database — i.e. the test-suite per-worker bootstrap, which never runs
        migrations and so has no ``alembic_version`` — falls through to create_all.
        """
        if not self.is_async:
            raise RuntimeError("Use create_tables() for async engine")
        async with self.async_engine.begin() as conn:
            already_managed = await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table("alembic_version"))
            if already_managed:
                logger.info(
                    "Skipping create_all -- schema is Alembic-managed (alembic_version present); "
                    "migrations are the single source of truth"
                )
                return
            # Fresh un-migrated DB (dev / test bootstrap): create the schema.
            # Extensions are created during installation phase, not at runtime.
            await conn.run_sync(Base.metadata.create_all)

    def drop_tables(self):
        """Drop all database tables (sync). USE WITH CAUTION!"""
        if not self.is_async:
            Base.metadata.drop_all(bind=self.engine)
        else:
            raise RuntimeError("Use drop_tables_async() for async engine")

    async def drop_tables_async(self):
        """Drop all database tables (async). USE WITH CAUTION!"""
        if self.is_async:
            async with self.async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        else:
            raise RuntimeError("Use drop_tables() for sync engine")

    @contextmanager
    def get_session(self, tenant_key: str | None = None) -> Session:
        """
        Get a database session (sync).

        Usage:
            with db_manager.get_session() as session:
                # Use session
        """
        if self.is_async:
            raise RuntimeError("Use get_session_async() for async operations")

        session = self.SessionLocal()
        effective_tenant_key = tenant_key or TenantManager.get_current_tenant()
        if effective_tenant_key:
            session.info["tenant_key"] = effective_tenant_key
            session.info[TENANT_CONTEXT_SOURCE_KEY] = "service"
        try:
            yield session
            session.commit()
        except (RuntimeError, OSError):
            session.rollback()
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def get_session_async(self, tenant_key: str | None = None) -> AsyncSession:
        """
        Get a database session (async) with automatic cleanup.

        Usage:
            async with db_manager.get_session_async() as session:
                # Use session

        Note:
            Handles GeneratorExit (BaseException) from FastAPI HTTPException.
            Ensures rollback before close when session is active to prevent
            IllegalStateChangeError.
        """
        if not self.is_async:
            raise RuntimeError("Use get_session() for sync operations")

        session = self.AsyncSessionLocal()
        effective_tenant_key = tenant_key or TenantManager.get_current_tenant()
        if effective_tenant_key:
            session.info["tenant_key"] = effective_tenant_key
            session.info[TENANT_CONTEXT_SOURCE_KEY] = "service"
        try:
            yield session
            await session.commit()
        except GeneratorExit:
            # GeneratorExit is BaseException (not Exception) - raised by FastAPI
            # when HTTPException occurs or client disconnects
            if hasattr(session, "is_active") and session.is_active:
                with suppress(RuntimeError, OSError):
                    await session.rollback()
            raise
        except Exception as _exc:  # Broad catch: session cleanup resilience
            # Regular exceptions - rollback and re-raise
            try:
                await session.rollback()
            except (SQLAlchemyError, RuntimeError) as rollback_error:
                logger.error(
                    "session_rollback_failed error_code=%s error_message=%s",
                    ErrorCode.DB_TRANSACTION_ROLLBACK.value,
                    str(rollback_error),
                    exc_info=True,
                )
            raise
        finally:
            # Always close session - but check state first to prevent IllegalStateChangeError
            if hasattr(session, "is_active") and session.is_active:
                with suppress(RuntimeError, OSError):
                    await session.rollback()
            try:
                await session.close()
            except (RuntimeError, OSError, SQLAlchemyError) as close_error:
                logger.debug(f"Session close during cleanup: {close_error}")

    def close(self):
        """Close database connections (sync)."""
        if not self.is_async:
            self.SessionLocal.remove()
            self.engine.dispose()
        else:
            raise RuntimeError("Use close_async() for async engine")

    async def close_async(self):
        """Close database connections (async)."""
        if self.is_async:
            await self.async_engine.dispose()
        else:
            raise RuntimeError("Use close() for sync engine")

    @staticmethod
    def build_postgresql_url(  # nosec B107
        host: str = "localhost",
        port: int = 5432,
        database: str = "giljo_mcp",
        username: str = "postgres",
        password: str = "",
    ) -> str:
        """
        Build a PostgreSQL connection URL.

        Args:
            host: Database host
            port: Database port
            database: Database name
            username: Database username
            password: Database password

        Returns:
            PostgreSQL connection URL
        """
        if password:
            password = quote_plus(password)
            return f"postgresql://{username}:{password}@{host}:{port}/{database}"
        return f"postgresql://{username}@{host}:{port}/{database}"

    @asynccontextmanager
    async def get_tenant_session_async(self, tenant_key: str):
        """
        Get an async session with automatic tenant filtering.

        Args:
            tenant_key: Tenant key for this session

        Yields:
            AsyncSession configured with tenant context
        """
        with TenantManager.with_tenant(tenant_key):
            async with self.get_session_async() as session:
                # Add tenant key to session info for reference
                session.info["tenant_key"] = tenant_key
                yield session


# Module-level database manager holder
class _DatabaseManagerHolder:
    """Lazy singleton holder to avoid global statement."""

    _instance: DatabaseManager | None = None

    @classmethod
    def get_instance(cls, database_url: str | None = None, is_async: bool = False) -> DatabaseManager:
        if cls._instance is None or (database_url and cls._instance.database_url != database_url):
            cls._instance = DatabaseManager(database_url, is_async)
        return cls._instance

    @classmethod
    def set_instance(cls, manager: DatabaseManager):
        cls._instance = manager


def get_db_manager(database_url: str | None = None, is_async: bool = False) -> DatabaseManager:
    """
    Get or create the global DatabaseManager instance.

    Args:
        database_url: Database connection URL
        is_async: Whether to use async operations

    Returns:
        DatabaseManager instance
    """
    return _DatabaseManagerHolder.get_instance(database_url, is_async)


def set_db_manager(manager: DatabaseManager):
    """Set the global DatabaseManager instance."""
    _DatabaseManagerHolder.set_instance(manager)
